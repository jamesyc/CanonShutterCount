from pathlib import Path
import contextlib
import io
import signal
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from canonshuttercount.cameras import EOS_5D
from canonshuttercount.errors import ProtocolError, ReadFailure, TransferError
from canonshuttercount.reader import read_count

WINDOW = bytes.fromhex("ffffff557305fd190a3c56002cdffef2ff25fcfff2ffffff")


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.logdir = Path(self.directory.name)
        location = (1, (2, 3))
        self.original = Mock(product=EOS_5D.pc_product, location=location)
        self.dcp_device = Mock(product=EOS_5D.dcp_product, location=location)
        self.restored = Mock(product=EOS_5D.ptp_product, location=location)
        self.normal = Mock()
        self.normal.identify.return_value = (EOS_5D.name, EOS_5D.firmware)
        self.normal.owner.return_value = b"Test Owner "
        self.after = Mock()
        self.after.identify.return_value = (EOS_5D.name, EOS_5D.firmware)
        self.after.owner.return_value = b"Test Owner "
        self.service = Mock()
        self.service.read.side_effect = [WINDOW[:12], WINDOW[12:]]
        self.bus = Mock(log_error=None)
        self.bus.one.return_value = self.original
        self.bus.wait_for.side_effect = lambda product, location: self.dcp_device if product == EOS_5D.dcp_product else self.restored
        for name, replacement in (
            ("PCConnect", Mock(return_value=self.normal)),
            ("PTP", Mock(side_effect=lambda device: self.normal if device is self.original else self.after)),
            ("DCP", Mock(return_value=self.service)),
        ):
            patcher = patch("canonshuttercount.reader." + name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_restored(self):
        self.assertIn(call("SetUSBToPTPMode"), self.service.call.call_args_list)
        self.bus.wait_for.assert_any_call(EOS_5D.ptp_product, self.original.location)
        self.after.owner.assert_called_once()
        self.restored.close.assert_called_once()

    def test_sigint_finishes_current_read_then_stops_before_next_chunk(self):
        previous = signal.getsignal(signal.SIGINT)
        def read(address, length):
            signal.raise_signal(signal.SIGINT)
            return WINDOW[:12]
        self.service.read.side_effect = read
        with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(ReadFailure) as failure:
            read_count(self.bus, self.logdir)
        self.assertTrue(failure.exception.interrupted)
        self.service.read.assert_called_once()
        self.assert_restored()
        self.assertIn("completing camera cleanup", errors.getvalue())
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_repeated_sigint_during_cleanup_and_owner_check_is_deferred(self):
        previous = signal.getsignal(signal.SIGINT)
        def invoke(name):
            if name == "MonClose":
                signal.raise_signal(signal.SIGINT)
                signal.raise_signal(signal.SIGINT)
        def owner():
            signal.raise_signal(signal.SIGINT)
            return b"Test Owner "
        self.service.call.side_effect = invoke
        self.after.owner.side_effect = owner
        with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(ReadFailure) as failure:
            read_count(self.bus, self.logdir)
        self.assertTrue(failure.exception.interrupted)
        self.assert_restored()
        self.assertEqual(errors.getvalue().count("Interrupt received"), 1)
        self.assertFalse((self.logdir / "result.json").exists())
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_sigint_after_normal_initialization_closes_session_without_entering_dcp(self):
        self.normal.initialize.side_effect = lambda: signal.raise_signal(signal.SIGINT)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ReadFailure):
            read_count(self.bus, self.logdir)
        self.normal.close.assert_called_once()
        self.normal.enter_dcp.assert_not_called()
        self.service.initialize.assert_not_called()

    def test_sigint_during_cleanup_preserves_the_original_read_error(self):
        self.service.read.side_effect = TransferError("read failed")
        self.service.call.side_effect = lambda name: signal.raise_signal(signal.SIGINT) if name == "MonClose" else None
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ReadFailure) as failure:
            read_count(self.bus, self.logdir)
        self.assertTrue(failure.exception.interrupted)
        self.assertIsInstance(failure.exception.primary, TransferError)
        self.assertIn("read failed", str(failure.exception))
        self.assert_restored()

    def test_both_modes_have_equal_success_conditions(self):
        for product, mode in ((EOS_5D.pc_product, "pc-connect"), (EOS_5D.ptp_product, "ptp")):
            with self.subTest(mode=mode):
                self.original.product = product
                self.service.read.side_effect = [WINDOW[:12], WINDOW[12:]]
                result = read_count(self.bus, self.logdir)
                self.assertEqual(result["shutter_count"], 11301)
                self.assertEqual(result["start_mode"], mode)
                self.assertEqual(result["end_mode"], "ptp")
                self.assertEqual(result["restored_start_mode"], mode == "ptp")
                self.assertTrue(result["owner_unchanged"] and result["returned_to_ptp"])
        self.assertEqual(self.service.call.call_args_list, [call("MonOpen"), call("MonClose"), call("SetUSBToPTPMode")] * 2)

    def test_usb_error_during_entry_requires_actual_reenumeration(self):
        self.normal.enter_dcp.side_effect = TransferError("device disconnected")
        result = read_count(self.bus, self.logdir)
        self.assertEqual(result["shutter_count"], 11301)
        self.bus.wait_for.assert_any_call(EOS_5D.dcp_product, self.original.location)
        self.assert_restored()

    def test_failed_dcp_claim_still_restores(self):
        self.dcp_device.claim.side_effect = [TransferError("busy"), None]
        with self.assertRaisesRegex(ReadFailure, "busy"):
            read_count(self.bus, self.logdir)
        self.service.read.assert_not_called()
        self.assert_restored()

    def test_read_failure_and_ctrl_c_close_monitor(self):
        for error in (TransferError("read failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.service.read.side_effect = error
                with self.assertRaises(ReadFailure) as failure:
                    read_count(self.bus, self.logdir)
                self.assertIs(failure.exception.primary, error)
                self.assertIn(call("MonClose"), self.service.call.call_args_list)
                self.assertIn(call("SetUSBToPTPMode"), self.service.call.call_args_list)
        self.assertFalse((self.logdir / "result.json").exists())

    def test_monitor_open_reply_lost_still_attempts_close(self):
        def invoke(name):
            if name == "MonOpen":
                raise TransferError("lost MonOpen reply")
        self.service.call.side_effect = invoke
        with self.assertRaises(ReadFailure):
            read_count(self.bus, self.logdir)
        self.assertIn(call("MonClose"), self.service.call.call_args_list)
        self.assert_restored()

    def test_cleanup_error_does_not_hide_primary_or_skip_restoration(self):
        self.service.read.side_effect = TransferError("read failed")
        def invoke(name):
            if name == "MonClose":
                raise ProtocolError("close failed")
        self.service.call.side_effect = invoke
        with self.assertRaises(ReadFailure) as failure:
            read_count(self.bus, self.logdir)
        self.assertIn("read failed", str(failure.exception))
        self.assertIn("close failed", str(failure.exception))
        self.assert_restored()

    def test_disk_failure_after_read_still_restores(self):
        (self.logdir / "window.bin").mkdir()
        with self.assertRaises(ReadFailure):
            read_count(self.bus, self.logdir)
        self.assert_restored()

    def test_owner_mismatch_prevents_result(self):
        self.after.owner.return_value = b"Test Owner"  # Lost trailing space matters.
        with self.assertRaisesRegex(ReadFailure, "Owner-name verification failed"):
            read_count(self.bus, self.logdir)
        self.assertFalse((self.logdir / "result.json").exists())
        self.assert_restored()

    def test_unknown_firmware_never_enters_diagnostics(self):
        self.normal.identify.return_value = (EOS_5D.name, bytes(4))
        with self.assertRaises(ReadFailure):
            read_count(self.bus, self.logdir)
        self.normal.enter_dcp.assert_not_called()
        self.normal.close.assert_called_once()
        self.service.initialize.assert_not_called()

    def test_missing_location_refused_before_claim(self):
        self.original.location = None
        with self.assertRaisesRegex(ProtocolError, "location unavailable"):
            read_count(self.bus, self.logdir)
        self.original.claim.assert_not_called()

    def test_recovery_never_reads_memory(self):
        self.original.product = EOS_5D.dcp_product
        result = read_count(self.bus, self.logdir, recover=True)
        self.assertTrue(result["returned_to_ptp"])
        self.service.read.assert_not_called()
        self.service.call.assert_called_once_with("SetUSBToPTPMode")

    def test_log_failure_does_not_interrupt_cleanup(self):
        self.bus.log_error = OSError("disk full")
        with self.assertRaisesRegex(ReadFailure, "disk full"):
            read_count(self.bus, self.logdir)
        self.assert_restored()
