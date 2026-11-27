"""After fakeptr/symmerge removed symbols: every `kind:load` relocation left pointing at an address that has no symbol.

dsd delink stops at the first one, per run: delink_fix.py needs one build per relocation and gives up after 20 rounds
(Fairy Tail: 68 and 241 overlays). This fixes them all at once, the way dsd suggests: `to:<previous symbol> add:<offset>`
(a Thumb function pointer, address + 1, becomes `to:<function>`: the linker sets the bit).

    python orphanfix.py [--apply]      # from the game's folder
"""
import bisect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import modules  # noqa: E402
from datagen import module_key  # noqa: E402

REL = re.compile(r"^(from:0x[0-9a-f]+ kind:load )to:0x([0-9a-f]+)( module:(\S+))(.*)$")


def main() -> None:
    apply = "--apply" in sys.argv
    mods = modules()
    syms, funcs = {}, {}
    for name, folder in mods.items():
        text = (folder / "symbols.txt").read_text(encoding="utf-8")
        syms[module_key(name)] = sorted({int(a, 16) for a in re.findall(r" addr:0x([0-9a-f]+)", text)})
        funcs[module_key(name)] = {int(a, 16) for a in re.findall(r"kind:function\S* addr:0x([0-9a-f]+)", text)}
    total = 0
    for name, folder in mods.items():
        path = folder / "relocs.txt"
        lines = path.read_text(encoding="utf-8").split("\n")
        changed = 0
        for i, line in enumerate(lines):
            m = REL.match(line)
            if not m:
                continue
            to, mod = int(m[2], 16), m[4]
            many = re.fullmatch(r"overlays\(([\d,]+)\)", mod)
            first = f"overlay({many[1].split(',')[0]})" if many else mod
            table = syms.get(first)
            if not table:
                continue
            k = bisect.bisect_right(table, to) - 1
            if k < 0 or table[k] == to:
                continue
            base = table[k]
            if to == base + 1 and base in funcs[first]:
                lines[i] = f"{m[1]}to:0x{base:08x}{m[3]}{m[5]}"
            else:
                lines[i] = f"{m[1]}to:0x{base:08x} add:0x{to - base:x}{m[3]}{m[5]}"
            changed += 1
        total += changed
        if apply and changed:
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(total, "relocations" + (" rewritten" if apply else " to rewrite"))


if __name__ == "__main__":
    main()
