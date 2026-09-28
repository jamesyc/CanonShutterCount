from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


class FirmwareToolTests(unittest.TestCase):
    def test_reference_scan_on_synthetic_arm_image(self):
        tool = Path(__file__).resolve().parents[1] / "tools/inspect_firmware.py"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "synthetic.bin"
            # At 0x1000, ARM BL +0 targets 0x1008 (PC is instruction address +8).
            image.write_bytes(struct.pack("<IIII", 0xEB000000, 0x1008, 0xE1A00000, 0))
            result = subprocess.run([sys.executable, str(tool), str(image), "--base", "0x1000", "--refs", "0x1008"],
                                    check=True, capture_output=True, text=True)
            self.assertIn("branch  0x1000 -> 0x1008", result.stdout)
            self.assertIn("literal 0x1004 -> 0x1008", result.stdout)
