"""profpadfix.py [--dry-run] : removes the last difference of matched -profile functions in .data.

A matched function's record was delinked as [start, end4) because a 1-3 byte gap object would be 4-aligned by mwld and
shift everything; objdiff then compares n bytes with the padded n+k (.data = 2n/(2n+k), accepted by match.py verify,
but never counted as matched data). Now the record is delinked exactly [start, end) and the zero padding is a C object
of its own, src/data/<mod>_profpad_<end>.c: tools/ld_align.py lowers the alignment of a file that starts off 4.
Idempotent: run it after new -profile matches, then `configure.py` + `match.py verify`.
Technique id: prof-pad-file. Origin: Heroes of Mana (2026-11-01).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402
from bssgen import modules  # noqa: E402

ROOT = project.ROOT


def main() -> None:
    dry = "--dry-run" in sys.argv
    prof = json.loads((ROOT / "build" / "profnames.json").read_text(encoding="utf-8"))
    ends = {(v["rec"][0], v["end4"]): v["rec"][1] for v in prof.values() if "end4" in v and v["end4"] != v["rec"][1]}
    fixed = 0
    for name, folder in modules().items():
        d = folder / "delinks.txt"
        text = d.read_text(encoding="utf-8")
        head, sep, body = text.partition("\n\n")
        tag = "" if name in ("main", "itcm", "dtcm") else f"{name}_"
        pads = []

        def fix(m):
            nonlocal fixed
            if "/data/" in m[1]:  # a profrec file holds its padding already
                return m[0]
            s, e = int(m[3], 16), int(m[4], 16)
            end = ends.get((s, e))
            if end is None:
                return m[0]
            fixed += 1
            rel = f"src/data/{name}_profpad_{end:08x}.c"
            pads.append(f"\n{rel}:\n    complete\n    .data       start:0x{end:08x} end:0x{e:08x}\n")
            if not dry:
                (ROOT / rel).write_text('/* compiler: 2.0/sp1p5 */\n#include "m2c.h"\n\n#pragma explicit_zero_data on\n'
                                        f"u8 data_{tag}{end:08x}[{e - end}] = {{0}};\n", encoding="utf-8", newline="\n")
            return f"{m[1]}:{m[2]}    .data       start:0x{s:08x} end:0x{end:08x}"
        new = re.sub(r"^(\S+\.(?:c|cpp)):((?:\n[ \t]+.*)*?\n)[ \t]+\.data\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+)", fix, body, flags=re.M)
        if new != body and not dry:
            d.write_text(head + sep + new.rstrip("\n") + "\n" + "".join(pads), encoding="utf-8", newline="\n")
    print(f"{fixed} records unrounded, as many padding files")


if __name__ == "__main__":
    main()
