# Changelog

## 0.1.0

Initial release of the CanonShutterCount command-line reader.

### Live camera support

- Original Canon EOS 5D with firmware 1.1.1, validated on Apple Silicon macOS.
- PC Connect and Print/PTP are both first-class starting modes.
- Reads the camera's bounded diagnostic counter window without taking a photo.
- Both modes finish in USB Print/PTP. The saved Communication setting is unchanged;
  power-cycle to return to that preference when it is PC Connect.
- Verifies the owner name before reporting a successful count and saves local logs.
- Supports explicit recovery for a known 5D left in diagnostic mode.
- Handles stale sessions and release control, bounded USB reconnection retries, and
  repeated Ctrl+C while allowing cleanup to finish.

### Offline decoding

- Saved-record decoders for 20D, 30D, 400D / Rebel XTi / Kiss Digital X,
  300D / Digital Rebel / Kiss Digital, and 10D, with explicit model/firmware selection.
- These additional decoders have synthetic tests only. They do not enable live USB
  reads or recovery for those bodies. The 20Da has no separate validated profile.

### Installation and compatibility

- Python 3.9 or newer; PyUSB 1.3.1 is the only third-party Python runtime dependency.
- Native libusb 1.0 is required for camera access; gphoto2 is not required for reads.
- Source distribution and pure-Python wheel, with a `canonshuttercount` console command.
- JSON output, an offline decoder, and a packaged manual owner-recovery guide.
- `CANONSHUTTERCOUNT_LIBUSB` selects a native library at a nonstandard location.
- GNU GPL version 3 (`GPL-3.0-only`).

### Validation and limits

- Repeated real-camera reads, a user-controlled photo increment, and snapshots across
  a counter rollover have passed on the tested 5D.
- Live interruption tests verified PTP cleanup and unchanged owner values. A forced
  stop at a controlled diagnostic-entry point recovered after a user power cycle.
- The pushed baseline passed all nine CI jobs: Linux Python 3.9–3.14, macOS Python
  3.14, and Windows Python 3.9/3.14. Native backend loading was checked on Linux/macOS.
- CI does not establish camera support on Linux or Windows; hardware testing there
  remains pending. Other 5D firmware versions are not validated.
- Ambiguous selected counter bytes (`0xff`) are rejected. Exact boundary behavior
  and counter-persistence timing are not fully established.
- A forced kill or unplug may leave the camera in diagnostic mode until explicit
  recovery or a power cycle. No guarantee is made for every interruption point.
- A historical shutter replacement or counter reset cannot be detected.
- A Homebrew tap is planned but is not included in this release preparation.
