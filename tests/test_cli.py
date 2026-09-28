import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from canonshuttercount.cli import main
from canonshuttercount.errors import ReadFailure, TransferError


class CLITests(unittest.TestCase):
    def test_new_models_are_offline_only_including_recovery(self):
        from canonshuttercount.cameras import OFFLINE_MODELS

        for model in OFFLINE_MODELS[1:]:
            for action in ([], ["--recover-dcp"]):
                with self.subTest(model=model, action=action), \
                        patch("canonshuttercount.transport.USBBus") as bus, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(["--model", model] + action)
                self.assertEqual(error.exception.code, 2)
                bus.assert_not_called()

    def test_new_model_decode_requires_firmware_and_never_opens_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.bin"
            path.write_bytes(bytes(20) + bytes.fromhex("39300000") + bytes(32))
            output, errors = io.StringIO(), io.StringIO()
            with patch("canonshuttercount.transport.USBBus") as bus, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                args = ["--decode", str(path), "--model", "eos-400d", "--json"]
                self.assertEqual(main(args), 1)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(main(args + ["--firmware", "1.1.1"]), 0)
            bus.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()), {"shutter_count": 12345})
            self.assertIn("no hardware validation", errors.getvalue())

    def test_interrupt_returns_130_without_printing_a_count(self):
        for primary in (KeyboardInterrupt(), TransferError("read failed")):
            with tempfile.TemporaryDirectory() as directory:
                output, errors = io.StringIO(), io.StringIO()
                failure = ReadFailure(primary, [], interrupted=True)
                with patch("canonshuttercount.transport.USBBus"), \
                        patch("canonshuttercount.reader.read_count", side_effect=failure), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    self.assertEqual(main(["--log-dir", directory]), 130)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("Logs:", errors.getvalue())

    def test_final_mode_reporting_does_not_claim_pc_connect_restored(self):
        for mode in ("pc-connect", "ptp"):
            result = dict(shutter_count=11304, start_mode=mode, end_mode="ptp",
                          restored_start_mode=mode == "ptp", returned_to_ptp=True, owner_unchanged=True)
            with tempfile.TemporaryDirectory() as directory:
                output, errors = io.StringIO(), io.StringIO()
                with patch("canonshuttercount.transport.USBBus"), \
                        patch("canonshuttercount.reader.read_count", return_value=result), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    self.assertEqual(main(["--json", "--log-dir", directory]), 0)
                self.assertEqual(json.loads(output.getvalue()), result)
                label = "PC Connect" if mode == "pc-connect" else "Print/PTP"
                expected = ["Started in %s mode; USB mode is now Print/PTP." % label]
                if mode == "pc-connect":
                    expected.append("Power-cycle to return to the saved Communication setting.")
                self.assertEqual(errors.getvalue().splitlines()[:-1], expected)
                self.assertTrue(errors.getvalue().splitlines()[-1].startswith("Logs: "))

    def test_offline_decode_json_does_not_construct_bus(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.bin"
            fixture = json.loads((Path(__file__).parent / "fixtures/counter.json").read_text())
            path.write_bytes(bytes.fromhex(fixture["after"]))
            output = io.StringIO()
            with patch("canonshuttercount.transport.USBBus") as bus, contextlib.redirect_stdout(output):
                self.assertEqual(main(["--decode", str(path), "--json"]), 0)
            bus.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()), {"shutter_count": 11301})

    def test_recovery_requires_explicit_model(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--recover-dcp"])
        self.assertEqual(error.exception.code, 2)

    def test_importing_protocols_never_imports_pyusb(self):
        result = subprocess.run([sys.executable, "-c", "import canonshuttercount.reader, sys; assert 'usb.core' not in sys.modules"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
