"""Offline ARM firmware inspection; requires capstone only in the analysis environment.

Pass the reference image explicitly. This tool never accesses a camera.
Example: uv run --no-project --with capstone==5.0.9 python tools/inspect_firmware.py IMAGE --range 0xff9d7320:0xff9d73f0
"""

import argparse
import hashlib
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--base", type=lambda value: int(value, 0), default=0xFF810000)
    parser.add_argument("--range", action="append", default=[])
    parser.add_argument("--refs", action="append", type=lambda value: int(value, 0), default=[])
    args = parser.parse_args()
    data = args.image.read_bytes()
    print("SHA256:", hashlib.sha256(data).hexdigest())

    def word(address):
        offset = address - args.base
        if not 0 <= offset <= len(data) - 4:
            raise ValueError("Address outside supplied image: %#x" % address)
        return struct.unpack_from("<I", data, offset)[0]

    if args.refs:
        for offset in range(0, len(data) - 3, 4):
            address = args.base + offset
            value = word(address)
            if value in args.refs:
                print("literal %#x -> %#x" % (address, value))
            if value & 0x0E000000 == 0x0A000000:
                displacement = value & 0xFFFFFF
                if displacement & 0x800000:
                    displacement -= 0x1000000
                target = (address + 8 + 4 * displacement) & 0xFFFFFFFF
                if target in args.refs:
                    print("branch  %#x -> %#x" % (address, target))

    if args.range:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN
        from capstone.arm import ARM_OP_MEM, ARM_REG_PC

        disassembler = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN)
        disassembler.detail = True
        disassembler.skipdata = True
        for region in args.range:
            start, end = (int(value, 0) for value in region.split(":"))
            if start % 4 or end % 4 or not args.base <= start < end <= args.base + len(data):
                parser.error("range must be aligned and inside the supplied image")
            print("Range %#x:%#x" % (start, end))
            for instruction in disassembler.disasm(data[start - args.base:end - args.base], start):
                note = ""
                if instruction.id and instruction.mnemonic.startswith("ldr"):
                    for operand in instruction.operands:
                        if operand.type == ARM_OP_MEM and operand.mem.base == ARM_REG_PC:
                            literal = instruction.address + 8 + operand.mem.disp
                            value = word(literal)
                            note = " ; [%#x] = %#x" % (literal, value)
                            if args.base <= value < args.base + len(data):
                                raw = data[value - args.base:value - args.base + 96].split(b"\0", 1)[0]
                                if raw and all(32 <= byte < 127 for byte in raw):
                                    note += " " + repr(raw.decode("ascii"))
                print("%08x %-8s %s%s" % (instruction.address, instruction.mnemonic, instruction.op_str, note))


if __name__ == "__main__":
    main()
