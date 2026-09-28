"""Original 5D PC Connect exchanges; see tests/fixtures/README.md for evidence.

Identification, owner, release-control setup/teardown, and entry have been tested
on the original 5D. Only these documented operations are exposed.
"""

import struct

from .cameras import owner_bytes
from .errors import ProtocolError


class PCConnectResponseError(ProtocolError):
    def __init__(self, code, payload):
        self.code, self.payload = code, payload
        super().__init__("PC Connect operation failed: 0x%02x" % code)


def entry_packet():
    packet = bytearray(0x74)
    struct.pack_into("<II", packet, 0, 0x34, 0x201)
    packet[0x40] = 2
    struct.pack_into("<III", packet, 0x44, 0x12100006, 0x34, 0x200)
    event = b"$EV#OP$SetUSBToDCPMode"
    packet[0x50:0x50 + len(event)] = event
    return bytes(packet)


class PCConnect:
    def __init__(self, transport):
        self.transport = transport
        self.serial = 3
        self.remote_started = False

    def _control_read(self, request, value, length):
        reply = self.transport.control(0xC0, request, value, length)
        if len(reply) != length:
            raise ProtocolError("Short PC Connect control reply")
        return reply

    def _control_write(self, value, packet):
        if self.transport.control(0x40, 4, value, packet) != len(packet):
            raise ProtocolError("Short PC Connect control write")

    def initialize(self):
        state = self._control_read(0x0C, 0x55, 1)
        if state not in (b"A", b"C"):
            raise ProtocolError("Unknown PC Connect initialization state")
        greeting = self._control_read(4, 1, 0x58)
        if state == b"A":
            self._control_read(4, 4, 0x50)
        else:
            wake = struct.pack("<I", 0x10) + bytes(0x3C) + greeting[0x48:0x58]
            self._control_write(0x11, wake)
            reply = self.transport.read(0x81, 0x44)
            if len(reply) != 0x44 or reply[:4] != b"\x04\0\0\0":
                raise ProtocolError("Unexpected PC Connect wake reply")
            # The reference interposer did not record interrupt transfers.
            # This 16-byte wait is documented by the upstream Class-6 handshake.
            interrupt = b""
            for _ in range(4):
                interrupt += self.transport.read(0x83, 16, timeout=1000)
                if len(interrupt) >= 16:
                    break
            if len(interrupt) != 16:
                raise ProtocolError("Incomplete PC Connect wake interrupt")

    def _command(self, command, payload=b""):
        allowed = (command in (1, 5) and not payload) or (
            command == 0x25 and payload in (
                struct.pack("<II", 0, 0) + b"\0",
                struct.pack("<II", 10, 0) + b"\0",
                struct.pack("<II", 1, 0) + b"\0",
            )
        )
        if not allowed:
            raise ProtocolError("PC Connect command not allowed")
        packet = bytearray(0x50)
        length = 0x10 + len(payload)
        struct.pack_into("<II", packet, 0, length, 0x201)
        packet[0x40] = 2
        struct.pack_into("<III", packet, 0x44, 0x12100000 | command, length, self.serial)
        packet += payload
        serial = self.serial
        self.serial += 4
        self._control_write(0x10, packet)
        reply = self.transport.read(0x81, 512)
        if len(reply) < 0x54:
            raise ProtocolError("Truncated PC Connect reply")
        length, kind = struct.unpack_from("<II", reply)
        operation, repeated_length, transaction, status = struct.unpack_from("<IIII", reply, 0x44)
        if (length + 0x40 != len(reply) or repeated_length != length or kind != 0x301
                or operation != (0x22100000 | command) or transaction != serial):
            raise ProtocolError("Unexpected PC Connect reply")
        if status != 0:
            raise PCConnectResponseError(status, reply[0x54:])
        return reply[0x54:]

    def identify(self):
        reply = self._command(1)
        if len(reply) != 72:
            raise ProtocolError("Unexpected PC Connect identification length")
        try:
            model = reply[8:40].split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise ProtocolError("Invalid camera model name") from error
        return model, reply[4:8]

    def owner(self):
        return owner_bytes(self._command(5))

    def prepare_entry(self):
        # A previous process may have left release control active. End it before
        # initialization; close() accepts only the verified already-inactive reply.
        self.remote_started = True
        self.close()
        self.remote_started = True  # Also clean up if initialization's reply is lost.
        for subcommand in (0, 10):
            reply = self._command(0x25, struct.pack("<II", subcommand, 0) + b"\0")
            if len(reply) < 8 or struct.unpack_from("<I", reply)[0] != subcommand:
                raise ProtocolError("Unexpected PC Connect release-control reply")
            if subcommand == 10 and struct.unpack_from("<I", reply, 4)[0] != len(reply) - 8:
                raise ProtocolError("Truncated PC Connect parameter data")

    def enter_dcp(self):
        self._control_write(0x10, entry_packet())
        # Re-enumeration must establish success; the camera disconnects here.

    def close(self):
        if self.remote_started:
            expected = struct.pack("<II", 1, 0)
            try:
                reply = self._command(0x25, expected + b"\0")
            except PCConnectResponseError as error:
                # The tested 5D returns 0x86 when release control is inactive.
                if error.code != 0x86 or error.payload != expected:
                    raise
            else:
                if reply != expected:
                    raise ProtocolError("Unexpected PC Connect release-control exit reply")
            self.remote_started = False
