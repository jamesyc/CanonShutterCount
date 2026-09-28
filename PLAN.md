# CanonShutterCount implementation plan

## Current status

The reader works on the tested original Canon EOS 5D (firmware 1.1.1) on Apple
Silicon macOS from **both PC Connect and Print/PTP**. Both modes passed repeated
reads, owner verification, and PTP cleanup. A user-confirmed photograph increased
the count from 11,303 to 11,304. A later burst crossed a page/ring rollover; after
the buffer activity, settled reads from both starting modes matched at 11,536.

All **67 offline tests** pass under Python 3.9.25 and Python 3.14.7, including a
regression test built from actual snapshots across rollover and synthetic tests
for the older-camera decoders. The previous 61-test
baseline also passed fresh source-archive installations outside the checkout. Live interruption
and stale-session checks are recorded in [VALIDATION.md](VALIDATION.md).

The next phase is now **older EOS camera support**, at the user's request.
Offline decoding is implemented for 20D, 30D, 400D, 300D, and 10D;
new-model live entry/read/cleanup remains unimplemented and gated. No dedicated
20Da layout was established. None of these bodies is available for testing.

**Release preparation and Homebrew packaging** follows this work. The implementation
is still uncommitted, package metadata is `0.1.0.dev0`, no project license has been
chosen, remote CI has not run, and no tap formula has been published. Linux and
Windows camera behavior remains unverified.

## Requirements and accepted decisions

- Work in `~/git/CanonShutterCount`. Treat `/tmp/canonshuttercount` as read-only
  reference material; neither the application nor its tests depends on it.
- Support Python 3.9+. PyUSB is the only third-party Python runtime dependency;
  native USB access uses libusb 1.0. Normal reads require neither gphoto2 nor a C bridge.
- PC Connect and Print/PTP are first-class modes with equal acceptance criteria.
  Name the PC Connect implementation `pc_connect.py` / `PCConnect`.
- Both modes intentionally finish in USB Print/PTP (`3102`). The saved Communication
  preference remains unchanged. Direct software restoration to PC Connect was
  investigated and explicitly dropped by the user; do not resume that work unless asked.
- After a PC Connect read, print these two status lines, followed by the count and
  log location. Preserve machine-readable JSON on stdout when requested:

  ```text
  Started in PC Connect mode; USB mode is now Print/PTP.
  Power-cycle to return to the saved Communication setting.
  ```

- Initially support only the original 5D and validated firmware. Other models need
  documented profiles, decoder/protocol evidence, offline tests, and hardware validation.
- Use mise for development Python and uv for the project environment and lockfile.
  Homebrew supplies its own supported Python; mise and uv are not end-user requirements.
- Use standard-library unit tests. Hardware validation is separate and explicit.

## Architecture

| Module | Responsibility |
| --- | --- |
| `cli.py` | Arguments, text/JSON output, exit status |
| `reader.py` | Read lifecycle, interruption handling, cleanup, owner verification |
| `transport.py` | PyUSB boundary, backend discovery, interface ownership, bounded retries, USB-port correlation |
| `ptp.py` | PTP sessions, properties, stale-session recovery, DCP entry |
| `pc_connect.py` | PC Connect initialization, properties, release-control cleanup, DCP entry |
| `dcp.py` | Diagnostic session, approved monitor reads, PTP exit |
| `cameras.py` | Explicit camera profiles and pure decoders |
| `errors.py` | Protocol/transport errors and combined read/cleanup failures |

Use ordinary functions and small concrete classes. Protocol code accepts a transport
that tests can replace with replay data. Keep PyUSB imports at the transport boundary.
No plugin framework or speculative inheritance hierarchy is needed.

Normal flow: discover one Canon camera → validate model/firmware and preserve owner
bytes → enter DCP through the selected protocol → reconnect at the same physical USB
port → read the profile's approved window → close monitor and restore PTP → verify
owner → decode and report.

## Ongoing correctness requirements

- Validate the normal camera identity before diagnostic entry. The shared DCP product
  ID `3086` does not identify a model; a camera already in DCP requires explicit
  `--recover-dcp --model eos-5d` for recovery.
