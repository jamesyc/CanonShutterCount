"""Bounded diagnostic monitor protocol, reproduced from the successful 5D trace."""

import struct

from .cameras import EOS_5D
from .errors import ProtocolError, TransferTimeout


def words(*values):
    return struct.pack("<" + "I" * len(values), *values)


def frame(kind, executor, sequence, payload=b""):
    body = (b"EVNTPROCEXE\0" + words(0)
            + struct.pack("<HHHI", kind, executor, sequence, len(payload)) + payload)
    return words(2, len(body)) + body


class DCP:
    def __init__(self, transport, profile=EOS_5D):
        self.transport = transport
        self.profile = profile
        self.executor = 1
        self.sequence = 0x41

    def control(self, value, size):
        if self.transport.control(0x40, 0, value, words(size)) != 4:
            raise ProtocolError("Short DCP control write")
        if self.transport.control(0xC0, 0, 0, 2) != b"\0\0":
            raise ProtocolError("Nonzero DCP transport status")

    def send(self, packet):
        self.control(0x0E, len(packet))
        if self.transport.write(2, packet) != len(packet):
            raise ProtocolError("Short DCP bulk write")

    def receive(self, allocate=False, output=False):
        for _ in range(12):
            try:
                reply = self.transport.read(0x83, 64, timeout=1000)
            except TransferTimeout:
                continue
            if (len(reply) < 44 or reply[:4] != bytes.fromhex("efcdab89")
                    or reply[16:27] != b"EVNTPROCEXE"):
                continue
            envelope = struct.unpack_from("<I", reply, 8)[0]
            sequence = struct.unpack_from("<H", reply, 38)[0]
            if envelope != 2 or sequence != self.sequence:
                continue
            kind, subtype = struct.unpack_from("<HH", reply, 32)
            executor = struct.unpack_from("<H", reply, 36)[0]
            if not allocate and executor != self.executor:
                continue
            size = struct.unpack_from("<I", reply, 40)[0]
            if 44 + size > len(reply):
                raise ProtocolError("Truncated DCP reply")
            if allocate and kind == 1 and size == 2:
                return reply[44:46]
            if not allocate and kind == 2 and subtype == (3 if output else 1):
                if size < 4 or struct.unpack_from("<I", reply, 44)[0] != 0:
                    raise ProtocolError("Camera diagnostic procedure failed")
                return reply[44:44 + size]
        raise ProtocolError("No matching DCP completion")

    def call(self, name):
        if name not in ("MonOpen", "MonClose", "SetUSBToPTPMode"):
            raise ProtocolError("Diagnostic procedure not allowed")
        self.sequence += 1
        self.send(frame(5, self.executor, self.sequence, name.encode("ascii") + b"\0" + words(0, 0)))
        self.receive()

    def initialize(self):
        for _ in range(8):
            try:
                self.transport.read(0x83, 64, timeout=30)
            except TransferTimeout:
                break
        self.control(0x10, 0)
        self.send(words(0, 12, 1, 4, 0))
        for service in (b"EVNTPROCEXE", b"MEMMNGR"):
            body = (words(1) + service.ljust(12, b"\0") + words(132, 0)
                    + b"SERVER\\1.00\\CAMERA\\PROTO\\SERIAL_NUMBER\0".ljust(128, b"\0"))
            self.send(words(1, len(body)) + body)
            body = words(3) + service.ljust(12, b"\0") + words(4, 0)
            self.send(words(1, len(body)) + body)
        self.send(frame(1, 0, self.sequence))
        self.executor = struct.unpack("<H", self.receive(allocate=True))[0]
        if not self.executor:
            raise ProtocolError("Camera returned executor zero")

    def read(self, address, length=12):
        if (address, length) not in self.profile.chunks:
            raise ProtocolError("Memory read is outside the camera profile")
        self.sequence += 1
        payload = b"MonReadAndGetData\0" + words(4)
        for value in (length, self.profile.memory_kind, address, length):
            payload += words(2, value, 0, 0, 0)
        self.send(frame(7, self.executor, self.sequence, payload + words(0)))
        reply = self.receive(output=True)
        if len(reply) != 8 + length or struct.unpack_from("<I", reply, 4)[0] != length:
            raise ProtocolError("Unexpected diagnostic output length")
        return reply[8:]
