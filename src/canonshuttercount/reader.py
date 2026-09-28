"""One bounded read, with restoration covering the entire USB transition."""

import json
from contextlib import contextmanager
from pathlib import Path
import signal
import sys
import threading

from .cameras import EOS_5D, validate_identity
from .dcp import DCP
from .errors import ProtocolError, ReadFailure, TransferError, TransferTimeout
from .pc_connect import PCConnect
from .ptp import PTP


@contextmanager
def _defer_sigint():
    """Finish USB transactions and cleanup before honoring Ctrl+C on the main thread."""
    requested = reported = False

    def request(signum, frame):
        nonlocal requested
        requested = True

    def cancelled():
        nonlocal reported
        if requested and not reported:
            reported = True
            try:
                print("Interrupt received; completing camera cleanup before stopping.", file=sys.stderr)
            except OSError:
                pass  # A closed terminal must not prevent recovery.
        return requested

    installed = threading.current_thread() is threading.main_thread()
    previous = signal.getsignal(signal.SIGINT) if installed else None
    if installed:
        signal.signal(signal.SIGINT, request)
    try:
        yield cancelled
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous)


def _attempt(errors, action):
    try:
        return action()
    except Exception as error:
        errors.append(error)
        return None


def _restore(bus, location, device, service, ready, monitor_attempted, profile, errors):
    """Try one diagnostic recovery, then independently verify PTP enumeration."""
    if not ready:
        if device is not None:
            _attempt(errors, device.close)
        device = _attempt(errors, lambda: bus.wait_for(profile.dcp_product, location))
        if device is not None:
            try:
                device.claim()
                service = DCP(device, profile)
                service.initialize()
                ready = True
            except Exception as error:
                errors.append(error)
    if ready:
        if monitor_attempted:
            _attempt(errors, lambda: service.call("MonClose"))
        _attempt(errors, lambda: service.call("SetUSBToPTPMode"))
    if device is not None:
        _attempt(errors, device.close)
    return _attempt(errors, lambda: bus.wait_for(profile.ptp_product, location))


def _verify_owner(device, before, logdir, profile, errors):
    protocol = PTP(device)
    try:
        device.claim()
        protocol.initialize()
        validate_identity(*protocol.identify(), profile=profile)
        after = protocol.owner()
        # Check the value even if writing the evidence fails.
        _attempt(errors, lambda: (logdir / "owner-after.bin").write_bytes(after))
        if after != before:
            instructions = Path(__file__).with_name("OWNER_RECOVERY.md")
            raise ProtocolError("Owner-name verification failed; original saved in owner-before.bin. "
                                "Manual recovery instructions: " + str(instructions))
    finally:
        _attempt(errors, protocol.close)
        _attempt(errors, device.close)


def read_count(bus, logdir, profile=EOS_5D, recover=False):
    with _defer_sigint() as cancelled:
        result = _read_count(bus, logdir, profile, recover, cancelled)
        if cancelled():
            raise ReadFailure(KeyboardInterrupt(), [])
        return result


def _read_count(bus, logdir, profile, recover, cancelled):
    def checkpoint():
        if cancelled():
            raise KeyboardInterrupt()

    checkpoint()
    original = bus.one()
    location = original.location
    if location is None:
        raise ProtocolError("USB port location unavailable; cannot safely follow mode changes")
    if recover:
        if original.product != profile.dcp_product:
            raise ProtocolError("Recovery requires the known 5D already in DCP mode")
    elif original.product not in (profile.pc_product, profile.ptp_product):
        raise ProtocolError("Unsupported camera USB identity; identify the model before recovery")

    protocol = None
    device = original if recover else None
    service = None
    before = window = None
    ready = monitor_attempted = transition_attempted = False
    primary = None
    errors = []
    start_mode = "dcp" if recover else ("pc-connect" if original.product == profile.pc_product else "ptp")
    try:
        checkpoint()
        if not recover:
            original.claim()
            protocol = PCConnect(original) if start_mode == "pc-connect" else PTP(original)
            protocol.initialize()
            checkpoint()
            validate_identity(*protocol.identify(), profile=profile)
            checkpoint()
            before = protocol.owner()
            (logdir / "owner-before.bin").write_bytes(before)
            checkpoint()
            protocol.prepare_entry()
            checkpoint()
            transition_attempted = True  # Set before sending; a failed write can still change USB mode.
            try:
                protocol.enter_dcp()
            except (TransferError, TransferTimeout):
                pass  # Only re-enumeration establishes whether the transition happened.
            original.close()
            device = bus.wait_for(profile.dcp_product, location)
            checkpoint()
        device.claim()
        service = DCP(device, profile)
        service.initialize()
        ready = True
        checkpoint()
        if not recover:
            monitor_attempted = True  # MonOpen may succeed even if its reply is lost.
            service.call("MonOpen")
            checkpoint()
            chunks = []
            for address, length in profile.chunks:
                chunks.append(service.read(address, length))
                checkpoint()
            window = b"".join(chunks)
            (logdir / "window.bin").write_bytes(window)
    except BaseException as error:
        primary = error
    finally:
        cancelled()  # Report an interrupt that arrived between checkpoints.
        if transition_attempted or recover:
            restored = _restore(bus, location, device, service, ready, monitor_attempted, profile, errors)
            cancelled()
            if restored is not None and before is not None:
                _attempt(errors, lambda: _verify_owner(restored, before, logdir, profile, errors))
            elif restored is None and protocol is not None:
                # If a failed entry left PC Connect unchanged, end its remote session.
                remaining = _attempt(errors, lambda: bus.one(required=False))
                if remaining is not None and remaining.location == location and remaining.product == original.product:
                    try:
                        original.claim()
                        _attempt(errors, protocol.close)
                    except Exception as error:
                        errors.append(error)
                    finally:
                        _attempt(errors, original.close)
        elif protocol is not None:
            _attempt(errors, protocol.close)
        _attempt(errors, original.close)

    interrupted = cancelled()
    if interrupted and primary is None:
        primary = KeyboardInterrupt()
    if getattr(bus, "log_error", None) is not None:
        errors.append(ProtocolError("USB trace could not be saved: " + str(bus.log_error)))
    if primary is not None or errors:
        raise ReadFailure(primary, errors, interrupted=interrupted) from primary
    result = dict(model=profile.name, start_mode=start_mode, end_mode="ptp",
                  restored_start_mode=start_mode == "ptp", returned_to_ptp=True)
    if not recover:
        result.update(shutter_count=profile.decoder(window), owner_unchanged=True, window_hex=window.hex())
    (logdir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
