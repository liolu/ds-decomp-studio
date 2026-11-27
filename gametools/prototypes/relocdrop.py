"""relocdrop.py MODULE START END [START END ...] : delete the relocations dsd found inside number tables (false pointers).

For a table datagap calls thumbptr/noname although its words are plainly numbers (sine table, u16 pairs, palettes):
dsd took a few values for pointers, and datagen cannot write them. Look at the bytes first. Then run datagen.
MODULE = main, itcm, dtcm, ov000...
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import modules  # noqa: E402


def main() -> None:
    mod, *nums = sys.argv[1:]
    ranges = [(int(nums[i], 16), int(nums[i + 1], 16)) for i in range(0, len(nums), 2)]
    path = modules()[mod] / "relocs.txt"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    keep = [x for x in lines if not ((m := re.match(r"from:0x([0-9a-f]+)", x)) and
                                     any(s <= int(m[1], 16) < e for s, e in ranges))]
    path.write_text("".join(keep), encoding="utf-8", newline="\n")
    print(len(lines) - len(keep), "relocations removed")


if __name__ == "__main__":
    main()
