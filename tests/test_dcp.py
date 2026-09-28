import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock

from canonshuttercount.dcp import DCP, frame
from canonshuttercount.errors import ProtocolError, TransferTimeout

FIXTURES = Path(__file__).parent / "fixtures"


class Replay:
    def __init__(self):
        self.groups = []
        self.pending = []
        self.index = 0
        self.control_size = None
        for line in (FIXTURES / "dcp.log").read_text().splitlines():
            if line.startswith("OUT "):
                self.groups.append((bytes.fromhex(line[4:]), []))
            else:
                self.groups[-1][1].append(bytes.fromhex(line[3:]))

    def control(self, kind, request, value, data):
        assert request == 0
        if kind == 0x40:
            assert value in (0x10, 0x0E) and len(data) == 4
            self.control_size = struct.unpack("<I", data)[0]
            return 4
        assert (kind, value, data) == (0xC0, 0, 2)
        return b"\0\0"

    def write(self, endpoint, packet):
        assert endpoint == 2 and not self.pending
        assert self.control_size == len(packet)
        expected, replies = self.groups[self.index]
        assert packet == expected, self.index
        self.pending = list(replies)
        self.index += 1
        return len(packet)

    def read(self, endpoint, size, timeout=3000):
        assert endpoint == 0x83 and size == 64
        if not self.pending:
            raise TransferTimeout()
        return self.pending.pop(0)


class DCPTests(unittest.TestCase):
    def test_complete_saved_session(self):
        transport = Replay()
        service = DCP(transport)
        service.initialize()
        service.call("MonOpen")
        window = service.read(0x938) + service.read(0x944)
        samples = json.loads((FIXTURES / "counter.json").read_text())
        self.assertEqual(window.hex(), samples["after"])
        service.call("MonClose")
        service.call("SetUSBToPTPMode")
        self.assertEqual(transport.index, len(transport.groups))
        self.assertFalse(transport.pending)

    def test_unapproved_operation_never_reaches_transport(self):
        transport = Mock()
        service = DCP(transport)
        for action in (lambda: service.call("MonWrite"),
                       lambda: service.call("SetUSBToStandardMode"),
                       lambda: service.call("RefreshUSBMode"),
                       lambda: service.call("SetUSBToFactoryMode"),
                       lambda: service.read(0x900), lambda: service.read(0x938, 24)):
            with self.assertRaises(ProtocolError):
                action()
        self.assertFalse(transport.mock_calls)

    def test_allocation_packet(self):
        self.assertEqual(frame(1, 0, 0x41).hex(), "020000001a00000045564e5450524f43455845000000000001000000410000000000")

    def test_timeout_is_bounded(self):
        transport = Mock()
        transport.read.side_effect = TransferTimeout()
        with self.assertRaises(ProtocolError):
            DCP(transport).receive()
        self.assertEqual(transport.read.call_count, 12)

    def test_corrupt_completion_rejected(self):
        transport = Replay()
        service = DCP(transport)
        service.initialize()
        service.call("MonOpen")
        # Use a recorded completion, changing only its declared body length/status.
        completion = next(r for _, replies in transport.groups for r in replies
                          if len(r) >= 48 and r[32:36] == b"\x02\0\x01\0")
        for size, status in ((1000, 0), (0, 0), (4, 1)):
            reply = bytearray(completion)
            struct.pack_into("<H", reply, 38, service.sequence)
            struct.pack_into("<II", reply, 40, size, status)
            mock = Mock()
            mock.read.return_value = bytes(reply)
            service.transport = mock
            with self.subTest(size=size, status=status), self.assertRaises(ProtocolError):
                service.receive()
