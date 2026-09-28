"""Live 5D profile and offline counter layouts."""

from dataclasses import dataclass
from typing import Callable

from .errors import ProtocolError


@dataclass(frozen=True)
class CameraProfile:
    name: str
    pc_product: int
    ptp_product: int
    dcp_product: int
    firmware: bytes
    memory_kind: int
    chunks: tuple
    decoder: Callable[[bytes], int]


def owner_bytes(data):
    """Preserve name bytes/spaces; bytes after the first NUL are unspecified."""
    name, terminator, _ = data.partition(b"\0")
    if not terminator:
        raise ProtocolError("Malformed owner-name field")
    return name


def decode_5d(data):
    """Decode the documented 24-byte MPU window; ambiguous values fail closed."""
    if len(data) != 24:
        raise ProtocolError("Expected exactly 24 counter bytes")
    upper = int.from_bytes(data[11:13], "big")
    slot = upper % 8
    low = data[13 + slot]
    count = (upper << 8) | low
    if low == 0xFF or count > 9_999_999:
        raise ProtocolError("Counter is ambiguous or exceeds the validated decoder limit")
    return count


EOS_5D = CameraProfile(
    "Canon EOS 5D", 0x3101, 0x3102, 0x3086,
    bytes.fromhex("02010101"), 2, ((0x938, 12), (0x944, 12)), decode_5d,
)


def validate_identity(model, firmware, profile=EOS_5D):
    if model != profile.name or firmware != profile.firmware:
        raise ProtocolError("Unsupported model or firmware for " + profile.name)


# Offline evidence only: (counter address, record length, counter offset,
# required-zero byte). These are RAM records, NOT 5D MPU monitor windows.
RAM_COUNTERS = {
    ("eos-20d", "1.1.0"): (0x10994, 24, 12, 10),
    ("eos-20d", "2.0.0"): (0x10E34, 24, 12, 10),
    ("eos-20d", "2.0.2"): (0x10E34, 24, 12, 10),
    ("eos-20d", "2.0.3"): (0x10E34, 24, 12, 10),
    ("eos-30d", "1.0.4"): (0xFEFC, 56, 20, None),
    ("eos-30d", "1.0.5"): (0xFF3C, 56, 20, None),
    ("eos-30d", "1.0.6"): (0xFF3C, 56, 20, None),
    ("eos-400d", "1.0.4"): (0xEBBC, 56, 20, None),
    ("eos-400d", "1.0.5"): (0xEBBC, 56, 20, None),
    ("eos-400d", "1.1.0"): (0xEBFC, 56, 20, None),
    ("eos-400d", "1.1.1"): (0xEBFC, 56, 20, None),
}
HC12_REFERENCE_FIRMWARE = {"eos-300d": "1.1.1.0", "eos-10d": "1.0.0.0"}
OFFLINE_MODELS = ("eos-5d", "eos-400d", "eos-30d", "eos-20d", "eos-300d", "eos-10d")


def decode_saved_window(data, model="eos-5d", firmware=None):
    """Decode a raw record, not a USB reply; never authorize live camera access.

    The additional layouts have synthetic tests but no camera captures.
    A plausible result cannot prove that the supplied bytes are a shutter counter.
    """
    if model == "eos-5d":
        if firmware not in (None, "1.1.1"):
            raise ProtocolError("Unsupported saved-window firmware for eos-5d")
        return decode_5d(data)
    if model in HC12_REFERENCE_FIRMWARE:
        if firmware != HC12_REFERENCE_FIRMWARE[model]:
            raise ProtocolError("Use the documented HC12 reference firmware for " + model)
        if len(data) != 10:
            raise ProtocolError("Expected exactly 10 HC12 counter bytes from 0x10c0")
        upper = int.from_bytes(data[:2], "big")
        low = data[2 + upper % 8]
        count = (upper << 8) | low
        # Keep the project's conservative erased-byte policy, not an approximation.
        if low == 0xFF or count == 0 or count > 9_999_999:
            raise ProtocolError("HC12 counter is zero, ambiguous, or exceeds the decoder limit")
        return count
    layout = RAM_COUNTERS.get((model, firmware))
    if layout is None:
        raise ProtocolError("No saved-window layout for this model/firmware")
    _, length, offset, zero_offset = layout
    if len(data) != length:
        raise ProtocolError("Expected exactly %d RAM record bytes" % length)
    if zero_offset is not None and data[zero_offset] != 0:
        raise ProtocolError("RAM record failed its required-zero layout check")
    count = int.from_bytes(data[offset:offset + 4], "little")
    if count > 9_999_999:
        raise ProtocolError("RAM counter exceeds the decoder limit")
    return count
