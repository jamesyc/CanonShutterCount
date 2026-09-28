# Manual owner-name recovery

Use this procedure only after an owner-verification failure, with the
`owner-before.bin` from that exact run. It contains the original name bytes,
including trailing spaces. Keep this file and the USB trace private.

The reader never writes an owner name automatically. This manual procedure uses
gphoto2, which is **not a dependency for normal shutter-count reads**. The earlier
reference investigation used gphoto2 to restore and verify an owner name. The
procedure below has not been deliberately tested by damaging the current name.

1. Stop other camera applications. Connect only the known original EOS 5D.
2. Get back to normal communication: power-cycle the camera and select Print/PTP,
   or use `canonshuttercount --recover-dcp --model eos-5d` if this known body is
   stuck in DCP. The recovery command changes USB mode, not the owner name.
3. Install gphoto2 separately if needed (`brew install gphoto2` on macOS).
4. Inspect the backup locally. Do not trim whitespace or substitute a name from
   another run. Save the following script as a temporary file, and pass the exact
   backup path as its only argument. The script checks the model, shows the name
   with spaces visible via `repr`, requires you to type `RESTORE`, and verifies
   the exact value afterward.

```python
from pathlib import Path
import os
import subprocess
import sys

original = Path(sys.argv[1]).read_bytes()
environment = dict(os.environ, LC_ALL="C")
if len(original) > 31 or any(byte < 32 or byte > 126 for byte in original):
    raise SystemExit("Unsupported owner encoding; do not guess or trim the name.")

def get_value(key):
    result = subprocess.run(
        ["gphoto2", "--get-config", key], capture_output=True, check=True,
        timeout=45, env=environment,
    )
    for line in result.stdout.split(b"\n"):
        if line.startswith(b"Current: "):
            return line[len(b"Current: "):].removesuffix(b"\r")
    raise SystemExit("Could not read camera property; no restoration attempted.")

if get_value("cameramodel") != b"Canon EOS 5D":
    raise SystemExit("Camera model did not match the original EOS 5D.")
if get_value("ownername") == original:
    raise SystemExit("Owner already matches the backup; no write needed.")
print("Original owner:", repr(original.decode("ascii")))
if input("Type RESTORE to write this exact owner name: ") != "RESTORE":
    raise SystemExit("Cancelled.")
subprocess.run(
    ["gphoto2", "--set-config", "ownername=" + original.decode("ascii")],
    check=True, timeout=45, env=environment,
)
if get_value("ownername") != original:
    raise SystemExit("Verification failed. Preserve the backup and stop here.")
print("Owner restored and verified, including trailing spaces.")
```

Run it with Python 3.9 or newer:

```sh
python restore_owner.py /absolute/path/to/the/failed/run/owner-before.bin
```

This deliberately accepts only printable ASCII names, including an empty name,
because translating an unknown camera encoding could alter the value. For a
non-ASCII backup, preserve the raw bytes and establish the correct encoding and
write method before proceeding. If the backup is missing, do not invent a value.
