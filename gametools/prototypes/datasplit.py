"""datasplit.py GAP.json [--dry-run] : the .data / .rodata counterpart of bsssplit: ONE C file per symbol for the ranges
datagen leaves or cannot order (odd or halfword symbols inside a block, equal-size scalars that mwcc/mwld reorder).

Every object is an array of bytes, halfwords or words in its own file, so nothing can be reordered; tools/ld_align.py
lowers the section alignment of the files whose range starts off 4. A symbol with a pointer goes through
datagen.declare (only words at 4-aligned addresses); what it refuses stays in the gap.
GAP.json = `datagap.py --json` output. Appends the delinks entries; run `configure.py` + `match.py verify` after.
Technique id: data-split. Origin: Fairy Tail Madoushi (2026-10-30).
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import modules  # noqa: E402
from datagen import Mod, declare, load_symbols, module_key  # noqa: E402


def plain(n: str, raw: bytes, ad: int, const: str) -> str:
    pre = "" if const or any(raw) else "#pragma explicit_zero_data on\n"
    size = len(raw)
    if ad % 4 == 0 and size % 4 == 0:
        words = ", ".join(f"0x{w:08X}" for w, in struct.iter_unpack("<I", raw))
        return f"{pre}{const}u32 {n}[{size // 4}] = {{{words}}};"
    if ad % 2 == 0 and size % 2 == 0:
        halves = ", ".join(f"0x{h:04X}" for h, in struct.iter_unpack("<H", raw))
        return f"{pre}{const}u16 {n}[{size // 2}] = {{{halves}}};"
    return f"{pre}{const}u8 {n}[{size}] = {{" + ", ".join(f"0x{c:02X}" for c in raw) + "};"


def main() -> None:
    dry = "--dry-run" in sys.argv
    gaps = json.loads(Path(sys.argv[1]).read_text())
    mods = modules()
    targets = {module_key(n): load_symbols(f) for n, f in mods.items()}
    files = skipped = 0
    for name, folder in mods.items():
        m = Mod(name, folder, targets)
        blocks = []
        for g in gaps:
            sec = g["sec"]
            if g["mod"] != name or sec not in (".data", ".rodata"):
                continue
            syms = sorted({(a, n) for a, n, k in m.symbols if g["start"] <= a < g["end"] and k == "data"})
            bounds = sorted({a for a, _n, _k in m.symbols if g["start"] < a < g["end"]} | {g["end"]})
            if [a for a, _n in syms].count(g["start"]) != 1:
                skipped += 1
                continue
            for ad, n in syms:
                if [a for a, _x in syms].count(ad) > 1:
                    skipped += 1
                    continue
                end = next(b for b in bounds if b > ad)
                raw = m.bin[ad - m.base:end - m.base]
                const = "const " if sec == ".rodata" else ""
                ext = set()
                if any(ad <= f < end for f in m.relocs):
                    decl, ext = declare(None, m, targets, ad, n, end - ad, sec)
                    if decl is None:
                        skipped += 1
                        continue
                else:
                    decl = plain(n, raw, ad, const)
                rel = f"src/data/{name}_{sec.strip('.')}_{ad:08x}.c"
                if Path(rel).exists():
                    continue
                files += 1
                blocks.append(f"{rel}:\n    complete\n    {sec:<11} start:0x{ad:08x} end:0x{end:08x}\n")
                if not dry:
                    head = '/* compiler: 2.0/sp1p5 */\n#include "m2c.h"\n\n'
                    head += "".join(f"extern u8 {x}[];\n" for x in sorted(ext - {n}))
                    Path(rel).write_text(head + decl + "\n", encoding="utf-8", newline="\n")
        if blocks and not dry:
            d = folder / "delinks.txt"
            d.write_text(d.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(blocks), encoding="utf-8", newline="\n")
    print(files, "files,", skipped, "symbols left to the gap")


if __name__ == "__main__":
    main()
