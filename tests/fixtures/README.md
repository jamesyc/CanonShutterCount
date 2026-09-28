# Protocol evidence

These fixtures are for offline tests. They do not authorize arbitrary replay on hardware.

- `counter_rollover.json`: actual 24-byte windows from user runs `read-o6t3821c`,
  `read-myxowrqz`, and `read-f74r5e6n`: 11,502 → 11,521 → 11,536. Upper value and
  selected ring slot advance from (44, 4) to (45, 5). These establish snapshots
  across rollover, not a capture of the exact 0xff boundary or a known number of
  intervening photos. No owner or serial-number read is included.

- `pc_connect_end_inactive.json`: the exact end-release request/reply from live run
  `pc-recovery-8g8iro4v`. Status `0x86` accompanies subcommand 1 and zero output.
  It contains no owner or serial-number values. The test replay inserts this exchange before the
  older initialization capture and renumbers transaction IDs, leaving other bytes
  unchanged. Status `0x86` is accepted only for this exact exit response.

- `counter.json`: exact 24-byte before/after windows from the reference `research/5d-counter-before.bin` and `5d-counter-after-one-shot.bin`. Recorded values: 11,300 and 11,301 after one user-reported photo. Unknown surrounding bytes are retained for exact comparison; they are not interpreted as additional counters.
- `dcp.log`: only OUT/IN lines from the successful reference `research/dcp-after-shot.log`. Removed the device descriptor dump. Contains the session setup, allocation, monitor open, two reads, monitor close, and return to PTP. No owner-name read or serial-number response is included. Service-path strings containing `SERIAL_NUMBER` are protocol constants.
- `pc_connect.json`: selected packets from `research/usb-baseline.log`: initial contact/wake, identification, owner read, and release-control initialization/GET_PARAMS. Owner fields are replaced with `Test Camera Owner ` (including trailing space) and zero padding. Intermediate body-ID, abilities, battery, and other configuration requests were omitted. Original transaction numbers are retained; tests set the next transaction number explicitly when jumping over omitted commands.

The PC Connect capture did not intercept interrupt transfers. Tests supply synthetic 16-byte wake interrupts, based on the handshake described in libgphoto2's Canon Class-6 initialization. Those bytes are not represented as observed camera evidence. The shortened standalone PC Connect sequence still requires live validation.

The DCP entry packet is checked against the corrected reference `pc_connect.c` layout: exactly 116 bytes, event string beginning at offset 0x50. It is not taken from the archived failed entry attempts.

Reference sources were read from `/tmp/canonshuttercount`; the installed package and tests do not depend on that directory. Protocol implementation is newly written from the documented wire exchanges. The libgphoto2 checkout consulted for interpreting the handshake is commit `b7529b283e616c35527fa02971a412b2a279bed1`; no upstream source files are distributed here.
