"""Portable command-line entry point; hardware is opened only for live operations."""

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys
import tempfile

from .cameras import OFFLINE_MODELS, decode_saved_window
from .errors import ProtocolError, ReadFailure


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read the original Canon EOS 5D shutter count over USB.")
    parser.add_argument("--version", action="version", version=version("canonshuttercount"))
    parser.add_argument("--json", action="store_true", help="write machine-readable results to stdout")
    parser.add_argument("--log-dir", type=Path, help="parent directory for a new private run log folder")
    parser.add_argument("--model", choices=OFFLINE_MODELS, help="saved-window model; live reads/recovery support eos-5d only")
    parser.add_argument("--firmware", help="firmware for offline decoding; required for models other than eos-5d")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--decode", type=Path, metavar="WINDOW", help="decode a saved raw counter window without USB access (default: eos-5d)")
    actions.add_argument("--recover-dcp", action="store_true", help="restore a known 5D already in DCP; do not read memory")
    args = parser.parse_args(argv)
    if args.recover_dcp and args.model != "eos-5d":
        parser.error("--recover-dcp requires --model eos-5d; the diagnostic USB ID is shared by other cameras")
    if args.decode is None and args.model not in (None, "eos-5d"):
        parser.error("This model has offline decoding only; live entry and cleanup are not implemented")
    if args.firmware is not None and args.decode is None:
        parser.error("--firmware is for --decode only; live firmware is checked on the camera")
    logdir = None
    try:
        if args.decode is not None:
            result = dict(shutter_count=decode_saved_window(args.decode.read_bytes(), args.model or "eos-5d", args.firmware))
            if args.model not in (None, "eos-5d"):
                print("Offline decoding only; no hardware validation for this model.", file=sys.stderr)
        else:
            from .reader import read_count
            from .transport import USBBus

            parent = args.log_dir or Path.home() / ".canonshuttercount" / "logs"
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            logdir = Path(tempfile.mkdtemp(prefix="read-", dir=str(parent)))
            with (logdir / "usb.jsonl").open("w", encoding="utf-8") as log:
                result = read_count(USBBus(log), logdir, recover=args.recover_dcp)
        if "start_mode" in result and not args.recover_dcp:
            mode = "PC Connect" if result["start_mode"] == "pc-connect" else "Print/PTP"
            print("Started in %s mode; USB mode is now Print/PTP." % mode, file=sys.stderr)
            if not result["restored_start_mode"]:
                print("Power-cycle to return to the saved Communication setting.", file=sys.stderr)
        if args.json:
            print(json.dumps(result))
        elif "shutter_count" in result:
            print("Shutter count: {:,}".format(result["shutter_count"]))
        else:
            print("PTP restored.")
        return 0
    except ReadFailure as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 130 if error.interrupted else 1
    except (ProtocolError, OSError, ImportError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    finally:
        if logdir is not None:
            print("Logs: " + str(logdir), file=sys.stderr)
