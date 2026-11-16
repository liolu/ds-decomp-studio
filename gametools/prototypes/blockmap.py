"""blockmap.py - for every function of ONE game: how it was solved (matched) or which parameter blocks it (unmatched).

    cd projets/<game>
    python ../../studio/gametools/prototypes/blockmap.py scan [-j 10] [--min 4 --max 1500] [names...]
    python ../../studio/gametools/prototypes/blockmap.py show [CLASS]      # summary, or the functions of one class
    python ../../studio/gametools/prototypes/blockmap.py list CLASS        # names only (feed to a tool: @file)

Every unmatched function is judged ONCE with its best starting draft (build/auto/near, drafts, qwen memory: same as
workbench.starting_draft) on the first two profiles of auto_match.profiles_for (the prior), and the diff is
classified into one "parameter" that blocks it. One class = one tool to run (see TOOLS below).

near (same size) classes, from the instruction listings (bl targets and literal pools masked like the judge):
  reg        only register numbers differ              -> regalloc: declperm / declclimb / regswap
  sched      same instructions, other order            -> statement order: stmtperm / schedscan
  regsched   same instructions modulo registers, order -> both
  imm        only immediates/offsets differ            -> constants, struct offsets, element size: immfix
  cond       only condition codes differ (lt/lo..)     -> signedness: signfix
  ldst       ldrb/ldrsb/ldrh/ldrsh/str width or sign   -> variable/field type: signfix
  swap       commutative operands swapped              -> operand order: hunt battery (cmp-swap) / opswap
  mixed      several of the above / opcodes            -> by hand / permuter
size classes (candidate size != target):
  frame      push/pop register list or stack size differs (callee-saved count, locals) -> framefix (dead temps)
  calls      number of bl differs (inline vs call, missing call)  -> callfix
  loop       backward branch count differs (loop form, unroll)    -> hunt loop forms
  short/long only a few instructions more/less                    -> by hand / permuter
compile classes: one per compiler error kind (undeclared, m2c leftovers, pointer arith on void...) -> errfix

Matched functions get their method from git (the commit that added their file: auto_match / clone_match / donor /
hand) and their profile from config/<v>/compilers.txt.

Writes build/blockmap/blockmap.json  {name: {size, status, class, profile, diffs, detail}}  and blockmap.tsv.
"""
import argparse
import collections
import gzip
import json
import os
import re
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
OUT = Path("build/blockmap")

TOOLS = {
    "reg": "declperm.py / declclimb.py / regswap.py (local declaration order, temps)",
    "sched": "stmtperm.py / schedscan.py (statement order)",
    "regsched": "declperm + stmtperm",
    "imm": "immfix.py (constant / offset / element size)",
    "cond": "signfix.py (signed <-> unsigned)",
    "ldst": "signfix.py (u8/s8/u16/s16/int types of locals, fields, casts)",
    "swap": "opswap.py (operand order of + * & | ^ ==)",
    "mixed": "by hand, permuter",
    "frame": "framefix.py (callee-saved count: temps, dead stores, volatile)",
    "calls": "callfix.py (inline function vs call, missing/extra call)",
    "loop": "hunt.py loop forms (for/while/do, unrolled)",
    "short": "by hand (candidate shorter)",
    "long": "by hand (candidate longer)",
    "nodraft": "m2c failed: ghidra_draft.py",
    "match": "already matches: workbench.py submit-many (+ __sinit_ in .init since 2026-11-16)",
    "pool": "relcheck.py (literal pool order)",
    "error": "tool error",
}

REG = r"\b(r1[0-5]|r[0-9]|sb|sl|fp|ip|sp|lr|pc)\b"
COND = "eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le"


# ------------------------------------------------------------------ classification of one diff
def _split(ins: str):
    m, _, ops = ins.partition(" ")
    return m.strip(), ops.strip()


def _norm_reg(ins: str) -> str:
    return re.sub(REG, "R", ins)


def _norm_imm(ins: str) -> str:
    s = re.sub(r"#-?(0x[0-9a-f]+|\d+)", "#I", ins)
    return re.sub(r"\b[0-9a-f]{6,8}\b", "A", s)  # branch targets (b/bl absolute addresses)


