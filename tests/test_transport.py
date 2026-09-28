from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from canonshuttercount.errors import ProtocolError, TransferError, TransferTimeout
from canonshuttercount.transport import USBBus, USBTransport


class USBError(Exception):
    backend_error_code = None


class USBTimeoutError(USBError):
    pass


class TransportTests(unittest.TestCase):
    def test_explicit_backend_path_loads_without_enumerating_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "libusb-test"
            library.touch()
            with patch.dict("os.environ", {"CANONSHUTTERCOUNT_LIBUSB": str(library)}), \
                    patch("usb.backend.libusb1.get_backend") as backend, patch("usb.core.find") as find:
                bus = USBBus()
                self.assertIs(bus.backend, backend.return_value)
                resolver = backend.call_args.kwargs["find_library"]
                self.assertEqual(resolver("usb-1.0"), str(library))
                find.assert_not_called()

    def test_invalid_explicit_backend_never_falls_back_to_another_library(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"CANONSHUTTERCOUNT_LIBUSB": str(Path(directory) / "missing")}), \
                    patch("usb.backend.libusb1.get_backend") as backend:
                with self.assertRaises(TransferError):
                    USBBus()
                backend.assert_not_called()

    def test_stale_device_handle_is_refreshed_before_claim_retry(self):
        transport = USBTransport(self.bus, self.device)
        fresh = Mock(idProduct=self.device.idProduct, bus=1, port_numbers=(2, 3))
        error = USBError("not ready")
        error.backend_error_code = -4
        self.bus.util.claim_interface.side_effect = [error, None]
        self.bus.core.find.return_value = [fresh]
        with patch("canonshuttercount.transport.sys.platform", "darwin"), patch("canonshuttercount.transport.time.sleep"):
            transport.claim()
        self.assertTrue(transport.claimed)
        self.assertIs(transport.device, fresh)
        self.assertEqual(self.bus.util.claim_interface.call_count, 2)

    def test_claim_retry_is_bounded_and_rejects_another_camera(self):
        for changed in (False, True):
            transport = USBTransport(self.bus, self.device)
            error = USBError("not ready")
            error.backend_error_code = -4
            self.bus.util.claim_interface.side_effect = error
            self.bus.core.find.return_value = [Mock(idProduct=0x3101, bus=1, port_numbers=(9,))] if changed else []
            with patch("canonshuttercount.transport.sys.platform", "darwin"), \
                    patch("canonshuttercount.transport.time.monotonic", side_effect=[0, 0, 6]), \
                    patch("canonshuttercount.transport.time.sleep"):
                with self.subTest(changed=changed), self.assertRaises(ProtocolError if changed else TransferError):
                    transport.claim()
            self.assertFalse(transport.claimed)

    def setUp(self):
        # Bypass backend loading. No test enumerates or opens real USB devices.
        self.bus = USBBus.__new__(USBBus)
        self.bus.core = SimpleNamespace(USBError=USBError, USBTimeoutError=USBTimeoutError, find=Mock())
        self.bus.util = Mock()
        self.bus.backend = None
        self.bus.log = None
        self.bus.log_error = None
        self.device = Mock(idProduct=0x3101, bus=1, port_numbers=(2, 3))

    def test_multiple_devices_refused(self):
        self.bus.core.find.return_value = [self.device, self.device]
        with self.assertRaisesRegex(ProtocolError, "only one"):
            self.bus.one()
        self.bus.util.claim_interface.assert_not_called()

    def test_changed_location_is_not_a_match(self):
        self.device.idProduct = 0x3086
        self.bus.core.find.return_value = [self.device]
        with self.assertRaisesRegex(ProtocolError, "location changed"):
            self.bus.wait_for(0x3086, (1, (2, 4)))
        self.bus.util.claim_interface.assert_not_called()

    def test_wait_times_out_without_commands(self):
        self.bus.core.find.return_value = []
        with patch("canonshuttercount.transport.time.monotonic", side_effect=[0, 0, 16]), patch("canonshuttercount.transport.time.sleep"):
            with self.assertRaises(TransferTimeout):
                self.bus.wait_for(0x3086, (1, (2, 3)))
        self.bus.util.claim_interface.assert_not_called()

    def test_linux_partial_claim_reattaches_driver(self):
        transport = USBTransport(self.bus, self.device)
        self.device.is_kernel_driver_active.return_value = True
        self.bus.util.claim_interface.side_effect = USBError("busy")
        with patch("canonshuttercount.transport.sys.platform", "linux"):
            with self.assertRaises(TransferError):
                transport.claim()
            transport.close()
        self.device.detach_kernel_driver.assert_called_once_with(0)
        self.device.attach_kernel_driver.assert_called_once_with(0)
        self.bus.util.dispose_resources.assert_called_once_with(self.device)

    def test_timeout_translation_and_logging_failure(self):
        self.bus.log = Mock()
        self.bus.log.write.side_effect = OSError("disk full")
        action = Mock(side_effect=USBTimeoutError("timeout"))
        with self.assertRaises(TransferTimeout):
            self.bus.call(action)
        self.assertIsInstance(self.bus.log_error, OSError)
        self.bus.trace("cleanup")  # Does not raise or attempt another failed write.
        self.bus.log.write.assert_called_once()

    def test_disconnect_during_release_is_expected(self):
        transport = USBTransport(self.bus, self.device)
        transport.claimed = True
        error = USBError("disconnected")
        error.backend_error_code = -4
        self.bus.util.release_interface.side_effect = error
        transport.close()
        self.bus.util.dispose_resources.assert_called_once()
        self.assertFalse(transport.claimed)
