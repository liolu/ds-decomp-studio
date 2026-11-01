"""fieldgap.py [--dry-run] [--mods main,ov004] [--sections .data,.rodata,.bss] [--with-profile]: the last data holes,
the ones whose interior symbols (struct fields named by matched C, odd 1-byte labels, alias labels) stop datagen,
bssgen, symmerge and datasplit.

Each hole becomes ONE object of exact bytes (src/data/<module>_<sec>_<addr>.c); a hole with pointers is cut at its
4-aligned bounds, the pointers go in a u32 table. The interior symbols stay in symbols.txt, so matched C and the
delinked target keep their names, and get their address in config/<version>/arm9/lcf_symbols.txt (tools/ld_align.py
puts those lines in the lcf). tools/ld_align.py lowers the alignment of the files that start off 4.
`--sections .ctor,.exceptix,.exception` gives the C++ tables to C too (define_section + __declspec, see table_decl).
Run `configure.py` + `match.py verify` after. Technique id: field-gap. Origin: Resident Evil DS (2026-11-01).
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project  # noqa: E402
from bssgen import SECTION, modules  # noqa: E402
from datagap import holes  # noqa: E402
from datagen import Mod, declare, load_symbols, module_key  # noqa: E402
from datasplit import plain  # noqa: E402

ROOT = project.ROOT
TABLES = (".ctor", ".exceptix", ".exception")


def obj_name(mod: str, ad: int) -> str:
    tag = "" if mod in ("main", "itcm", "dtcm") else f"{mod}_"
    return f"data_{tag}{ad:08x}"


def table_decl(sec: str, decl: str) -> str:
    """A C++ table in its own section. `RW` is what makes it a data section for objdiff: without it mwcc marks the
    section executable and objdiff does not compare it with the target's (read-only) one."""
    decl = re.sub(r"^(u32|u16|u8|char) ", r"__declspec(TABLE) \1 ", decl, flags=re.M)
    return f'#pragma define_section TABLE "{sec}" "{sec}" RW\n{decl}'


def pieces(m: Mod, s: int, e: int, sec: str = "") -> list[tuple[int, int]]:
    """An object with pointers must be a u32 table, so it starts and ends 4-aligned; the bytes around it go apart.
    Each .ctor entry gets its own file: it belongs to one __sinit_ function, which can then be matched later."""
    if sec == ".ctor":
        return [(x, min(x + 4, e)) for x in range(s, e, 4)]
    if sec == ".bss":  # objdiff compares .bss symbol by symbol, so one object per symbol
        cuts = sorted({s, e} | {ad for ad, _n, k in m.symbols if s < ad < e and k != "function"})
        return list(zip(cuts, cuts[1:]))
    if not any(s <= f < e for f in m.relocs):
        return [(s, e)]
    a, b = (s + 3) & ~3, e & ~3
    return [(x, y) for x, y in ((s, a), (a, b), (b, e)) if x < y]


