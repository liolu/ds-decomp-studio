"""pragsweep.py - sweep every compiler pragma hidden in mwccarm.exe over one function's draft.

    python ../../studio/gametools/prototypes/pragsweep.py NAME FILE.c [--levels "-O4,p -O2 -O3"] [-k 2] [-j 12]
    python ../../studio/gametools/prototypes/pragsweep.py --list          # the pragma names found in the binary

Run from the project dir (projets/<game>). What it does:
  1. reads every `opt_*` name (plus peephole/scheduling/...) out of the game's mwccarm.exe (2.0/sp1p5 has ~70 opt_
     pragmas; earlier sweeps only knew ~40 by hand), keeps the `on`/`off` forms;
  2. single pass: the draft judged with `<base> -O<level> -pragma "<name> <on|off>"` for every level and pragma;
     a pragma that leaves the compiled code identical to the plain level is dropped (no effect on this function);
  3. pair pass (-k 2): every pair of the pragmas that DID change the code, at each level.
Prints the best results (diffs, size, profile); a MATCH is printed as MATCH. Writes build/hunt/pragsweep/NAME.txt.

Why: TnJ s38 rounds found `-pragma "opt_propagation off"` (5th-arg family, 6 functions) and the pair
`opt_dead_assignments off` + `opt_propagation off` (0203e6f8): the original sources had #pragma lines, so a
profile reproduces them. Profiles with -pragma work in compilers.txt (quotes kept by configure.py).
"""
import argparse, itertools, os, re, sys, hashlib
from multiprocessing import Pool
from pathlib import Path

GT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GT))

EXTRA = ["peephole", "scheduling", "global_optimizer", "optimize_for_size", "auto_inline", "inline_bottom_up",
         "dont_inline", "readonly_strings", "pool_strings", "dead_stripping"]


def pragma_names(exe: Path) -> list[str]:
    b = exe.read_bytes()
    s = {m.decode() for m in re.findall(rb"[a-z][a-z0-9_]{3,48}(?=\x00)", b)}
    names = sorted(x for x in s if x.startswith("opt_") and not x.endswith(("_limit", "_count", "_mode")))
    return names + [x for x in EXTRA if x in s]


def _init(name, src):
    global NAME, SRC, hunt
    import hunt as h
    hunt = h
    NAME, SRC = name, src
    hunt._init()


def _judge(prof):
    r = hunt._judge((NAME, SRC, prof))
    d = r.get("diffs")
    sig = hashlib.md5(((r.get("diff") or "") + str(r.get("size"))).encode()).hexdigest()
    return (d if d is not None else 99999, r.get("size"), prof, bool(r.get("match")), sig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--levels", default="-O4,p -O4,s -O3 -O2 -O1")
    ap.add_argument("--base", default="2.0/sp1p5")
    ap.add_argument("-k", type=int, default=2)
    ap.add_argument("-j", type=int, default=12)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    exe = Path("../../tools/mwccarm") / a.base / "mwccarm.exe"
    if not exe.exists():
        exe = Path("../../tools/mwccarm/2.0/sp1p5/mwccarm.exe")
    names = pragma_names(exe)
    if a.list:
        print(len(names), " ".join(names))
        return
    src = Path(a.file).read_text(encoding="utf-8", errors="replace")
    if src.startswith("// profile:"):
        src = src.split("\n", 1)[1]
    levels = a.levels.split()
    plain = [f"{a.base} {lv}" for lv in levels]
    singles = [f"{a.base} {lv} -pragma \"{n} {v}\"" for lv in levels for n in names for v in ("off", "on")]
    out = Path("build/hunt/pragsweep"); out.mkdir(parents=True, exist_ok=True)
    with Pool(a.j, initializer=_init, initargs=(a.name, src)) as pool:
        base_res = {p: r for p, r in zip(plain, pool.map(_judge, plain))}
        res = pool.map(_judge, singles, chunksize=8)
        eff = {}  # level -> pragma args that changed the code at that level
        for r in res:
            lv = r[2].split(" -pragma")[0]
            if r[4] != base_res[lv][4]:
                eff.setdefault(lv, []).append(r[2][len(lv) + 1:])
        pairs = []
        if a.k >= 2:
            for lv, prs in eff.items():
                prs = [p for p in prs if '"' in p]
                for x, y in itertools.combinations(prs, 2):
                    if x.split('"')[1].split()[0] != y.split('"')[1].split()[0]:
                        pairs.append(f"{lv} {x} {y}")
            res += pool.map(_judge, pairs, chunksize=8)
    res += list(base_res.values())
    res.sort(key=lambda r: (r[0], r[2]))
    lines = [f"{d}\t{s}\t{p}" + ("\tMATCH" if m else "") for d, s, p, m, _ in res]
    (out / f"{a.name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{a.name}: {len(singles)} singles, {sum(len(v) for v in eff.values())} with an effect, {len(pairs)} pairs")
    for l in lines[:8]:
        print(" ", l)


if __name__ == "__main__":
    main()
