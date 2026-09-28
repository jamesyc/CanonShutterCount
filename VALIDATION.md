# Validation status

## New implementation in this repository

| Check | Status |
| --- | --- |
| 67 offline unit tests, Python 3.9.25 and 3.14.7 | Passed, including actual 5D windows across rollover and synthetic older-model decoders |
| 20D/30D/400D saved RAM records and 300D/10D saved HC12 ring decoding | Synthetic offline checks only; no new-model hardware validation |
| New-model live reads and recovery | Not implemented; CLI rejects before USB construction |
| Source distribution built with Python 3.9.25 | Passed |
| Fresh source-archive install outside checkout, Python 3.9.25 | Passed; all 61 tests, installed decoder, recovery document, automatic/explicit native backend loading |
| Fresh source-archive install outside checkout, Python 3.14.7 | Passed; all 61 tests, installed decoder, recovery document, automatic/explicit native backend loading |
| Pure-Python wheel build | Passed |
| Source archive includes sanitized replay fixtures | Checked |
| Package import and offline decoder without USB discovery | Tested |
| Native libusb discovery in development environment | Working after user installed Homebrew libusb 1.0.30 |
| PC Connect live read on original 5D | Latest settled read 11,536; matches Print/PTP; PTP restored; owner unchanged |
| Print/PTP live read on original 5D | Latest settled read 11,536; matches PC Connect; PTP restored; owner unchanged |
| Stale PC Connect release control | Live recovery passed; warm handshake A; inactive exit 0x86, active exit 0; owner unchanged |
| PTP session left open | Live second OpenSession accepted; owner unchanged. 0x201E close/reopen path tested offline |
| Repeated SIGINT during live read/cleanup | Passed from both starting modes; PTP restored and owner verified despite six injected signals per run |
| External SIGINT against CLI process | Six signals; exit 130; no count output; PTP restored and owner unchanged |
| Forced stop after DCP initialization | SIGKILL left DCP active; user power cycle restored PC Connect; follow-up read remained 11,536 with identical window and owner |
| Linux/Windows hardware behavior | Unverified |
| GitHub Actions matrix | First run failed at locked sync before tests; project-local cooldown fix passes isolated sync locally; remote rerun pending |
| Homebrew tap installation | Pending release preparation |
| GPLv3 packaging | Canonical LICENSE and GPL-3.0-only metadata verified in the built wheel |
| PC Connect restoration investigation | Archived by user decision; application intentionally exits to PTP |
| Counter rollover snapshots | Upper 44 → 45, slot 4 → 5 observed; exact 0xff sample not captured |

Unit tests inject transport faults and use recorded or synthetic replies. They do
not access a camera and do not establish live hardware support. Fixtures identify
their provenance and any sanitization/synthetic content in `tests/fixtures/README.md`.

## Older-camera offline decoding (2026-09-28)

No USB enumeration or camera operation was performed during this work.

Added five test methods covering the RAM layouts, HC12 ring arithmetic,
malformed/ambiguous data, firmware selection, offline JSON output, and rejection
of every new model for live reads/recovery before bus construction. All new
records are generated synthetic bytes, not camera captures.
The live 5D protocol and hardware acceptance status are unchanged.

`mise run test` passed all 67 tests with Python 3.9.25. A fresh uv-built package
passed all 67 with mise Python 3.14.7. The initial 3.14 invocation reused a stale
uv build and failed imports of the newly added symbols; rerunning with
`uv run --no-cache --no-project --python "$(mise where python@3.14.7)/bin/python3" --with . python -m unittest discover -s tests`
rebuilt the current source and passed. This is offline verification, not a new
source-archive installation or hardware-validation claim.

The user has none of the requested new bodies available. Live support for them
is not ready for manual testing. A separate 20Da profile still needs evidence.

## PC Connect owner-field correction

Manual run `read-7ae4nv1z` completed PC Connect initialization and identification,
then failed before DCP entry with `Malformed owner-name field`. Its 32-byte owner
reply contained a valid NUL-terminated name followed by nonzero unused bytes.
The parser had incorrectly required all bytes after the terminator to be zero.

