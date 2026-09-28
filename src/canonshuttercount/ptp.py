"""Print/PTP sessions and the original 5D's read-only identity properties."""

import struct
import time

from .cameras import owner_bytes
from .errors import ProtocolError, TransferTimeout


class PTPResponseError(ProtocolError):
    def __init__(self, code):
        self.code = code
        super().__init__("PTP operation failed: 0x%04x" % code)


class PTP:
    def __init__(self, transport):
        self.transport = transport
        self.transaction = 0
        self.buffer = b""
        self.opened = False

    def _send(self, operation, params=()):
        transaction = self.transaction
        self.transaction += 1
        packet = struct.pack("<IHHI", 12 + 4 * len(params), 1, operation, transaction)
        packet += struct.pack("<" + "I" * len(params), *params)
        if self.transport.write(2, packet) != len(packet):
            raise ProtocolError("Short PTP command write")
        return transaction

    def _receive(self, transaction, deadline):
        while True:
            if len(self.buffer) >= 12:
                length, kind, code, received_transaction = struct.unpack_from("<IHHI", self.buffer)
                # All supported identity properties fit within this bound.
                if not 12 <= length <= 4096:
                    raise ProtocolError("Invalid PTP container length")
                if len(self.buffer) >= length:
                    payload, self.buffer = self.buffer[12:length], self.buffer[length:]
                    if received_transaction != transaction:
                        raise ProtocolError("Wrong PTP transaction ID")
                    return kind, code, payload
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransferTimeout("PTP reply deadline exceeded")
            chunk = self.transport.read(0x81, 512, timeout=max(1, int(remaining * 1000)))
            if not chunk:
                raise ProtocolError("Empty PTP transfer before completion")
            self.buffer += chunk

    def _command(self, operation, params=(), output=False):
        allowed = ((operation == 0x1002 and params == (1,) and not output)
                   or (operation == 0x1003 and not params and not output)
                   or (operation == 0x1015 and params in ((0xD031,), (0xD032,), (0xD033,)) and output))
        if not allowed:
            raise ProtocolError("PTP operation not allowed")
        transaction = self._send(operation, params)
        deadline = time.monotonic() + 5
        kind, code, data = self._receive(transaction, deadline)
        if kind == 3 and code != 0x2001:
            raise PTPResponseError(code)
        if output:
            if (kind, code) != (2, operation):
                raise ProtocolError("Expected PTP property data")
            kind, code, _ = self._receive(transaction, deadline)
        if (kind, code) != (3, 0x2001):
            raise ProtocolError("Unexpected PTP completion: 0x%04x" % code)
        return data if output else None

    def initialize(self):
        try:
            self._command(0x1002, (1,))
        except PTPResponseError as error:
            if error.code != 0x201E:  # SessionAlreadyOpen after an interrupted run.
                raise
            self._command(0x1003)
            self.transaction = 0  # OpenSession always starts at transaction zero.
            self._command(0x1002, (1,))  # Exactly one recovery attempt.
        self.opened = True

    def identify(self):
        model = self._command(0x1015, (0xD032,), output=True)
        if not model or model[0] < 1 or len(model) != 1 + model[0] * 2 or model[-2:] != b"\0\0":
            raise ProtocolError("Malformed PTP model string")
        try:
            name = model[1:-2].decode("utf-16-le")
        except UnicodeDecodeError as error:
            raise ProtocolError("Malformed PTP model encoding") from error
        firmware = self._command(0x1015, (0xD031,), output=True)
        if len(firmware) != 4:
            raise ProtocolError("Unexpected firmware property length")
        return name, firmware

    def owner(self):
        data = self._command(0x1015, (0xD033,), output=True)
        if len(data) < 4 or struct.unpack_from("<I", data)[0] != len(data) - 4:
            raise ProtocolError("Malformed PTP owner array")
        return owner_bytes(data[4:])

    def prepare_entry(self):
        pass

    def enter_dcp(self):
        self._send(0x901F, (3,))
        # A reply is not required: this operation disconnects the PTP interface.
        # The caller must confirm re-enumeration and still recover on write errors.

    def close(self):
        if self.opened:
            self._command(0x1003)
            self.opened = False