- Cleanup covers failures during mode transition, reconnection, claiming, reading,
  logging, and interruption. Preserve the initial error alongside cleanup failures.
  Do not print a successful count before cleanup and owner verification succeed.
- Defer SIGINT at protocol boundaries and throughout cleanup. Repeated Ctrl+C must
  allow bounded restoration and owner verification to finish, then exit 130. Forced
  termination or unplugging cannot guarantee recovery.
- Recover `SessionAlreadyOpen` (`0x201E`) with one close/reopen attempt. On this 5D,
  reopening the existing session was accepted directly; the `0x201E` branch is
  verified with offline replies, not claimed as a live observation.
- End stale PC Connect release control before initialization. Live tests established
  the warm `A` handshake and successful stale-session teardown. Accept `0x86` only
  for the exact verified already-inactive end-release reply; other failures stay fatal.
- Retry interface-claim NoDevice errors only within a bounded window, with the same
  USB location and product. Never retry arbitrary mode-changing commands blindly.
- Keep PC Connect's 116-byte entry packet and event-string offset `0x50` checked.
  Archived malformed attempts are not implementation references.
- Preserve owner bytes, including trailing spaces; ignore unspecified bytes after
  the first NUL. Owner mismatch errors point to the packaged manual recovery guide.
  There is no automatic owner-write path. gphoto2 is only a separate manual recovery
  option. The guide is syntax-checked; its write operation has not been invoked on
  the current camera.
- A real rollover is observed in the 11,502 → 11,521 snapshots: upper value 44 → 45,
  selected ring slot 4 → 5. The exact `0xff` sample and adjacent single-shot boundary
  remain uncaptured. Retain ambiguous `0xff` rejection. Distinguish these observations
  from synthetic boundary tests and from a measured number of intervening photos.
- Unit tests must never access a camera. Cover malformed replies, sequence errors,
  timeouts, disconnects, owner mismatches, and cleanup failures, including commands
  that must not be sent after a failure.

## Completed milestones

- [x] Create documented, sanitized reference fixtures and decoder/DCP replay tests.
- [x] Implement and hardware-test standalone PC Connect and direct Print/PTP without gphoto2.
- [x] Implement shared USB transport, camera profiles, identity correlation, logging, and CLI.
- [x] Validate stable counts from both modes, matching counter windows, unchanged owner, monitor closure, and PTP restoration.
- [x] Validate the user-controlled one-photo increment: 11,303 → 11,304. The application never triggers a photo.
- [x] Capture and replay actual windows across a page/ring rollover: 11,502 → 11,521 → 11,536. The user confirmed the burst buffer was draining during these reads. Settled reads from both modes now match at 11,536; exact `0xff` behavior and counter-persistence timing remain unverified.
- [x] Complete the requested forced-stop/power-cycle check: SIGKILL after DCP initialization left `3086`; the user's power cycle restored `3101`. Follow-up `read-jnqqhh86` returned 11,536 with an identical counter window and unchanged owner. This validates that stop point, not every interruption/unplug scenario.
- [x] Implement stale-session/release-control recovery and deferred repeated Ctrl+C; test offline and on the actual camera.
- [x] Test six externally delivered SIGINT signals against the CLI: exit 130, no count output, PTP restored, owner unchanged.
- [x] Package manual owner-recovery instructions and link them from the verification error. This was completed after the initial hardware validation.
- [x] Build source/wheel artifacts and verify fresh installs, all 61 tests, the installed decoder, and packaged guide on Python 3.9.25 and 3.14.7.
- [x] Verify automatic and explicit libusb loading locally without application-level camera discovery. Support `CANONSHUTTERCOUNT_LIBUSB` for nonstandard installation prefixes.
- [x] Configure CI: Python 3.9–3.14 on Linux, 3.14 on macOS, and 3.9/3.14 on Windows; native backend loading checks on Linux/macOS. Configuration is complete; remote execution is pending.
- [x] Accept PTP exit from both modes and archive direct PC Connect restoration research.

## Next phase: older EOS support

- [x] Add offline saved-record decoding for 20D, 30D, 400D, 300D, and 10D with
  synthetic tests and explicit model/firmware selection. Keep the live 5D gate.
