"""Relocations whose 4 bytes cross the end of a data range of delinks.txt: dsd delink panics on them
("range end index 4 out of range", cli/src/config/section.rs), and no C file can write such a word.

They appear when bsssplit/datasplit give one file to each small symbol. A real pointer does not overlap the next
symbol, so the relocation is a false one found in a byte table: --apply deletes it (the bytes do not change).

    python relocstraddle.py [--apply]     # from the game's folder
"""
import bisect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import SECTION, modules  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    total = 0
    for name, folder in modules().items():
        body = (folder / "delinks.txt").read_text(encoding="utf-8").partition("\n\n")[2]
        # the gaps between ranges are objects too: every start and end of a range is a boundary
        bounds = sorted({int(x, 16) for sec, s, e in SECTION.findall(body) if sec in (".data", ".rodata") for x in (s, e)})
        path = folder / "relocs.txt"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = []
        for line in lines:
            m = re.match(r"from:0x([0-9a-f]+) ", line)
            if m:
                frm = int(m[1], 16)
                k = bisect.bisect_right(bounds, frm)
                if k < len(bounds) and bounds[k] < frm + 4:
                    print(name, line.strip()[:90])
                    total += 1
                    continue
            keep.append(line)
        if apply and len(keep) != len(lines):
            path.write_text("".join(keep), encoding="utf-8", newline="\n")
    print(total, "relocations" + (" removed" if apply else ""))


if __name__ == "__main__":
    main()