The shared parser now ignores those unspecified bytes, preserves all name bytes
including trailing spaces, and still rejects a missing terminator. Two regression
tests use synthetic tail bytes. Parsing the actual saved reply now produces exactly
the owner value captured in the successful Print/PTP run. No private name or tail
bytes were added to the repository. The subsequent run `read-xr3yodzt` completed
a full PC Connect read successfully after this correction.

## Interruption and session-recovery tests

- `ptp-recovery-otbjxw3j`: deliberately left a PTP session open while releasing
  the host handle. A second OpenSession for session 1 was accepted and the owner
  matched. This body did not return `0x201E` in this test. That response is covered
  by offline tests requiring exactly one CloseSession/OpenSession recovery and
  failure on other statuses or a second refusal.
- `pc-recovery-8g8iro4v`: ending inactive PC Connect release control returned
  `0x86` with the expected subcommand-1 payload.
- `pc-recovery-k70ooewj`: initialized release control, released the host handle
  without ending it, and opened a new connection. Both handshakes returned `A`.
  The new cleanup sequence ended the stale session and initialized a fresh one.
  Exit statuses were `0x86`, `0`, `0`; owner bytes matched before/after.
- `interrupt-p_66avsz`: an initial test hit a transient DCP interface-claim
  failure before signal injection. Explicit recovery `read-hkh6r0pr` restored
  PTP without a reboot. The subsequent owner check matched the saved original.
  Bounded same-port/same-product retries for backend NoDevice errors were added
  and tested with injected backend failures; other claim errors remain fatal.
- `interrupt-ptp-oy9x25hq` and `interrupt-pc-6pz4a_l3`: actual camera reads from
  Print/PTP and PC Connect with six `signal.raise_signal(SIGINT)` injections per
  run: after the first counter chunk, after MonClose, and after the final owner
  read. Cleanup completed, PTP was verified, owner bytes matched, the previous
  signal handler was restored, and no successful count result was published.
- `external-sigint-syhqy29w/read-mu6lqs2j`: a separate parent process sent six
  SIGINT signals to the running CLI after observing its counter-read request.
  The CLI exited 130 with empty stdout, restored PTP, and verified the owner.
- `read-3kn4g6qt`: a normal CLI run after the interruption changes returned
  11,304 with successful cleanup and unchanged owner.

All raw logs remain private. Tests did not trigger the shutter or modify the owner.
Forced process termination and unplugging still cannot guarantee software cleanup.
The manual owner-restoration guide is packaged and syntax-checked on Python 3.9
and 3.14; its write operation has not been invoked against the camera.

## Manual acceptance

### Settled baseline and forced-stop test

After the burst-buffer activity, `read-3p5b5red` (PC Connect) and `read-kk5yarba`
(Print/PTP) both returned 11,536. Their complete counter windows and owner values
match exactly. PTP restoration and owner verification passed in both runs.

Test `forced-stop-s1aclqde/read-w8c4l_07` deliberately paused a child reader after
DCP initialization, before MonOpen or any counter read, then terminated only that
child with SIGKILL. Exit status was -9. The trace confirms no MonOpen,
MonReadAndGetData, or SetUSBToPTPMode was sent; the camera remained at USB identity
`3086` on the same physical port. The saved owner matches the settled baseline.
After the user power-cycled, USB enumeration confirmed `3101` (PC Connect).
Verification run `read-jnqqhh86` returned 11,536, with the complete counter window
identical to `read-kk5yarba`. The post-restart before/after owner values also match
the baseline and the owner saved by the killed reader. Normal PTP cleanup succeeded.
This controlled stop point does not represent every possible interruption or unplug.

### Rollover observations

The user supplied these reads while investigating a burst and slow card writing:

| Run | Count | Upper | Selected ring slot | Low byte |
| --- | --- | --- | --- | --- |
| `read-o6t3821c` | 11,502 | 44 | 4 | `0xee` (238) |
| `read-myxowrqz` | 11,521 | 45 | 5 | `0x01` (1) |
| `read-f74r5e6n` | 11,536 | 45 | 5 | `0x10` (16) |

All three saved results, windows, and before/after owner comparisons were checked;
PTP cleanup and owner verification succeeded. These samples cross a real rollover
and match the 5D decoder's formula. The old slot remains
`0xee` after the upper value advances; only the newly selected slot supplies the low
byte. The samples at exactly 11,519/0xff and 11,520 were missed.

