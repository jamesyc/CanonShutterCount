import json
from pathlib import Path
import unittest

from canonshuttercount.cameras import (
    EOS_5D, RAM_COUNTERS, decode_5d, decode_saved_window, owner_bytes, validate_identity,
)
from canonshuttercount.errors import ProtocolError


class CounterTests(unittest.TestCase):
    def test_ram_layouts_with_synthetic_records(self):
        # Deliberately not camera captures; exercise every table entry.
        for (model, firmware), (_, length, offset, zero_offset) in RAM_COUNTERS.items():
            with self.subTest(model=model, firmware=firmware):
                record = bytearray(length)
                record[offset:offset + 4] = bytes.fromhex("39300000")
                self.assertEqual(decode_saved_window(record, model, firmware), 12345)
                for malformed in (record[:-1], record + b"\0"):
                    with self.assertRaises(ProtocolError):
                        decode_saved_window(malformed, model, firmware)
                record[offset:offset + 4] = (10_000_000).to_bytes(4, "little")
                with self.assertRaises(ProtocolError):
                    decode_saved_window(record, model, firmware)
                record[offset:offset + 4] = bytes.fromhex("7f969800")
                self.assertEqual(decode_saved_window(record, model, firmware), 9_999_999)
                if zero_offset is not None:
                    record[zero_offset] = 1
                    with self.assertRaises(ProtocolError):
                        decode_saved_window(record, model, firmware)

    def test_hc12_layout_with_synthetic_ring(self):
        for model, firmware in (("eos-300d", "1.1.1.0"), ("eos-10d", "1.0.0.0")):
            for upper in (0, 1, 7, 8, 255, 256):
                with self.subTest(model=model, upper=upper):
                    record = bytearray(b"\xff" * 10)
                    record[:2] = upper.to_bytes(2, "big")
                    record[2 + upper % 8] = 42
                    self.assertEqual(decode_saved_window(record, model, firmware), upper * 256 + 42)
            for malformed in (bytes(9), bytes(11), bytes(10), b"\xff" * 10,
                              bytes.fromhex("0000ff01ffffffffffff"),
                              bytes.fromhex("98960102030405068008")):
                with self.subTest(model=model, malformed=malformed), self.assertRaises(ProtocolError):
                    decode_saved_window(malformed, model, firmware)

    def test_offline_layouts_require_known_model_and_firmware(self):
        for model, firmware in (("eos-20d", None), ("eos-30d", "9.9.9"),
                                ("eos-20da", "2.0.3"), ("eos-300d", None),
                                ("eos-10d", "9.9.9"), ("eos-5d", "9.9.9")):
            with self.subTest(model=model, firmware=firmware), self.assertRaises(ProtocolError):
                decode_saved_window(bytes(24), model, firmware)

    def test_recorded_windows_across_rollover(self):
        cases = json.loads((Path(__file__).parent / "fixtures/counter_rollover.json").read_text())
        windows = []
        for case in cases:
            window = bytes.fromhex(case["window_hex"])
            windows.append(window)
            with self.subTest(log=case["source_log"]):
                self.assertEqual(decode_5d(window), case["count"])
                upper = int.from_bytes(window[11:13], "big")
                self.assertEqual(upper, case["upper"])
                self.assertEqual(upper % 8, case["slot"])
        self.assertEqual([(case["upper"], case["slot"]) for case in cases], [(44, 4), (45, 5), (45, 5)])
        # The previous slot stays at 0xee; after rollover the new slot is selected.
        self.assertEqual(windows[0][17], windows[1][17])
        self.assertEqual(windows[1][18], 1)
        self.assertEqual(windows[2][18], 16)

    def test_recorded_photo_increment(self):
        samples = json.loads((Path(__file__).parent / "fixtures/counter.json").read_text())
        before, after = (bytes.fromhex(samples[key]) for key in ("before", "after"))
        self.assertEqual(decode_5d(before), 11300)
        self.assertEqual(decode_5d(after), 11301)
        self.assertEqual([(i, a, b) for i, (a, b) in enumerate(zip(before, after)) if a != b], [(17, 36, 37)])

    def test_synthetic_ring_selection_and_limits(self):
        # These check the formula, not the camera's unobserved rollover behavior.
        for count in (0, 254, 256, 7 * 256 + 4, 8 * 256 + 5, 9_999_999):
            with self.subTest(count=count):
                upper, low = divmod(count, 256)
                window = bytearray(b"\xff" * 24)
                window[11:13] = upper.to_bytes(2, "big")
                window[13 + upper % 8] = low
                self.assertEqual(decode_5d(window), count)
        window[13 + upper % 8] = low + 1
        with self.assertRaises(ProtocolError):
            decode_5d(window)

    def test_ambiguous_and_wrong_length_fail(self):
        for data in (b"", bytes(23), bytes(25), b"\xff" * 24):
            with self.subTest(data=data), self.assertRaises(ProtocolError):
                decode_5d(data)

    def test_owner_comparison_preserves_spaces_not_padding(self):
        self.assertEqual(owner_bytes(b"Test Owner \0"), owner_bytes(b"Test Owner " + bytes(20)))
        self.assertNotEqual(owner_bytes(b"Test Owner \0"), owner_bytes(b"Test Owner\0"))
        self.assertEqual(owner_bytes(bytes(32)), b"")
        for data in (b"", b"no terminator"):
            with self.assertRaises(ProtocolError):
                owner_bytes(data)

    def test_owner_ignores_unspecified_bytes_after_terminator(self):
        # PC Connect hardware run read-7ae4nv1z returned nonzero bytes after NUL.
        # Use synthetic tail bytes so no private contents enter the repository.
        self.assertEqual(owner_bytes(b"Test Owner \0\x12\x34\xff"), b"Test Owner ")
        self.assertEqual(owner_bytes(b"\0\xff\x12"), b"")

    def test_unknown_model_or_firmware_refused(self):
        validate_identity(EOS_5D.name, EOS_5D.firmware)
        for model, firmware in (("Canon EOS 5D Mark II", EOS_5D.firmware), (EOS_5D.name, bytes(4))):
            with self.assertRaises(ProtocolError):
                validate_identity(model, firmware)