- [ ] Implement and replay-test bounded RAM transport and cleanup for 20D/30D/400D.
- [ ] Implement and replay-test each model's entry path and identity checks,
  including the distinct 30D PC Connect and Print/PTP paths.
- [ ] Implement and replay-test 300D/10D factory-session entry, strict reply
  validation, reads, and cleanup. Do not route these through the 5D DCP profile.
- [ ] Establish a separate 20Da profile from firmware/protocol evidence.
- [ ] Validate each new body/firmware and applicable mode on actual hardware.
  Tell the user when its implementation is ready for manual testing; offline
  decoding alone does not meet that milestone.

## Following phase: release preparation

1. **Choose the project license and audit release contents.**
   - [ ] Obtain the user's license choice and add the license file/package metadata.
   - [ ] Review source and fixture provenance, documentation, and distribution contents.
   - [ ] Keep private camera logs, firmware images,
     `.analysis`, virtual environments, caches, and build outputs out of version control
     and published distributions. Keep only the necessary sanitized fixtures.
2. **Run remote CI on the reviewed implementation.**
   - [ ] Commit the application, tests, documentation, configuration, and `uv.lock`.
   - [ ] Push the reviewed changes and run the configured GitHub Actions matrix.
   - [ ] Resolve actual platform failures and verify the installed artifacts on runners.
     Passing offline CI does not establish Linux/Windows camera support.
3. **Create a versioned release and prepare the Homebrew tap.**
   - [ ] Choose the first release version, update metadata/lockfile, and write release notes.
   - [ ] Produce the source release URL and SHA-256 checksum.
   - [ ] Write the tap formula with Homebrew's supported Python, libusb, and a checksummed
     PyUSB resource installed in an isolated environment.
   - [ ] Select the formula's native library through `CANONSHUTTERCOUNT_LIBUSB` when
     needed, rather than assuming a particular Homebrew prefix.
   - [ ] Test formula installation, the installed decoder/command, and native backend
     loading without a camera. Verify that the owner-recovery guide is installed.
   - [ ] Publish the reviewed release/tap. A later homebrew/core submission is separate.
4. **Expand hardware validation when those environments are available.**
   - [ ] Test the actual 5D from both modes on Linux, including scoped USB permissions
     for `3101`, `3102`, and `3086`.
   - [ ] Test Windows native-library/driver setup, both modes, and USB transitions.
   - [ ] Record OS, architecture, firmware, native backend version, cleanup, and owner
     results before broadening support claims. Additional cameras follow the same rule.

The release-specific outstanding decision is the **project license**. Release publication
has not been performed as part of development or this plan update.

## Development and packaging conventions

- `mise.toml` selects development tools; uv uses mise's interpreter explicitly with
  automatic Python downloads disabled for that workflow.
- `pyproject.toml` owns package metadata, Python minimum, dependencies, and console entry point.
- `uv.lock` records development resolution. Homebrew resources separately pin source
  versions and checksums; they do not depend on the developer's virtual environment.
- Store logs in a writable user directory or explicit `--log-dir`, never alongside
  installed code. Raw traces may contain owner and serial information.
- Keep normal installation independent of reference/research files. Analysis tools
  may take an explicit firmware path and use isolated analysis dependencies.

## Evidence and archived research

- [VALIDATION.md](VALIDATION.md): exact local tests and actual-device observations,
  including limitations and private log identifiers.
- [Fixture provenance](tests/fixtures/README.md): captured versus synthetic data.
- [Manual owner recovery](src/canonshuttercount/OWNER_RECOVERY.md): separate manual procedure.
- [USB mode research](docs/USB_MODE_RESEARCH.md):
  archived work; not a pending requirement or permission to resume mode-switch probes.
- Local reference: `/tmp/canonshuttercount`, read-only; not a runtime/test dependency.
- [PyUSB](https://github.com/pyusb/pyusb/blob/master/README.rst)
- [libusb Windows](https://github.com/libusb/libusb/wiki/Windows)
- [Python packaging](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Homebrew Python packaging](https://docs.brew.sh/Language-Specific-Formulae#python)
- [uv Python selection](https://docs.astral.sh/uv/concepts/python-versions/)
- [uv resolution](https://docs.astral.sh/uv/concepts/resolution/)