def name_exception_labels(name: str, folder: Path, sections: list[str]) -> None:
    """dsd's `@ET@x` labels are no C names, but .exceptix points to them: they get a C name, not dropped like .p__sinit_."""
    head = (folder / "delinks.txt").read_text(encoding="utf-8").partition("\n\n")[0]
    spans = [(int(x, 16), int(y, 16)) for sec in sections if sec in (".exceptix", ".exception")
             for x, y in re.findall(rf"{re.escape(sec)}\s+start:0x(\w+) end:0x(\w+)", head)]
    if not spans:
        return
    p = folder / "symbols.txt"
    lines = p.read_text(encoding="utf-8").splitlines(True)
    seen, out = {x.split(" ", 1)[0] for x in lines}, []
    for x in lines:
        m = re.match(r"(\S+) (.*addr:0x(\w+).*)", x, re.S)
        ad = int(m[3], 16) if m else 0
        if m and not re.fullmatch(r"\w+", m[1]) and any(s <= ad < e for s, e in spans):
            n = obj_name(name, ad)
            if n in seen:  # two labels on one address (or a C name already there): one is enough
                continue
            seen.add(n)
            x = f"{n} {m[2]}"
        out.append(x)
    p.write_text("".join(out), encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mods", default="")
    ap.add_argument("--sections", default=".data,.rodata,.bss")
    ap.add_argument("--with-profile", action="store_true", help="also take holes holding a -profile record")
    a = ap.parse_args()
    mods = modules()
    if not a.dry_run:
        for name, folder in mods.items():
            name_exception_labels(name, folder, a.sections.split(","))
    targets = {module_key(n): load_symbols(f) for n, f in mods.items()}
    pj = ROOT / "build" / "profnames.json"
    prof = [tuple(v.get("rec", (0, 0))[:2]) for v in json.loads(pj.read_text(encoding="utf-8")).values()] \
        if pj.exists() else []
    want = set(a.mods.split(",")) if a.mods else None
    lcf, files, nbytes, left = {}, 0, 0, 0
    for name, folder in mods.items():
        if want and name not in want:
            continue
        m = Mod(name, folder, targets)
        body = (folder / "delinks.txt").read_text(encoding="utf-8").partition("\n\n")[2]
        blocks, new_syms, drop_syms = [], [], set()
        for sec in a.sections.split(","):
            if sec not in m.sections:
                continue
            start, end = m.sections[sec]
            taken = [(int(x, 16), int(y, 16)) for sc, x, y in SECTION.findall(body) if sc == sec]
            for hs, he in holes(start, end, taken):
                if not a.with_profile and any(hs < pe and ps < he for ps, pe in prof):
                    left += he - hs
                    continue
                inside = [(ad, n) for ad, n, k in m.symbols if hs <= ad < he and k != "function"]
                # dsd's `.p__sinit_X` (the .ctor entry) is no C name and neither C nor the lcf can define it: dropped
                bad = {n for _ad, n in inside if not re.fullmatch(r"\w+", n)}
                inside = [(ad, n) for ad, n in inside if n not in bad]
                drop_syms |= bad
                cut = pieces(m, hs, he, sec)
                # first see that every piece can be written: a hole is taken whole or not at all
                out = []
                for s, e in cut:
                    at_start = [n for ad, n in inside if ad == s]
                    n = at_start[0] if at_start else obj_name(name, s)
                    if sec == ".bss":
                        decl, ext = (f"u32 {n}[{(e - s) // 4}];" if s % 4 == 0 and (e - s) % 4 == 0 else f"u8 {n}[{e - s}];"), set()
                    elif any(s <= f < e for f in m.relocs):
                        decl, ext = declare(None, m, targets, s, n, e - s, ".data" if sec in TABLES else sec)
                    else:
                        decl, ext = plain(n, m.bin[s - m.base:e - m.base], s, "const " if sec == ".rodata" else ""), set()
                    if decl is None:
                        out = None
                        break
                    if sec in TABLES:
                        decl = table_decl(sec, decl)
                    out.append((s, e, n, decl, ext, at_start))
                if out is None:
                    left += he - hs
                    print(f"left: {name} {sec} 0x{hs:08x}-0x{he:08x} (pointer not writable)")
                    continue
                for s, e, n, decl, ext, at_start in out:
                    if not at_start:
                        new_syms.append(f"{n} kind:{'bss' if sec == '.bss' else 'data(any)'} addr:0x{s:08x}\n")
                    for ad, x in inside:
                        if s <= ad < e and x != n:
                            lcf[x] = ad
                    rel = f"src/data/{name}_{sec.strip('.')}_{s:08x}.c"
                    blocks.append(f"{rel}:\n    complete\n    {sec:<11} start:0x{s:08x} end:0x{e:08x}\n")
                    files += 1
                    nbytes += e - s
                    if not a.dry_run:
                        head = '/* compiler: 2.0/sp1p5 */\n#include "m2c.h"\n\n'
                        head += "".join(f"extern u8 {x}[];\n" for x in sorted(ext - {n}))
                        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
                        (ROOT / rel).write_text(head + decl + "\n", encoding="utf-8", newline="\n")
        if a.dry_run:
            continue
        if blocks:
            d = folder / "delinks.txt"
            d.write_text(d.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(blocks), encoding="utf-8", newline="\n")
        if new_syms or drop_syms:
            p = folder / "symbols.txt"
            kept = [x for x in p.read_text(encoding="utf-8").splitlines(True) if x.split(" ", 1)[0] not in drop_syms]
            p.write_text("".join(kept).rstrip("\n") + "\n" + "".join(new_syms), encoding="utf-8", newline="\n")
    print(f"{files} files, {nbytes} bytes, {len(lcf)} interior symbols for the lcf, {left} bytes left")
    if a.dry_run or not lcf:
        return
    sf = mods["main"] / "lcf_symbols.txt"
    old = sf.read_text(encoding="utf-8").splitlines() if sf.exists() else []
    have = {re.split(r"\s*=", x.strip())[0] for x in old}
    add = [f"{n} = 0x{ad:08x};" for n, ad in sorted(lcf.items(), key=lambda kv: kv[1]) if n not in have]
    sf.write_text("\n".join(old + add) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