def _mask(lines: list[str]) -> list[str]:
    """bl targets differ by link; branch targets are kept (they say where the code flows)."""
    out = []
    for l in lines:
        m, ops = _split(l)
        if m.startswith("bl") and m not in ("bls", "blt", "ble", "blo"):  # bl/blx with or without cond
            out.append(m.rstrip("x") + " F")
        else:
            out.append(l)
    return out


def _cond_strip(m: str) -> str:
    return re.sub(f"({COND})(?=(b|h|sb|sh|s)?$)", "", m)


LDST_FAM = re.compile(r"^(ldr|str)(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?(b|h|sb|sh|d)?$")


def pair_kind(t: str, c: str) -> str:
    if t == c:
        return "same"
    tm, to = _split(t)
    cm, co = _split(c)
    if tm == cm and _norm_reg(to) == _norm_reg(co):
        return "reg"
    if tm == cm and _norm_imm(to) == _norm_imm(co):
        return "imm"
    if tm == cm and to != co:
        a, b = [x.strip() for x in to.split(",")], [x.strip() for x in co.split(",")]
        if len(a) == len(b) == 3 and a[0] == b[0] and a[1:] == b[2:0:-1]:
            return "swap"
        if len(a) == len(b) == 2 and tm.startswith(("cmp", "tst", "teq", "cmn")) and a == b[::-1]:
            return "swap"
    if tm != cm and to == co:
        if _cond_strip(tm) == _cond_strip(cm):
            return "cond"
        if LDST_FAM.match(tm) and LDST_FAM.match(cm):
            return "ldst"
    if tm != cm and _norm_reg(to) == _norm_reg(co) and LDST_FAM.match(tm) and LDST_FAM.match(cm):
        return "ldst"
    return "other"


def classify_near(t: list[str], c: list[str]) -> tuple[str, dict]:
    t, c = _mask(t), _mask(c)
    kinds = collections.Counter(pair_kind(a, b) for a, b in zip(t, c))
    kinds.pop("same", None)
    detail = dict(kinds)
    if not kinds:
        return "pool", detail  # only masked words differ in text (pool / relocation): relcheck
    if collections.Counter(t) == collections.Counter(c):
        return "sched", detail
    only = set(kinds)
    if only == {"reg"}:
        return "reg", detail
    if collections.Counter(map(_norm_reg, t)) == collections.Counter(map(_norm_reg, c)):
        return "regsched", detail
    for k in ("imm", "cond", "ldst", "swap"):
        if only <= {k, "reg"} and kinds[k]:
            return k, detail
    return "mixed", detail


def _frame(lines: list[str]) -> tuple[str, str]:
    push = next((l for l in lines[:4] if l.startswith(("push", "stmdb sp!", "stmfd"))), "")
    sub = next((l for l in lines[:6] if l.startswith("sub") and "sp, sp" in l), "")
    return push, sub


def _backbranches(lines: list[str], addr: int) -> int:
    n = 0
    for i, l in enumerate(lines):
        m, ops = _split(l)
        if re.match(rf"^b({COND})?$", m):
            mm = re.match(r"([0-9a-f]+)", ops)
            if mm and int(mm.group(1), 16) <= addr + 4 * i:
                n += 1
    return n


def classify_size(t: list[str], c: list[str], addr: int) -> tuple[str, dict]:
    d = {"t": len(t), "c": len(c)}
    if _frame(t)[0] != _frame(c)[0] or _frame(t)[1] != _frame(c)[1]:
        d["push"] = [_frame(t)[0], _frame(c)[0]]
        d["sub"] = [_frame(t)[1], _frame(c)[1]]
        return "frame", d
    bl = lambda L: sum(1 for l in L if _split(l)[0] in ("bl", "blx"))  # noqa: E731
    if bl(t) != bl(c):
        d["bl"] = [bl(t), bl(c)]
        return "calls", d
    if _backbranches(t, addr) != _backbranches(c, addr):
        d["loops"] = [_backbranches(t, addr), _backbranches(c, addr)]
        return "loop", d
    return ("short" if len(c) < len(t) else "long"), d