The user confirms using continuous burst and that the card buffer was still draining
during the changing readings. The number of intervening photos and precise counter
persistence timing were not independently measured. The reader continues to reject
the ambiguous selected byte `0xff`.

Raw counter windows are captured in `tests/fixtures/counter_rollover.json` and replayed
by a regression test. No owner/serial data was added to the repository.

### Recorded new-reader runs

| Local log folder | Starting mode | Count | PTP restored | Owner unchanged |
| --- | --- | --- | --- | --- |
| `read-vi1kdp_3` | Print/PTP | 11,303 | Yes | Yes |
| `read-xr3yodzt` | PC Connect | 11,303 | Yes | Yes |
| `read-7bzqxttc` | Print/PTP | 11,304 | Yes | Yes |
| `read-77gszj0v` | PC Connect | 11,304 | Yes | Yes |
| `read-vdudqrat` | PC Connect | 11,304 | Yes | Yes |
| `read-imkgpmi7` | Print/PTP | 11,304 | Yes | Yes |
| `read-3kn4g6qt` | Print/PTP | 11,304 | Yes | Yes |
| `read-3p5b5red` | PC Connect | 11,536 | Yes | Yes |
| `read-kk5yarba` | Print/PTP | 11,536 | Yes | Yes |
| `read-jnqqhh86` | PC Connect, after forced-stop power cycle | 11,536 | Yes | Yes |

The photograph was taken between `read-xr3yodzt` and `read-7bzqxttc`. The 11,304
windows from both starting modes match exactly, as do the 11,303 windows, and the
owner bytes are identical before and after the first four runs. The subsequent
`read-vdudqrat` repeats the 11,304 count with an identical window to `read-77gszj0v`
and unchanged before/after owner bytes, confirming PC Connect count stability.
Run `read-imkgpmi7` then started in Print/PTP without a power cycle, repeated
11,304, and preserved the owner. Its window matches both `read-vdudqrat` and
the earlier Print/PTP run `read-7bzqxttc`, confirming stability in both modes.

The user ran the program with Homebrew libusb 1.0.30 on Apple Silicon macOS;
the saved `result.json` files were checked against the reported terminal output.
The initial 11,303 counter windows match exactly across modes. The first PC Connect before/after
owner bytes match each other and the earlier Print/PTP owner value. All runs passed
the model/firmware check. Raw logs remain in the user's private
`~/.canonshuttercount/logs` directory. No-photo stability checks have passed for
both starting modes. The increment is supported by the user's single-photo
confirmation below. Returning to the
starting PC Connect identity is still unimplemented/unverified; the successful
PC Connect run ended in PTP, as reported by the program.

For each starting mode, record the firmware, actual reported starting mode, count,
successful PTP restoration, and unchanged owner result. Repeat without taking a
photograph to check count stability. To repeat a PC Connect start, power-cycle to
return to the saved Communication setting after the previous run restored PTP.

Run `read-77gszj0v` changed only counter-window byte 17, from `0x27` to `0x28`,
relative to `read-xr3yodzt`. The user confirmed taking one photograph between these
runs: 11,303 → 11,304 is a user-controlled one-photo increment check on the new
implementation, not a no-photo stability test. Both traces send `SetUSBToPTPMode`, then perform PTP
OpenSession/property reads/CloseSession. A read-only USB enumeration after each
reported run found `04a9:3102` (PTP). The later run starting in PC Connect does not
establish how or when it returned to that mode between runs. The Communication-menu
preference and currently enumerated USB mode are separate observations. After the
user explicitly power-cycled the camera and reported that its menu still said
PC Connect, a fresh read-only enumeration found `04a9:3101` (PC Connect). This
confirms that power-cycling restored the saved preference on this body; it does
not validate a software route from DCP directly back to PC Connect.

After `read-vdudqrat`, the user explicitly reported no further power cycle and a
menu still showing PC Connect. Read-only USB enumeration at that point found
`04a9:3102` (PTP), directly demonstrating the distinction between the saved menu
preference and active USB communication mode.

Keep raw logs private. Report the terminal output before sharing a trace. A separate
user-controlled photo can validate an increment; the program never triggers one.

The reference prototype previously produced 11,300 then 11,301 after one photo,
and later read 11,303 in both modes. Those results belong to the reference prototype,
not this new implementation.
