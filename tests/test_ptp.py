import struct
import unittest
from unittest.mock import Mock

from canonshuttercount.errors import ProtocolError, TransferTimeout
from canonshuttercount.ptp import PTP, PTPResponseError


def container(kind, code, transaction, data=b""):
    return struct.pack("<IHHI", 12 + len(data), kind, code, transaction) + data


class PTPTests(unittest.TestCase):
    def test_stale_session_is_closed_and_reopened_once(self):
        device = Mock()
        device.write.side_effect = lambda endpoint, packet: len(packet)
        device.read.side_effect = [container(3, 0x201E, 0), container(3, 0x2001, 1), container(3, 0x2001, 0)]
        protocol = PTP(device)
        protocol.initialize()
        self.assertTrue(protocol.opened)
        self.assertEqual([c.args[1].hex() for c in device.write.call_args_list], [
            "10000000010002100000000001000000", "0c0000000100031001000000",
            "10000000010002100000000001000000",
        ])

    def test_stale_session_recovery_failure_does_not_loop(self):
        for replies, expected_writes in (([container(3, 0x201E, 0), container(3, 0x2002, 1)], 2),
                                         ([container(3, 0x201E, 0), container(3, 0x2001, 1), container(3, 0x201E, 0)], 3),
                                         ([container(3, 0x2002, 0)], 1)):
            device = Mock()
            device.write.side_effect = lambda endpoint, packet: len(packet)
            device.read.side_effect = replies
            protocol = PTP(device)
            with self.subTest(replies=replies), self.assertRaises(PTPResponseError):
                protocol.initialize()
            self.assertFalse(protocol.opened)
            self.assertEqual(device.write.call_count, expected_writes)

    def test_identification_properties(self):
        name = "Canon EOS 5D"
        model = bytes([len(name) + 1]) + (name + "\0").encode("utf-16-le")
        firmware = bytes.fromhex("02010101")
        device = Mock()
        device.write.return_value = 16
        device.read.side_effect = [
            container(2, 0x1015, 0, model) + container(3, 0x2001, 0),
            container(2, 0x1015, 1, firmware) + container(3, 0x2001, 1),
        ]
        self.assertEqual(PTP(device).identify(), (name, firmware))

    def test_open_owner_and_close_packets_with_split_and_combined_replies(self):
        owner = b"Test Owner \0"
        data = struct.pack("<I", len(owner)) + owner
        value = container(2, 0x1015, 1, data) + container(3, 0x2001, 1)
        device = Mock()
        device.write.side_effect = lambda endpoint, packet: len(packet)
        device.read.side_effect = [container(3, 0x2001, 0), value[:5], value[5:15], value[15:], container(3, 0x2001, 2)]
        ptp = PTP(device)
        ptp.initialize()
        self.assertEqual(ptp.owner(), b"Test Owner ")
        ptp.close()
        self.assertEqual([call.args[1].hex() for call in device.write.call_args_list], [
            "10000000010002100000000001000000",
            "10000000010015100100000033d00000",
            "0c0000000100031002000000",
        ])

    def test_mode_switch_matches_recorded_command(self):
        device = Mock()
        device.write.return_value = 16
        ptp = PTP(device)
        ptp.transaction = 4
        ptp.enter_dcp()
        self.assertEqual(device.write.call_args.args[1].hex(), "1000000001001f900400000003000000")
        device.read.assert_not_called()

    def test_invalid_packets_and_status(self):
        for reply in (container(3, 0x200A, 0), container(3, 0x2001, 100),
                      struct.pack("<IHHI", 0xFFFFFFFF, 3, 0x2001, 0), b""):
            device = Mock()
            device.write.return_value = 16
            device.read.return_value = reply
            with self.subTest(reply=reply), self.assertRaises(ProtocolError):
                PTP(device).initialize()

    def test_timeout_propagates_without_resending_command(self):
        device = Mock()
        device.write.return_value = 16
        device.read.side_effect = TransferTimeout()
        with self.assertRaises(TransferTimeout):
            PTP(device).initialize()
        device.write.assert_called_once()

    def test_bad_owner_length(self):
        device = Mock()
        device.write.return_value = 16
        device.read.return_value = container(2, 0x1015, 0, struct.pack("<I", 100) + b"x\0") + container(3, 0x2001, 0)
        with self.assertRaises(ProtocolError):
            PTP(device).owner()

    def test_arbitrary_operation_never_sent(self):
        device = Mock()
        with self.assertRaises(ProtocolError):
            PTP(device)._command(0x1016, (0xD033,))
        device.write.assert_not_called()
