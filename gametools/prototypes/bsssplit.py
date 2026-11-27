"""bsssplit.py GAP.json [--dry-run] : cover the .bss ranges that bssgen leaves (symbols at odd / 2-byte addresses inside a
block, e.g. data_020714f5) with ONE C file per symbol, typed by its alignment: u32[] when address and size are multiples
of 4, u16[] for 2, else `struct { u8 b[N]; }` (alignment 1; a plain u8[] becomes a common symbol and loses its place).
Why one file per object: mwcc sorts the .bss objects of one file (smallest first), so two objects in one file do not
keep the address order. GAP.json = `datagap.py --json` output; only .bss ranges starting on a symbol are handled.
Appends the delinks entries; run `configure.py` + `match.py verify` after. tools/ld_align.py lowers the alignment of
the objects whose range starts off 4.
Technique id: bss-split. Origin: TnJ s34 (2026-10-29)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402,F401
from bssgen import modules  # noqa: E402


def declaration(name: str, s: int, size: int) -> str:
    if s % 4 == 0 and size % 4 == 0:
        return f"u32 {name}[{size // 4}];\n"
    if s % 2 == 0 and size % 2 == 0:
        return f"u16 {name}[{size // 2}];\n"
    return f"typedef struct {{\n    u8 b[{size}];\n}} {name}_t;\n{name}_t {name};\n"


def main():
    a = sys.argv[1:]
    dry = "--dry-run" in a
    gaps = json.loads(Path(a[0]).read_text())
    for mod, folder in modules().items():
        syms = {}
        for line in open(folder / "symbols.txt", encoding="utf-8"):
            m = re.match(r"(\S+) kind:bss\S* addr:0x([0-9a-f]+)", line)
            if m:
                syms.setdefault(int(m.group(2), 16), []).append(m.group(1))
        blocks = []
        for g in gaps:
            if g["mod"] != mod or g["sec"] != ".bss" or g["start"] not in syms:
                continue
            cuts = sorted(k for k in syms if g["start"] <= k < g["end"]) + [g["end"]]
            for s, e in zip(cuts, cuts[1:]):
                if len(syms[s]) > 1:  # alias labels: C cannot define both names
                    continue
                name, size = syms[s][0], e - s
                path = f"src/data/{mod}_bss_{s:08x}.c"
                if Path(path).exists():
                    print("exists, skipped:", path)
                    continue
                print(f"{path}: {size} bytes")
                if not dry:
                    Path(path).write_text(f'/* compiler: 2.0/sp1p5 */\n#include "m2c.h"\n\n{declaration(name, s, size)}',
                                          encoding="utf-8", newline="\n")
                blocks.append(f"{path}:\n    complete\n    .bss        start:0x{s:08x} end:0x{e:08x}\n")
        if not dry and blocks:
            p = folder / "delinks.txt"
            p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(blocks), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
