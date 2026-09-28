# CanonShutterCount

Python 3.9+ shutter-count reader for the original Canon EOS 5D, firmware 1.1.1.
**PC Connect and Print/PTP are first-class modes.** Both enter the diagnostic
monitor, read the same bounded memory window, and finish with USB PTP restored.
The saved Communication-menu preference is unchanged. The reader does not take a photo.

## Current status

The new implementation has offline tests for both modes, recorded DCP exchanges,
counter decoding, and recovery behavior. **PC Connect and Print/PTP have passed
repeated manual reads on the original 5D on macOS:** both initially returned 11,303,
then repeatedly returned 11,304 after one user-confirmed photo. Counter bytes match
across modes, PTP was restored, and the owner stayed unchanged; see
[VALIDATION.md](https://github.com/jamesyc/CanonShutterCount/blob/main/VALIDATION.md). Both modes intentionally finish in PTP; power-cycle
to return to the saved Communication setting when it is PC Connect.
The result explicitly includes `start_mode`, `end_mode`, and `restored_start_mode`;
the CLI reports the mode mismatch and power-cycle fallback.
The reference prototype's hardware results are documented separately in the fixture
provenance. Linux and Windows hardware behavior is also unverified.

**Offline saved-record decoding** is available for 400D / Rebel
XTi / Kiss Digital X, 30D, 20D, 300D / Digital Rebel / Kiss Digital, and 10D.
These cameras are not yet supported for live USB reads or recovery. The 20Da
needs separate evidence and has no decoder profile.

## Development with mise and uv

```sh
cd ~/git/CanonShutterCount
mise trust
mise install
mise run test
```

mise selects Python 3.9.25 and uv. uv creates `.venv` from the checked-in lockfile;
the sync task explicitly uses mise's Python and disables uv Python downloads.
Unit tests use `unittest` and never open a camera or require native libusb.

## Manual camera testing

The only Python runtime dependency is PyUSB 1.3.1. Live reads also require native
libusb 1.0. There is no gphoto2 dependency or C bridge.

On macOS, install the native runtime if it is missing:

```sh
brew install libusb
```

Connect only the original 5D, turn it on, and select **PC Connect** or **Print/PTP**
in the camera's Communication menu. Close applications using the camera. Run:

```sh
mise run read
```

A successful run prints the shutter count only after returning to PTP and checking
that the owner name is unchanged. Run twice without taking a photograph to check
for a stable count. A successful PC Connect run finishes in PTP; power-cycle to
return to the saved PC Connect preference when testing another PC Connect start.
Check the program's reported starting mode rather than only the menu setting.
Then manually select the other Communication mode (power-cycle
and reconnect if needed) and repeat. Share the terminal output first; raw logs can
contain private camera information. A controlled one-photo check is a separate,
manual step, never an automatic test.

For JSON output or an explicit log location:

```sh
uv run --no-sync canonshuttercount --json --log-dir ./logs
```

Each live run creates a new folder under `~/.canonshuttercount/logs` by default,
containing the USB trace and available before/after owner bytes, counter window,
and successful result. Logs are written outside the installed package.

If a **known original 5D** is stranded in DCP, recover without reading memory:

```sh
uv run --no-sync canonshuttercount --recover-dcp --model eos-5d
```

The DCP USB identity is shared with other Canon cameras and cannot identify a model
on its own. If recovery fails, power-cycle and reconnect the camera. Forced process
termination or unplugging can prevent software cleanup.

## Interrupted runs and recovery

Ctrl+C is honored at a protocol boundary so a USB transaction can finish. The
reader then closes the monitor, restores PTP, verifies the owner, and exits with
status 130. Additional Ctrl+C signals are deferred during this cleanup. USB timeouts
remain bounded; an unplugged camera or forced process kill can prevent recovery.

On the next run, a PTP `SessionAlreadyOpen` response triggers one close/reopen
attempt. PC Connect ends any stale release-control session before opening a fresh
one, accepting only the verified already-inactive response for that cleanup.
If the camera is already in DCP, use the explicit recovery command above.

If owner verification fails, the error points to the installed
[manual owner-recovery instructions](src/canonshuttercount/OWNER_RECOVERY.md).
The reader preserves the original bytes and never attempts an automatic owner write.

## Other platforms and installation

- Linux: install your distribution's libusb 1.0 runtime and configure access to
  Canon USB devices in both normal modes (`3101`, `3102`) and diagnostic mode
  (`3086`). Use an appropriate scoped udev rule; routine root execution is not
  the intended setup. The reader releases and reattaches a bound driver when needed.
- Windows: provide the libusb 1.0 DLL and a compatible USB driver for all required
  device identities. This setup and mode switching need hardware validation;
  see [libusb's Windows documentation](https://github.com/libusb/libusb/wiki/Windows).

The package is installable with ordinary Python tooling; mise and uv are development
tools rather than application runtime requirements:

```sh
python -m pip install .
canonshuttercount --help
```

If libusb is outside the system loader's paths, set `CANONSHUTTERCOUNT_LIBUSB` to
its absolute library filename (`.dylib`, `.so`, or `.dll`). Packaging can use this
to select the intended native dependency regardless of the installation prefix.
An invalid explicit path fails instead of silently selecting another library.
Check loading without discovering or opening a camera:

```sh
uv run --no-sync python -c "from canonshuttercount.transport import USBBus; USBBus(); print('libusb backend loaded')"
```

An offline decoder is available for saved 24-byte windows:

```sh
canonshuttercount --decode window.bin --json
```

For other saved-record formats, select the model and exact firmware explicitly:

```sh
canonshuttercount --decode record.bin --model eos-400d --firmware 1.1.1 --json
```

That example requires the complete 56-byte RAM record, not the 5D window or a
USB reply. New-model decoders are tested with synthetic data, not hardware captures.

## Distribution plan

Version **0.1.0** is prepared as a source archive and a pure-Python wheel; see
[CHANGELOG.md](CHANGELOG.md) for features and support limits. To install a downloaded
wheel into a Python environment:

```sh
python -m pip install /path/to/canonshuttercount-0.1.0-py3-none-any.whl
canonshuttercount --version
```

The package builds a source archive and a pure-Python wheel. CI tests supported
Python minors on Linux, current Python on macOS, and baseline/current Python on
Windows. These are offline tests, not hardware support claims.

A future Homebrew tap formula will use Homebrew's supported Python, `libusb`, and
a checksummed PyUSB resource in its own environment. It will test decoding without
requiring a camera. A formula needs a stable release URL/checksum before publication;
none has been published yet.

See [PLAN.md](https://github.com/jamesyc/CanonShutterCount/blob/main/PLAN.md) for the milestones and [tests/fixtures/README.md](tests/fixtures/README.md)
for evidence provenance and the distinction between captured and synthetic tests.

## License

GNU General Public License version 3 (`GPL-3.0-only`). See [LICENSE](LICENSE).