ERRCLS = [  # first compiler message -> family (errfix.py has one repair rule per family)
    ("undeclared", r"undefined identifier"),
    ("ptr-expected", r"pointer/array type was expected"),
    ("implicit-conv", r"illegal implicit conversion|illegal explicit conversion"),
    ("call-proto", r"function call .* does not match"),
    ("call-nonfunc", r"call of non-function"),
    ("void-operand", r"illegal operands?\b|illegal use of type"),
    ("redefined", r"redefined|redeclared"),
    ("label-decl", r"declaration syntax error|expression syntax error"),
    ("switch", r"label defined more than once|case"),
    ("timeout", r"timeout|timed out"),
    ("notinobj", r"is not in the object"),
]


def compile_message(err: str) -> tuple[str, str, int]:
    """(message, source line text, line number) of the first mwcc error.  mwcc prints:
    #      39:  <source line>
    #   Error:        ^
    #   <message, one or more lines>"""
    L = err.splitlines()
    for i, l in enumerate(L):
        if re.match(r"#\s+Error:", l):
            out = []
            for x in L[i + 1:]:
                if x.startswith("###") or not x.startswith("#") or "Error:" in x or "Warning:" in x:
                    break
                out.append(x.strip("# ").strip())
            src, num = "", -1
            for j in range(i - 1, max(-1, i - 4), -1):
                m = re.match(r"#\s+(\d+):\s?(.*)$", L[j])
                if m:
                    src, num = m.group(2), int(m.group(1))
                    break
            return " ".join(out), src, num
    return (L[-1] if L else ""), "", -1


def classify_compile(err: str) -> tuple[str, dict]:
    msg, src, num = compile_message(err)
    for k, rx in ERRCLS:
        if re.search(rx, msg, re.I):
            return "err:" + k, {"msg": msg[:200], "line": num, "src": src[:120]}
    return "err:other", {"msg": msg[:200], "line": num, "src": src[:120]}


# ------------------------------------------------------------------ worker
wbm = None
cur = None


def idle():
    try:  # Idle priority: the PC froze when a whole game was judged at normal priority
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS if os.name == "nt" else 19)
    except Exception:  # noqa: BLE001
        pass


ERRFIX_OK = None  # names whose build/errfix/NAME.c compiles


def init():
    global wbm, ERRFIX_OK
    idle()
    try:
        ERRFIX_OK = {n for n, r in json.loads(Path("build/errfix/results.json").read_text(encoding="utf-8")).items()
                     if r.get("status") in ("near", "size", "match")}
    except (OSError, ValueError):
        ERRFIX_OK = set()
    import missdb
    missdb.record = lambda *a, **k: None  # these drafts are already in the miss database
    os.environ["WB_FULL"] = "1"
    import workbench
    wbm = workbench


def scan_one(name: str):
    global cur
    try:
        ov = wbm.overlay_index().get(name)
        mod = "main" if ov is None else ("itcm" if ov < 0 else f"ov{ov:03d}")
        if mod != cur:
            wbm.select_module(name)
            cur = mod
        f = wbm.function(name)
        if wbm.covered(f["addr"]):
            return name, None
        src, where = wbm.starting_draft(name)
        fixed = Path("build/errfix") / f"{name}.c"  # errfix.py made it compile: classify that one
        if fixed.exists() and ERRFIX_OK is not None and name in ERRFIX_OK:
            src, where = fixed.read_text(encoding="utf-8"), fixed.as_posix()
        if not src:
            return name, {"size": f["size"], "status": "nodraft", "class": "nodraft", "detail": {"why": where[:200]}}
        thumb = f["mode"] == "thumb"
        if thumb:
            profs = [f"{v} {e} -thumb".replace("  ", " ") for v, e in wbm.am.COMPILERS][:2]
        else:
            profs = [f"{v} {e}".strip() for v, e in wbm.am.profiles_for(name, f["size"], f["addr"])][:2]
        best = None
        for p in profs:
            r = wbm.judge(name, src, p)
            rank = {"match": 0, "near": 1, "size": 2, "compile": 3, "refused": 4}
            if best is None or (rank[r["status"]], r.get("diffs", 0)) < (rank[best["status"]], best.get("diffs", 0)):
                best = r
            if r["status"] in ("match", "compile", "refused") and r["status"] != "compile":
                break
        st = best["status"]
        out = {"size": f["size"], "status": st, "profile": best.get("profile"), "diffs": best.get("diffs"),
               "draft": where, "mode": f["mode"]}
        if st == "match":
            out["class"] = "match"
        elif st == "compile":
            out["errors"] = best.get("errors", "")[-2000:]
            out["class"], out["detail"] = classify_compile(out["errors"])
        elif st == "refused":
            out["class"], out["detail"] = "refused", {"why": best.get("why", "")[:200]}
        else:
            full = best.get("full") or {}
            t, c = full.get("t", []), full.get("c", [])
            out["asm"] = {"t": t, "c": c, "addr": f["addr"]}
            if st == "near":
                out["class"], out["detail"] = classify_near(t, c)
            else:
                out["class"], out["detail"] = classify_size(t, c, f["addr"])
        return name, out
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return name, {"status": "error", "class": "error", "detail": {"why": str(e)[:200]}}


