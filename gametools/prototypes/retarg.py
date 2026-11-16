"""retarg.py - `void f(T *arg0)` drafts whose target returns its first argument (C++ constructors returning `this`).

    cd projets/<game>
    python ../../studio/gametools/prototypes/retarg.py [-j 8] [--out build/retarg] [--all] [names... | @file]
    python ../../studio/gametools/workbench.py submit-many build/retarg

Found 2026-11-16 on Spyro (blockmap.py class `reg`, 2 register diffs): the target puts a constant in r2 although
r0 (arg0) is dead in the draft:  `*arg0 = &vtable; g = 0;` -> target `mov r2, #0; str r2, [r1]`, draft `mov r0, #0`.
r0 is kept because the original returns arg0 (`Foo *Foo_ctor(Foo *this) { ...; return this; }`). permrand (local
declaration orders) never fixes it: 0 of 36 `reg` functions.

Detector (target listing): the function never writes r0 after its entry other than `mov r0, rN` right before the
return, or it moves r0 into a callee-saved register and back before returning. Every void draft that passes gets
`return arg0;` (return type = the type of arg0), judged on its blockmap profile and the prior's next ones.
Without --all only blockmap classes reg / regsched / mixed / short / long / frame are tried.
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

CLASSES = {"reg", "regsched", "mixed", "short", "long", "frame", "sched", "loop", "calls"}
DEST = re.compile(r"^\s*(?!str|cmp|cmn|tst|teq|b\b|bl|bx|push|stm)(\w+)\s+(r\d+|ip|lr|sp)\b")


def keeps_r0(asm: list[str]) -> bool:
    """r0 holds arg0 again when the function returns."""
    body = [l.split("@")[0].split(";")[0].strip() for l in asm]
    ret = [i for i, l in enumerate(body) if l.startswith(("bx lr", "pop", "ldmfd", "ldmia sp!")) and ("pc" in l or l.startswith("bx"))]
    if not ret:
        return False
    saved = None
    for i, l in enumerate(body[:ret[-1]]):
        m = re.match(r"mov\s+(r[4-9]|r1[01]), r0$", l)
        if m and saved is None:
            saved = m.group(1)
            continue
        d = DEST.match(l)
        if (d and d.group(2) == "r0") or re.match(r"(ldm|pop).*\br0\b", l) or l.startswith("bl"):
            if l.startswith("bl"):
                if saved is None:
                    return False
                continue
            if saved and re.match(rf"mov\s+r0, {saved}$", l):
                continue
            return False
    return True


def with_return(src: str, name: str) -> str | None:
    m = re.search(rf"^(?:static\s+)?void\s+{re.escape(name)}\s*\(\s*([^,)]*?)\s*\barg0\b([^)]*)\)\s*\{{", src, re.M)
    if not m:
        return None
    t = m.group(1).strip() or "s32"
    head = f"{t} {name}({m.group(1)}arg0{m.group(2)}) {{".replace(f"{t}  ", f"{t} ")
    s = src[:m.start()] + head + src[m.end():]
    # the last closing brace of the function: insert the return before it
    start = s.index(head) + len(head)
    depth, i = 1, start
    while i < len(s) and depth:
        depth += {"{": 1, "}": -1}.get(s[i], 0)
        i += 1
    if depth:
        return None
    end = i - 1
    body = s[start:end]
    body = re.sub(r"\breturn\s*;", "return arg0;", body)
    return s[:start] + body.rstrip() + "\n    return arg0;\n" + s[end:]


wbm = None
cur = None


def init():
    global wbm
    import blockmap
    blockmap.idle()
    import workbench
    workbench.MISS_SOURCE = "retarg"
    wbm = workbench


def one(job):
    global cur
    name, out = job
    try:
        ov = wbm.overlay_index().get(name)
        mod = "main" if ov is None else ("itcm" if ov < 0 else f"ov{ov:03d}")
        if mod != cur:
            wbm.select_module(name)
            cur = mod
        f = wbm.function(name)
        if wbm.covered(f["addr"]) or f["mode"] == "thumb":
            return name, None
        asm = [l.strip() for l in (wbm.am.function_asm(name) or "").splitlines()[1:-1] if l.strip() and not l.strip().endswith(":")]
        if not keeps_r0(asm):
            return name, None
        src = None
        for p in (Path("build/errfix") / f"{name}.c",):
            if p.exists():
                src = p.read_text(encoding="utf-8")
        if src is None:
            src, _ = wbm.starting_draft(name)
        new = with_return(src or "", name)
        if not new:
            return name, None
        best = None
        for p in [f"{v} {e}".strip() for v, e in wbm.am.profiles_for(name, f["size"], f["addr"])][:3]:
            r = wbm.judge(name, new, p)
            rk = {"match": 0, "near": 1, "size": 2, "compile": 3, "refused": 4}
            if best is None or (rk[r["status"]], r.get("diffs", 0)) < (rk[best["status"]], best.get("diffs", 0)):
                best = dict(r, profile=p)
            if r["status"] == "match":
                break
        (out / f"{name}.c").write_text(new, encoding="utf-8", newline="\n")
        st = best["status"]
        return name, {"size": f["size"], "status": st, "match": st == "match", "profile": best["profile"],
                      "k": [0 if st == "match" else 1, best.get("diffs", 999)], "mt": os.path.getmtime(out / f"{name}.c")}
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return name, {"status": "error", "match": False, "k": [1, 9999], "mt": 0, "err": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=8)
    ap.add_argument("--out", default="build/retarg")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    names = [m for n in a.names for m in (open(n[1:], encoding="utf-8").read().split() if n.startswith("@") else [n])]
    if not names:
        bm = json.loads(Path("build/blockmap/blockmap.json").read_text(encoding="utf-8"))
        names = [n for n, r in bm.items() if r.get("status") not in ("matched", "match")
                 and (a.all or r.get("class") in CLASSES or str(r.get("class")).startswith("err:"))]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    resf = out / "results.json"
    res = json.loads(resf.read_text(encoding="utf-8")) if resf.exists() else {}
    todo = [(n, out) for n in sorted(names) if n not in res]
    print(len(todo), "functions", flush=True)
    t0, done, tried = time.time(), 0, 0
    with Pool(a.j, initializer=init, maxtasksperchild=40) as pool:
        for n, r in pool.imap_unordered(one, todo, chunksize=2):
            done += 1
            if r is None:
                continue
            tried += 1
            res[n] = r
            if r.get("match"):
                print("MATCH", n, r["profile"], flush=True)
            resf.write_text(json.dumps(res, indent=1), encoding="utf-8")
    import collections
    print(f"{tried} keep r0 and were tried in {time.time() - t0:.0f}s:", dict(collections.Counter(r["status"] for r in res.values())))


if __name__ == "__main__":
    main()
