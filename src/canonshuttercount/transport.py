"""The only module that imports PyUSB. Constructing USBBus enables hardware access."""

import json
import os
from pathlib import Path
import sys
import time

from .errors import ProtocolError, TransferError, TransferTimeout


class USBBus:
    def __init__(self, log=None):
        import usb.core
        import usb.util
        import usb.backend.libusb1

        self.core, self.util = usb.core, usb.util
        self.log, self.log_error = log, None
        library = os.environ.get("CANONSHUTTERCOUNT_LIBUSB")
        if library:
            library = str(Path(library).expanduser())
            if not Path(library).is_file():
                raise TransferError("CANONSHUTTERCOUNT_LIBUSB does not point to a library file")
            self.backend = usb.backend.libusb1.get_backend(find_library=lambda name: library)
        else:
            self.backend = usb.backend.libusb1.get_backend()
        if self.backend is None and not library and sys.platform == "darwin":
            for path in ("/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"):
                if Path(path).exists():
                    self.backend = usb.backend.libusb1.get_backend(find_library=lambda name: path)
                    if self.backend is not None:
                        break
        if self.backend is None:
            raise TransferError("libusb 1.0 unavailable; install the native USB backend (see README)")

    def call(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except self.core.USBTimeoutError as error:
            self.trace("error", error=str(error))
            raise TransferTimeout(str(error)) from error
        except self.core.USBError as error:
            self.trace("error", error=str(error))
            raise TransferError(str(error)) from error

    def trace(self, kind, **fields):
        if self.log is not None and self.log_error is None:
            try:
                self.log.write(json.dumps(dict(kind=kind, **fields)) + "\n")
                self.log.flush()
            except OSError as error:
                # A full disk must not prevent camera cleanup.
                self.log_error = error

    def one(self, required=True):
        devices = self.call(lambda: list(self.core.find(find_all=True, idVendor=0x04A9, backend=self.backend)))
        if len(devices) > 1:
            raise ProtocolError("Connect only one Canon camera")
        if not devices:
            if required:
                raise ProtocolError("No Canon camera connected")
            return None
        return USBTransport(self, devices[0])

    def wait_for(self, product, location, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            device = self.one(required=False)
            if device is not None:
                if device.location != location:
                    raise ProtocolError("Canon USB location changed; refusing a different camera")
                if device.product == product:
                    return device
            time.sleep(0.1)
        raise TransferTimeout("Camera did not appear as 04a9:%04x at the original USB port" % product)


class USBTransport:
    def __init__(self, bus, device):
        self.bus, self.device = bus, device
        self.product = device.idProduct
        ports = tuple(device.port_numbers or ())
        self.location = (device.bus, ports) if device.bus is not None and ports else None
        self.claimed = self.detached = False

    def claim(self):
        deadline = time.monotonic() + 5
        while True:
            try:
                # The caller owns close(), including partial-claim failures.
                if sys.platform.startswith("linux") and self.bus.call(self.device.is_kernel_driver_active, 0):
                    self.bus.call(self.device.detach_kernel_driver, 0)
                    self.detached = True
                self.bus.call(self.bus.util.claim_interface, self.device, 0)
                self.claimed = True
                return
            except TransferError as error:
                if (getattr(error.__cause__, "backend_error_code", None) != -4
                        or self.location is None or time.monotonic() >= deadline):
                    raise
                # Enumeration can precede interface readiness after a USB mode switch.
                self.close()
                time.sleep(0.1)
                fresh = self.bus.one(required=False)
                if fresh is not None:
                    if fresh.location != self.location or fresh.product != self.product:
                        raise ProtocolError("Camera identity changed while claiming its interface") from error
                    self.device = fresh.device

    def close(self):
        errors = []
        actions = []
        if self.claimed:
            actions.append(lambda: self.bus.util.release_interface(self.device, 0))
        if self.detached:
            actions.append(lambda: self.device.attach_kernel_driver(0))
        actions.append(lambda: self.bus.util.dispose_resources(self.device))
        for action in actions:
            try:
                action()
            except self.bus.core.USBError as error:
                if getattr(error, "backend_error_code", None) != -4:  # Expected after mode-switch disconnect.
                    errors.append(error)
        self.claimed = self.detached = False
        if errors:
            raise TransferError("USB release failed: " + "; ".join(map(str, errors)))

    def control(self, kind, request, value, data, timeout=3000):
        result = self.bus.call(self.device.ctrl_transfer, kind, request, value, 0, data, timeout=timeout)
        incoming = bool(kind & 0x80)
        wire = bytes(result) if incoming else bytes(data)
        self.bus.trace("control-in" if incoming else "control-out", request=request, value=value, data=wire.hex())
        return wire if incoming else result

    def write(self, endpoint, data, timeout=3000):
        result = self.bus.call(self.device.write, endpoint, data, timeout=timeout)
        self.bus.trace("out", endpoint=endpoint, data=bytes(data).hex())
        return result

    def read(self, endpoint, length, timeout=3000):
        result = bytes(self.bus.call(self.device.read, endpoint, length, timeout=timeout))
        self.bus.trace("in", endpoint=endpoint, data=result.hex())
        return result
