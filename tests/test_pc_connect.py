import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock

from canonshuttercount.cameras import EOS_5D, validate_identity
from canonshuttercount.errors import ProtocolError
from canonshuttercount.pc_connect import PCConnect, entry_packet


class Replay:
    def __init__(self):
        self.records = json.loads((Path(__file__).parent / "fixtures/pc_connect.json").read_text())
        cleanup = json.loads((Path(__file__).parent / "fixtures/pc_connect_end_inactive.json").read_text())
        self.records[8:8] = cleanup
        # New recovery command precedes the old capture's release initialization.
        # Renumber only transaction IDs; all other recorded bytes are unchanged.
        for i, row in enumerate(self.records[8:]):
            packet = bytearray.fromhex(row["data"])
            struct.pack_into("<I", packet, 0x4C, 0x1B + 4 * (i // 2))
            row["data"] = packet.hex()
        self.index = 0

    def control(self, kind, request, value, data):
        row = self.records[self.index]
        self.index += 1
        expected = bytes.fromhex(row["data"])
        assert row["args"] == [kind, request, value, 0]
        if kind == 0xC0:
            assert row["kind"] == "CTRL_IN" and data == len(expected)
            return expected
        assert row["kind"] == "CTRL_OUT" and bytes(data) == expected
        return len(data)

    def read(self, endpoint, size, timeout=3000):
        if endpoint == 0x83:
            # Synthetic handshake completion; missing from the original capture.
            assert size == 16
            return bytes(16)
        row = self.records[self.index]
        self.index += 1
        assert row["kind"] == "BULK_IN" and row["args"][0] == endpoint
        result = bytes.fromhex(row["data"])
        assert len(result) <= size
        return result


class PCConnectTests(unittest.TestCase):
    def test_release_exit_accepts_only_success_or_exact_already_inactive_reply(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/pc_connect_end_inactive.json").read_text())
        for status, subcommand, success in ((0, 1, True), (0x86, 1, True), (0x87, 1, False), (0x86, 2, False), (0, 2, False)):
            reply = bytearray.fromhex(fixture[1]["data"])
            struct.pack_into("<II", reply, 0x50, status, subcommand)
            transport = Mock()
            transport.control.side_effect = lambda kind, request, value, data: len(data)
            transport.read.return_value = bytes(reply)
            protocol = PCConnect(transport)
            protocol.serial = 11
            protocol.remote_started = True
            with self.subTest(status=status, subcommand=subcommand):
                if success:
                    protocol.close()
                    self.assertFalse(protocol.remote_started)
                else:
                    with self.assertRaises(ProtocolError):
                        protocol.close()
                    self.assertTrue(protocol.remote_started)

    def test_selected_saved_exchanges(self):
        transport = Replay()
        protocol = PCConnect(transport)
        protocol.initialize()
        model, firmware = protocol.identify()
        self.assertEqual((model, firmware), (EOS_5D.name, EOS_5D.firmware))
        validate_identity(model, firmware)
        self.assertEqual(protocol.owner(), b"Test Camera Owner ")
        protocol.serial = 0x1B  # Recorded queries omitted between owner and GET_PARAMS.
        protocol.prepare_entry()
        self.assertTrue(protocol.remote_started)
        self.assertEqual(transport.index, len(transport.records))

    def test_entry_packet_boundary(self):
        packet = entry_packet()
        self.assertEqual(len(packet), 0x74)
        self.assertEqual(struct.unpack_from("<II", packet), (0x34, 0x201))
        self.assertEqual(packet[0x40], 2)
        self.assertEqual(struct.unpack_from("<III", packet, 0x44), (0x12100006, 0x34, 0x200))
        self.assertEqual(packet[0x50:], b"$EV#OP$SetUSBToDCPMode".ljust(0x24, b"\0"))

    def test_owner_reply_with_nonzero_unused_bytes(self):
        transport = Replay()
        row = transport.records[7]
        reply = bytearray.fromhex(row["data"])
        tail = reply.index(0, 0x54) + 1
        reply[tail:] = bytes(range(1, len(reply) - tail + 1))
        row["data"] = reply.hex()
        protocol = PCConnect(transport)
        protocol.initialize()
        protocol.identify()
        self.assertEqual(protocol.owner(), b"Test Camera Owner ")

    def test_truncated_parameter_data_rejected_before_entry(self):
        transport = Replay()
        protocol = PCConnect(transport)
        protocol.initialize()
        protocol.identify()
        protocol.owner()
        protocol.serial = 0x1B
        row = transport.records[-1]
        reply = bytearray.fromhex(row["data"])
        struct.pack_into("<I", reply, 0x58, 999)
        row["data"] = reply.hex()
        with self.assertRaisesRegex(ProtocolError, "parameter data"):
            protocol.prepare_entry()

    def test_active_camera_handshake(self):
        transport = Mock()
        transport.control.side_effect = [b"A", bytes(0x58), bytes(0x50)]
        PCConnect(transport).initialize()
        transport.read.assert_not_called()
        self.assertEqual(transport.control.call_args.args, (0xC0, 4, 4, 0x50))

    def test_unknown_state_stops_before_writes(self):
        transport = Mock()
        transport.control.return_value = b"E"
        with self.assertRaises(ProtocolError):
            PCConnect(transport).initialize()
        transport.control.assert_called_once_with(0xC0, 0x0C, 0x55, 1)

    def test_unapproved_commands_rejected_before_usb(self):
        transport = Mock()
        protocol = PCConnect(transport)
        for command, payload in ((6, b"owner"), (0x25, b"\x04"), (1, b"extra")):
            with self.assertRaises(ProtocolError):
                protocol._command(command, payload)
        self.assertFalse(transport.mock_calls)

    def test_bad_reply_stops_identification(self):
        for mode in ("short", "status", "transaction", "length"):
            transport = Replay()
            row = transport.records[5]
            reply = bytearray.fromhex(row["data"])
            if mode == "short":
                reply = reply[:20]
            elif mode == "status":
                struct.pack_into("<I", reply, 0x50, 1)
            elif mode == "transaction":
                struct.pack_into("<I", reply, 0x4C, 999)
            else:
                struct.pack_into("<I", reply, 0, 10)
            row["data"] = reply.hex()
            protocol = PCConnect(transport)
            protocol.initialize()
            with self.subTest(mode=mode), self.assertRaises(ProtocolError):
                protocol.identify()
