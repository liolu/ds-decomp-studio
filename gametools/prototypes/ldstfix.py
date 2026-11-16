"""ldstfix.py - wrong access width/sign: the target loads `ldr` where the draft loads `ldrsb` (m2c typed the pointer).

    cd projets<game>
    python ../../studio/gametools/prototypes/ldstfix.py [-j 8] [--out build/ldstfix] [names... | @file]
    python ../../studio/gametools/workbench.py submit-many build/ldstfix

For every instruction pair of the blockmap diff where only the load/store width or sign differs
(ldr/ldrh/ldrsh/ldrb/ldrsb/str/strh/strb), the pointer type the target needs is known:
    ldr/str -> s32 / u32,  ldrh -> u16,  ldrsh -> s16,  strh -> s16 / u16,  ldrb -> u8,  ldrsb -> s8,  strb -> s8 / u8
Each occurrence of the draft's type in a pointer cast (`(s8 *)`, `M2C_FIELD(x, s8 *, n)`, a local `s8 *p;`) is
replaced by the wanted type, one occurrence at a time, then all of them; every candidate is judged, the best kept,
and the pass repeats while it gets closer (up to 4 rounds). Found 2026-11-16 on Spyro (blockmap class `ldst`,
`*(s8 *)(a + i)` read as a word: `ldr r1, [r0, r1]` vs `ldrsb`).
Runs on blockmap classes ldst and mixed (only the functions whose diff has at least one ldst pair).
"""
import argparse
import json
import os
import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

WANT = {"ldr": ["s32", "u32", "void *", "M2C_UNK"], "str": ["s32", "u32", "M2C_UNK"], "ldrh": ["u16"], "ldrsh": ["s16"],
        "strh": ["s16", "u16"], "ldrb": ["u8"], "ldrsb": ["s8"], "strb": ["s8", "u8"]}
HAVE = {"ldr": ["s32", "u32", "M2C_UNK"], "str": ["s32", "u32", "M2C_UNK"], "ldrh": ["u16"], "ldrsh": ["s16"],
        "strh": ["s16", "u16"], "ldrb": ["u8", "char"], "ldrsb": ["s8"], "strb": ["s8", "u8"]}
OP = re.compile(r"^(ldr|str)(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?(sb|sh|b|h)?\b")


def width(ins: str) -> str | None:
    m = OP.match(ins.strip())
    return (m.group(1) + (m.group(2) or "")) if m else None


def type_pairs(t: list[str], c: list[str]) -> list[tuple[str, str]]:
    """(type in the draft, type wanted) for every width-only difference."""
    out = []
    for a, b in zip(t, c):
        wa, wb = width(a), width(b)
        if wa and wb and wa != wb:
            for have in HAVE.get(wb, []):
                for want in WANT.get(wa, []):
                    if have != want:
                        out.append((have, want))
    return list(dict.fromkeys(out))


def variants(src: str, have: str, want: str):
    pat = re.compile(rf"\b{re.escape(have)}(\s*\*)")
    spots = [m for m in pat.finditer(src)]
    for m in spots:
        yield src[:m.start()] + want + m.group(1) + src[m.end():]
    if len(spots) > 1:
        yield pat.sub(lambda m: want + m.group(1), src)


wbm = None
cur = None


def init():
    global wbm
    import blockmap
    blockmap.idle()
    import workbench
    workbench.MISS_SOURCE = "ldstfix"
    os.environ["WB_FULL"] = "1"
    wbm = workbench


def judge(name, src, prof):
    r = wbm.judge(name, src, prof)
    rk = {"match": 0, "near": 1, "size": 2, "compile": 3, "refused": 4}[r["status"]]
    return (rk, r.get("diffs", 10**6)), r


def one(job):
    global cur
    name, prof, draft, out = job
    try:
        ov = wbm.overlay_index().get(name)
        mod = "main" if ov is None else ("itcm" if ov < 0 else f"ov{ov:03d}")
        if mod != cur:
            wbm.select_module(name)
            cur = mod
        f = wbm.function(name)
        src = Path(draft).read_text(encoding="utf-8") if draft and Path(draft).is_file() else wbm.starting_draft(name)[0]
        if not src:
            return name, None
        best_k, r = judge(name, src, prof)
        steps = 0
        for _ in range(4):
            full = r.get("full") or {}
            pairs = type_pairs(full.get("t", []), full.get("c", []))
            if not pairs or best_k[0] == 0:
                break
            improved = None
            for have, want in pairs:
                for v in variants(src, have, want):
                    k, rr = judge(name, v, prof)
                    if k < best_k and (improved is None or k < improved[0]):
                        improved = (k, v, rr)
                    if k[0] == 0:
                        break
                if improved and improved[0][0] == 0:
                    break
            if not improved:
                break
            best_k, src, r = improved
            steps += 1
        if steps == 0:
            return name, None
        (out / f"{name}.c").write_text(src, encoding="utf-8", newline="\n")
        st = r["status"]
        return name, {"size": f["size"], "status": st, "match": st == "match", "profile": prof,
                      "k": [0 if st == "match" else 1, r.get("diffs", 999)], "steps": steps,
                      "mt": os.path.getmtime(out / f"{name}.c")}
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return name, {"status": "error", "match": False, "k": [1, 9999], "mt": 0, "err": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=8)
    ap.add_argument("--out", default="build/ldstfix")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    bm = json.loads(Path("build/blockmap/blockmap.json").read_text(encoding="utf-8"))
    names = [m for n in a.names for m in (open(n[1:], encoding="utf-8").read().split() if n.startswith("@") else [n])]
    if not names:
        names = [n for n, r in bm.items() if r.get("asm") and r.get("class") in ("ldst", "mixed", "short", "long", "frame")
                 and type_pairs(r["asm"]["t"], r["asm"]["c"])]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    resf = out / "results.json"
    res = json.loads(resf.read_text(encoding="utf-8")) if resf.exists() else {}
    jobs = [(n, bm[n].get("profile") or "2.0/sp1p5", bm[n].get("draft"), out) for n in sorted(names) if n not in res]
    print(len(jobs), "functions with a width/sign difference", flush=True)
    t0 = time.time()
    with Pool(a.j, initializer=init, maxtasksperchild=40) as pool:
        for n, r in pool.imap_unordered(one, jobs, chunksize=1):
            if r is None:
                continue
            res[n] = r
            print(n, r["status"], r.get("k"), flush=True)
            resf.write_text(json.dumps(res, indent=1), encoding="utf-8")
    import collections
    print(f"{time.time() - t0:.0f}s", dict(collections.Counter(r["status"] for r in res.values())),
          "matches:", sum(1 for r in res.values() if r.get("match")))


if __name__ == "__main__":
    main()