# ------------------------------------------------------------------ matched: how
def matched_methods() -> dict:
    """{file stem: method} from the commit that added the file."""
    r = subprocess.run(["git", "log", "--reverse", "--diff-filter=A", "--name-only", "--format=@@%s", "--", "src"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, cur_ = {}, ""
    for l in r.stdout.splitlines():
        if l.startswith("@@"):
            s = l[2:].lower()
            cur_ = ("clone" if "clone" in s else "donor" if "donor" in s else "reuse" if "reuse" in s else
                    "nearsweep" if "nearsweep" in s else "flagsweep" if "flagsweep" in s else
                    "auto" if "auto_match" in s or re.match(r"match \d+ function", s) and "(claude)" not in s else "hand")
        elif l.strip():
            out.setdefault(Path(l.strip()).stem, cur_)
    return out


def file_profiles() -> dict:
    out = {}
    for p in Path("config").glob("*/compilers.txt"):
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip() and not l.startswith("#"):
                path, _, prof = l.strip().partition(" ")
                out[Path(path).stem] = prof.strip()
    return out


def report_functions() -> list[tuple[str, str, int, float]]:
    d = json.load(gzip.open("progress/report.json.gz"))
    out = []
    for u in d["units"]:
        for f in u.get("functions", []):
            out.append((u["name"], f["name"], int(f["size"]), f.get("fuzzy_match_percent", 0)))
    return out


def default_profile() -> str:
    t = Path("game.toml").read_text(encoding="utf-8") if Path("game.toml").exists() else ""
    v = re.search(r'mwcc_version\s*=\s*"([^"]+)"', t)
    o = re.search(r'opt\s*=\s*"([^"]+)"', t)
    return f"{v.group(1) if v else '2.0/sp1p5'} {o.group(1) if o else '-O4,p'}"


def cmd_scan(a):
    idle()
    OUT.mkdir(parents=True, exist_ok=True)
    resf = OUT / "blockmap.json"
    res = {} if (a.fresh and not a.names) or not resf.exists() else json.loads(resf.read_text(encoding="utf-8"))
    funcs = report_functions()
    meth, profs, dflt = matched_methods(), file_profiles(), default_profile()
    for unit, n, size, pct in funcs:
        if pct >= 100:
            stem = unit.rsplit("/", 1)[-1]
            res[n] = {"size": size, "status": "matched", "class": "m:" + meth.get(stem, "?"),
                      "profile": profs.get(stem, dflt), "unit": unit}
    todo = sorted(n for u, n, s, p in funcs if p < 100 and a.min <= s <= a.max
                  and (not a.names or n in a.names)
                  and (a.fresh or a.names or res.get(n, {}).get("status") in (None, "error")))
    print(len(todo), "unmatched to classify", flush=True)
    t0, done = time.time(), 0
    with Pool(a.j, initializer=init, maxtasksperchild=40) as pool:
        for n, r in pool.imap_unordered(scan_one, todo, chunksize=1):
            done += 1
            if r is not None:
                res[n] = r
            if done % 25 == 0:
                print(f"[{done}/{len(todo)} {time.time() - t0:.0f}s]", flush=True)
                resf.write_text(json.dumps(res, indent=0), encoding="utf-8")
    resf.write_text(json.dumps(res, indent=0), encoding="utf-8")
    write_tsv(res)
    summary(res)


def write_tsv(res):
    with open(OUT / "blockmap.tsv", "w", encoding="utf-8") as f:
        f.write("name\tsize\tstatus\tclass\tprofile\tdiffs\tdetail\n")
        for n, r in sorted(res.items(), key=lambda x: (x[1].get("class", ""), x[1].get("size", 0))):
            f.write(f"{n}\t{r.get('size')}\t{r.get('status')}\t{r.get('class')}\t{r.get('profile') or ''}\t"
                    f"{r.get('diffs') if r.get('diffs') is not None else ''}\t{json.dumps(r.get('detail', ''))[:200]}\n")


def summary(res):
    c, b = collections.Counter(), collections.Counter()
    for r in res.values():
        c[r.get("class")] += 1
        b[r.get("class")] += r.get("size") or 0
    print(f"{'class':22} {'funcs':>6} {'bytes':>8}  tool")
    for k, v in sorted(c.items(), key=lambda x: (not str(x[0]).startswith("m:"), -x[1])):
        tool = TOOLS.get(k, "errfix.py" if str(k).startswith("err:") else "")
        print(f"{k:22} {v:6} {b[k]:8}  {tool}")
    pc = collections.Counter(r.get("profile") for r in res.values() if r.get("status") == "matched")
    print("\nmatched by profile:")
    for k, v in pc.most_common():
        print(f"  {v:5}  {k}")


def reclassify(r: dict) -> None:
    """Classify again from what scan kept (listings, compiler messages): improve the classifier without recompiling."""
    if r.get("status") == "compile" and "errors" in r:
        r["class"], r["detail"] = classify_compile(r["errors"])
    elif r.get("asm"):
        t, c, addr = r["asm"]["t"], r["asm"]["c"], r["asm"]["addr"]
        r["class"], r["detail"] = classify_near(t, c) if r["status"] == "near" else classify_size(t, c, addr)


def cmd_export(a):
    """Drafts of the functions of some classes into a.dir: the repaired file when errfix made one that compiles
    (build/errfix/NAME.c), else the starting draft (same as workbench.starting_draft)."""
    res = load()
    want = lambda c: any(c == k or (k.endswith("*") and c.startswith(k[:-1])) for k in a.classes)  # noqa: E731
    names = [n for n, r in res.items() if want(str(r.get("class"))) and r.get("size", 0) <= a.max]
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    fixed = {}
    ef = Path("build/errfix/results.json")
    if ef.exists():
        fixed = {n for n, r in json.loads(ef.read_text(encoding="utf-8")).items() if r.get("status") not in ("compile", "error")}
    os.environ.setdefault("WB_FULL", "")
    import workbench as wb
    n_ok = 0
    for n in names:
        src = None
        if n in fixed and Path(f"build/errfix/{n}.c").exists():
            src = Path(f"build/errfix/{n}.c").read_text(encoding="utf-8")
        else:
            wb.select_module(n)
            src, _ = wb.starting_draft(n)
        if src:
            (d / f"{n}.c").write_text(src, encoding="utf-8", newline="\n")
            n_ok += 1
    print(f"{n_ok}/{len(names)} drafts written to {d}")


RUNNERS = {  # class -> command line (NAME, FILE, PROFILE filled in); the tool writes FILE.best.c when it gets closer
    "reg": ["permrand.py", "{name}", "{file}", "--n", "{n}", "-j", "{j}", "--profile", "{profile}"],
    "regsched": ["permrand.py", "{name}", "{file}", "--n", "{n}", "-j", "{j}", "--profile", "{profile}"],
}


def cmd_run(a):
    """Each function of class a.cls: its draft into build/blockmap/run/<cls>/NAME.c, the class tool on it, the
    result (match / closer / nothing) into build/blockmap/run/<cls>/results.json (fj/submit-many format)."""
    if a.cls not in RUNNERS:
        sys.exit(f"no runner for {a.cls}; known: {', '.join(RUNNERS)}")
    idle()
    res = load()
    d = OUT / "run" / a.cls
    d.mkdir(parents=True, exist_ok=True)
    resf = d / "results.json"
    out = json.loads(resf.read_text(encoding="utf-8")) if resf.exists() else {}
    names = [n for n, r in sorted(res.items(), key=lambda x: (x[1].get("diffs") or 0, x[1].get("size", 0)))
             if r.get("class") == a.cls and r.get("size", 0) <= a.max and (r.get("diffs") or 0) <= a.max_diffs
             and n not in out]
    os.environ["WB_FULL"] = ""
    import workbench as wb
    tools = HERE.parent
    for i, n in enumerate(names):
        r = res[n]
        f = d / f"{n}.c"
        src = Path(r["draft"]).read_text(encoding="utf-8") if Path(str(r.get("draft"))).is_file() else None
        if src is None:
            wb.select_module(n)
            src, _ = wb.starting_draft(n)
        if not src:
            continue
        f.write_text(src, encoding="utf-8", newline="\n")
        cmd = [x.format(name=n, file=f.as_posix(), n=a.n, j=a.j, profile=r.get("profile") or "") for x in RUNNERS[a.cls]]
        t0 = time.time()
        p = subprocess.run([sys.executable, str(tools / cmd[0])] + cmd[1:], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        best = f.with_suffix(".best.c")
        tail = (p.stdout or "")[-300:].strip().splitlines()[-1:] or [""]
        m = re.search(r"written \S+ (\d+)\s*$", tail[0])  # permrand: `written FILE.best.c DIFFS`
        st = ("match" if m.group(1) == "0" else "closer") if m and best.exists() else "same"
        if best.exists() and st == "match":
            f.write_text(best.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        out[n] = {"size": r.get("size"), "status": "match" if st == "match" else r["status"], "match": st == "match",
                  "profile": r.get("profile"), "k": [0 if st == "match" else 1, r.get("diffs") or 0],
                  "mt": os.path.getmtime(f), "result": st, "tail": tail[0][:200], "t": round(time.time() - t0)}
        resf.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"[{i + 1}/{len(names)}] {n} {r.get('diffs')} diffs -> {st}  {tail[0][:100]}", flush=True)
    c = collections.Counter(v["result"] for v in out.values())
    print(dict(c))


def load():
    return json.loads((OUT / "blockmap.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan")
    s.add_argument("-j", type=int, default=10)
    s.add_argument("--min", type=int, default=4)
    s.add_argument("--max", type=int, default=1500)
    s.add_argument("--fresh", action="store_true")
    s.add_argument("names", nargs="*")
    sp.add_parser("reclass")
    s = sp.add_parser("run", help="run the tool of a class on all its functions (reg/regsched: permrand)")
    s.add_argument("cls")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("-j", type=int, default=6)
    s.add_argument("--max", type=int, default=10**9)
    s.add_argument("--max-diffs", type=int, default=12)
    s = sp.add_parser("export", help="write the drafts of some classes to DIR (feed nearsweep --src, fj, a tool)")
    s.add_argument("dir")
    s.add_argument("classes", nargs="+", help="class names, or a prefix ending in * (err:*)")
    s.add_argument("--max", type=int, default=10**9)
    s = sp.add_parser("show")
    s.add_argument("cls", nargs="?")
    s = sp.add_parser("list")
    s.add_argument("cls")
    s.add_argument("--max", type=int, default=10**9)
    a = ap.parse_args()
    a.names = [m for n in getattr(a, "names", []) for m in
               (open(n[1:], encoding="utf-8").read().split() if n.startswith("@") else [n])]
    if a.cmd == "scan":
        cmd_scan(a)
    elif a.cmd == "reclass":
        res = load()
        for r in res.values():
            reclassify(r)
        (OUT / "blockmap.json").write_text(json.dumps(res, indent=0), encoding="utf-8")
        write_tsv(res)
        summary(res)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "export":
        cmd_export(a)
    elif a.cmd == "show":
        res = load()
        if not a.cls:
            summary(res)
        else:
            for n, r in sorted(res.items(), key=lambda x: x[1].get("size", 0)):
                if r.get("class") == a.cls:
                    print(f"{n:28} {r.get('size'):6} {r.get('diffs')!s:>5} {r.get('profile')}  {json.dumps(r.get('detail', ''))[:160]}")
    elif a.cmd == "list":
        res = load()
        for n, r in sorted(res.items(), key=lambda x: x[1].get("size", 0)):
            if r.get("class") == a.cls and r.get("size", 0) <= a.max:
                print(n)


if __name__ == "__main__":
    main()
