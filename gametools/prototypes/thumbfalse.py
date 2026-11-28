"""Relocations dsd put on the middle of an ARM word it took for Thumb code: `kind:arm_branch` inside a `function(thumb)`.

mwld answers with Thumb->ARM veneers ($Ven$$func_X, 12 bytes each at the end of .text), so everything after them is
shifted and the ROM cannot be rebuilt (Plants vs Zombies: 4 veneers, +0x30). An ARM branch never starts inside Thumb
code. The owner symbol is no function at all (ARM code cut in the middle, it can start with a conditional branch, so
function(arm) is refused by dsd). Left Thumb, its `$t` mapping also covers the ARM calls that follow it, which get
veneers as well.

Two more cases (The Sims 2 USA, 2026-11-28: +0x3c of veneers before .init): a tiny function(thumb) (size <= 4) that
starts on a word with a `kind:load` relocation is a literal-pool word, not code; a `function(thumb,size=0x0,unknown)`
that no relocation targets, between two ARM functions, is a guess on data (its `$t` turns the ARM code after it Thumb). Both are deleted (symbol only), the word stays in its ARM neighbour.

    python thumbfalse.py [--apply]     # from the game's folder; --apply deletes the relocations and the owner symbol
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import modules  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    total = 0
    # every relocation target of every module (overlays call main): an unknown Thumb guess nobody targets is data
    targets = {int(a, 16) & ~1 for f in modules().values()
               for a in re.findall(r" to:0x([0-9a-f]+)", (f / "relocs.txt").read_text(encoding="utf-8"))}
    for name, folder in modules().items():
        syms = (folder / "symbols.txt").read_text(encoding="utf-8")
        thumb = [(int(a, 16), int(z, 16)) for z, a in re.findall(
            r"kind:function\(thumb,size=0x([0-9a-f]+)\) addr:0x([0-9a-f]+)", syms)]
        path = folder / "relocs.txt"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep, owners = [], set()
        for line in lines:
            m = re.match(r"from:0x([0-9a-f]+) kind:arm_branch", line)
            owner = next((a for a, z in thumb if m and a <= int(m[1], 16) < a + z), None)
            if owner is not None:
                print(name, line.strip())
                owners.add(owner)
                total += 1
                continue
            keep.append(line)
        loads = {int(a, 16) for a in re.findall(r"^from:0x([0-9a-f]+) kind:load", "".join(lines), re.M)}
        for a, z in thumb:
            if 0 < z <= 4 and a in loads:
                print(name, f"thumb {a:08x} size {z:#x} is a pool word (load relocation)")
                owners.add(a); total += 1
        funcs = sorted((int(a, 16), k) for k, a in re.findall(r"kind:function\((arm|thumb)[^)]*\) addr:0x([0-9a-f]+)", syms))
        for a in (int(x, 16) for x in re.findall(r"kind:function\(thumb,size=0x0,unknown\) addr:0x([0-9a-f]+)", syms)):
            i = funcs.index((a, "thumb"))
            between_arm = 0 < i < len(funcs) - 1 and funcs[i - 1][1] == "arm" and funcs[i + 1][1] == "arm"
            if a not in targets and between_arm:  # inside Thumb code such a guess is harmless (Plants vs Zombies)
                print(name, f"thumb {a:08x} unknown, size 0, never targeted")
                owners.add(a); total += 1
        if apply and owners:
            path.write_text("".join(keep), encoding="utf-8", newline="\n")
            for a in owners:
                syms = re.sub(rf"^\S+ kind:function\(thumb,size=0x[0-9a-f]+(?:,unknown)?\) addr:0x{a:08x}\b.*\n", "", syms, flags=re.M)
            (folder / "symbols.txt").write_text(syms, encoding="utf-8", newline="\n")
    print(total, "false relocations / symbols" + (" removed" if apply else ""))


if __name__ == "__main__":
    main()
