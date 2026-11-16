"""errfix.py - make m2c drafts that do not compile compile, one compiler error at a time, then judge them.

    cd projets/<game>
    python ../../studio/gametools/prototypes/errfix.py [-j 8] [--out build/errfix] [names... | @file]
    # no names: every function blockmap.py classed err:* (build/blockmap/blockmap.json)
    python ../../studio/gametools/workbench.py submit-many build/errfix      # the ones that match

Greedy: compile, read the FIRST error (line + message), try the repair rules of its family on that line, keep the
first candidate whose first error is gone (compiles, or the first error is now later / another one). Up to 40 steps.
Every rule is one family of blockmap.py (Spyro 2026-11-16: ~750 of 1900 unmatched functions never compiled):

  undeclared      sp / spN / saved_reg_rN / unkspN -> local `M2C_UNK X;`; data_/func_ -> extern; other -> local s32
  ptr-expected    `*(E)` / `E[i]` on an integer -> `*(T *)(E)` with T from the line's casts (u8/s16..) or s32
  implicit-conv   `lhs = rhs;` / `return rhs;` -> cast the right side to the type the message names
  call-proto      prototype that does not match its call -> old-style declaration `T f();`
  call-nonfunc    `X(...)` / `*(E)(...)` on an integer -> call through a function pointer cast
  void-operand    arithmetic on a `void *` / pointer operands -> casts to s32 / (s8 *)
  label-decl      m2c jump-table labels `.L_xxx` -> `L_xxx` (extern s32)

Writes OUT/NAME.c and OUT/results.json (fj.py / submit-many format) + OUT/errfix.json (steps per rule).
"""
import argparse
import collections
import json
import os
import re
import sys
import tempfile
import time
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

MAX_STEPS = 40
TYPES = r"(?:s8|u8|s16|u16|s32|u32|s64|u64|f32|f64|M2C_UNK|void|char|int|long|short|unsigned\s+\w+)"


# ------------------------------------------------------------------ helpers on one line of source
def body_start(lines: list[str], name: str) -> int:
    """Index of the line that opens the function body (`... name(...) {`)."""
    for i, l in enumerate(lines):
        if re.search(rf"\b{re.escape(name)}\s*\(.*\)\s*\{{\s*$", l):
            return i
    for i, l in enumerate(lines):
        if l.rstrip().endswith("{") and not l.startswith((" ", "\t")):
            return i
    return -1


def add_local(lines, name, decl):
    i = body_start(lines, name)
    if i < 0:
        return None
    return lines[:i + 1] + [f"    {decl}"] + lines[i + 1:]


def add_global(lines, decl):
    i = next((k for k, l in enumerate(lines) if l.startswith("#include")), -1)
    return lines[:i + 1] + [decl] + lines[i + 1:]


def cast_kind(line: str) -> list[str]:
    """Pointer types to try for an untyped dereference, the most likely first (casts already on the line)."""
    order = []
    for t in re.findall(r"\((u8|s8|u16|s16|u32|s32)\)", line):
        order.append(f"{t} *")
    order += ["s32 *", "u8 *", "u16 *", "s16 *", "s8 *", "u32 *", "void **"]
    return list(dict.fromkeys(order))


def _matching_paren(s: str, i: int) -> int:
    """s[i] == '(' -> index of its ')' (or -1)."""
    d = 0
    for k in range(i, len(s)):
        if s[k] == "(":
            d += 1
        elif s[k] == ")":
            d -= 1
            if d == 0:
                return k
    return -1


# ------------------------------------------------------------------ rules: (family, line) -> candidate sources
def rule_undeclared(lines, li, msg, name):
    m = re.search(r"undefined identifier '([^']+)'", msg)
    if not m:
        return
    x = m.group(1)
    if x.startswith((".L_", "L_")):
        return
    if re.match(r"(func_|data_|[A-Z][A-Za-z]+_)", x):
        called = re.search(rf"\b{re.escape(x)}\s*\(", "\n".join(lines))
        yield add_global(lines, f"M2C_UNK {x}();" if called else f"extern M2C_UNK {x};")
        yield add_global(lines, f"extern u8 {x}[];")
    else:
        yield add_local(lines, name, f"M2C_UNK {x};")
        yield add_local(lines, name, f"u8 {x}[0x100];")


def rule_ptr_expected(lines, li, msg, name):
    line = lines[li]
    # `**(E)` / `**(T *)(E)`: a pointer to a pointer
    m = re.search(r"\*\*\((?:(\w+) \*\))?\(?", line)
    if m:
        for t in ("u8 **", "s32 **", "void **", "u16 **"):
            if m.group(1):
                new = line.replace(f"**({m.group(1)} *)", f"**({t})", 1)
            else:
                new = line[:m.start()] + f"**({t})(" + line[m.start() + 3:]
            yield lines[:li] + [new] + lines[li + 1:]
    for t in cast_kind(line):
        # first `*(` not already cast
        for m in re.finditer(r"\*\(", line):
            if re.match(r"(?:[A-Za-z_]\w*\s*)*\*+\)", line[m.end():]):
                continue
            yield lines[:li] + [line[:m.start()] + f"*({t})(" + line[m.end():]] + lines[li + 1:]
            break
        # `*ident` on an integer
        m = re.search(r"(?<![\w)\]])\*([A-Za-z_]\w*)\b(?!\s*\()", line)
        if m:
            yield lines[:li] + [line[:m.start()] + f"*({t}){m.group(1)}" + line[m.end():]] + lines[li + 1:]
        # `ident[i]` on an integer
        m = re.search(r"\b([A-Za-z_]\w*)\[", line)
        if m and not re.match(TYPES, m.group(1)):
            yield lines[:li] + [line[:m.start()] + f"(({t}){m.group(1)})[" + line[m.end():]] + lines[li + 1:]
        # M2C_FIELD(base, ...) with an integer base works; `->` on an integer: nothing to do generically


def rule_implicit_conv(lines, li, msg, name):
    m = re.search(r"conversion from '([^']+)' to\s*'([^']+)'", msg)
    if not m:
        return
    to = m.group(2).strip()
    if "struct" in to or "union" in to:
        return
    line = lines[li]
    a = re.match(r"^(\s*)(.*?[^=!<>+\-*/&|^])=(?!=)\s*(.*);\s*(//.*)?$", line)
    if a:
        yield lines[:li] + [f"{a.group(1)}{a.group(2)}= ({to}) ({a.group(3)});"] + lines[li + 1:]
        # or retype the left side when it is a plain local: `temp_r1 = ...` with temp_r1 declared above
        v = a.group(2).strip()
        if re.fullmatch(r"\w+", v):
            for k in range(li):
                d = re.match(rf"^(\s*){TYPES}\s*\*?\s*{re.escape(v)};", lines[k])
                if d:
                    yield lines[:k] + [f"{d.group(1)}{to} {v};" if not to.endswith("*") else f"{d.group(1)}{to}{v};"] + lines[k + 1:]
                    break
    r = re.match(r"^(\s*)return\s+(.*);\s*$", line)
    if r:
        yield lines[:li] + [f"{r.group(1)}return ({to}) ({r.group(2)});"] + lines[li + 1:]
    # an argument of a call: cast every bare identifier / address-of argument in turn
    for m in re.finditer(r"(?<=[(,])\s*(&?[A-Za-z_]\w*)\s*(?=[,)])", line):
        yield lines[:li] + [line[:m.start(1)] + f"({to}) {m.group(1)}" + line[m.end(1):]] + lines[li + 1:]


def rule_call_proto(lines, li, msg, name):
    m = re.search(r"function call '(\w+)\(", msg) or re.search(r"\b(\w+)\s*\(", lines[li])
    if not m:
        return
    f = m.group(1)
    for k, l in enumerate(lines):
        d = re.match(rf"^(.*?\b{re.escape(f)})\s*\([^()]*\)\s*;(.*)$", l)
        if d and not l.startswith(" "):
            yield lines[:k] + [f"{d.group(1)}();{d.group(2)}"] + lines[k + 1:]
            return
    yield add_global(lines, f"M2C_UNK {f}();")


def rule_call_nonfunc(lines, li, msg, name):
    line = lines[li]
    # `*(E)(args)` -> `((M2C_UNK (*)()) *(E))(args)`
    for m in re.finditer(r"\*\(", line):
        e = _matching_paren(line, m.end() - 1)
        if e > 0 and line[e + 1:e + 2] == "(":
            yield lines[:li] + [line[:m.start()] + f"((M2C_UNK (*)()) *(s32 *)({line[m.end():e]}))" + line[e + 1:]] + lines[li + 1:]
            yield lines[:li] + [line[:m.start()] + f"((M2C_UNK (*)()) {line[m.start():e + 1]})" + line[e + 1:]] + lines[li + 1:]
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", line):
        if m.group(1) in ("if", "while", "for", "switch", "return", "sizeof") or m.group(1).startswith(("func_", "M2C")):
            continue
        yield lines[:li] + [line[:m.start()] + f"((M2C_UNK (*)()) {m.group(1)})(" + line[m.end():]] + lines[li + 1:]
    for m in re.finditer(r"\b(M2C_FIELD\()", line):
        e = _matching_paren(line, m.end() - 1)
        if e > 0 and line[e + 1:e + 2] == "(":
            yield lines[:li] + [line[:m.start()] + f"((M2C_UNK (*)()) {line[m.start():e + 1]})" + line[e + 1:]] + lines[li + 1:]


def rule_void_operand(lines, li, msg, name):
    line = lines[li]
    yield from rule_ptr_expected(lines, li, msg, name)
    # `void *` locals used in arithmetic: retype them u8 *
    for v in re.findall(r"\b(\w+)\b", line):
        for k in range(li):
            if re.match(rf"^\s*void \*{re.escape(v)};", lines[k]):
                yield lines[:k] + [lines[k].replace("void *", "u8 *", 1)] + lines[k + 1:]
                yield lines[:k] + [lines[k].replace("void *", "s32 ", 1)] + lines[k + 1:]
    # pointer + pointer / pointer * int: cast every identifier of the line to s32 in turn
    for m in re.finditer(r"(?<![\w.>*&])([A-Za-z_]\w*)\b(?!\s*[\(\[])", line):
        if re.fullmatch(TYPES, m.group(1)) or m.group(1) in ("if", "return", "while"):
            continue
        yield lines[:li] + [line[:m.start()] + f"((s32) {m.group(1)})" + line[m.end():]] + lines[li + 1:]


def rule_label_decl(lines, li, msg, name):
    """m2c names a call into the middle of another function `.L_ADDR` (a second entry point of a library routine,
    dsd label). Its global name is `lbl_ADDR` (find_culprits.globalize_labels, same bytes); auto_match.integrate
    renames the label in symbols.txt when a submitted file calls it."""
    src = "\n".join(lines)
    if ".L_" in src:
        s = re.sub(r"\.L_([0-9a-fA-F]{8})", r"lbl_\1", src)
        yield s.splitlines()


def rule_redefined(lines, li, msg, name):
    """`object 'X' redefined`: compile_fixes or m2c declared X twice: drop one of the two declarations."""
    m = re.search(r"'(\w+)'", msg)
    if not m:
        return
    x = m.group(1)
    decl = [k for k, l in enumerate(lines) if re.match(rf"^\s*[\w\s]+?\**\s*{re.escape(x)}(\[[^\]]*\])?;", l)]
    for k in decl[::-1]:
        yield lines[:k] + lines[k + 1:]


RULES = {"redefined": rule_redefined, "undeclared": rule_undeclared, "ptr-expected": rule_ptr_expected, "implicit-conv": rule_implicit_conv,
         "call-proto": rule_call_proto, "call-nonfunc": rule_call_nonfunc, "void-operand": rule_void_operand,
         "label-decl": rule_label_decl}


# ------------------------------------------------------------------ worker
wbm = None
cur = None


def init():
    global wbm
    import blockmap
    blockmap.idle()
    import workbench  # repaired drafts are new C: their misses go to the miss database (AGENTS.md rule 7)
    workbench.MISS_SOURCE = "errfix"
    wbm = workbench


def first_error(src: str, prof: str, tmp: Path):
    """None when it compiles, else (family, message, line index 0-based, raw)."""
    import blockmap
    version, _, extra = prof.partition(" ")
    extra = extra.replace("-thumb", "").strip()
    mwcc = wbm.am.MWCC_ROOT / version / "mwccarm.exe"
    (tmp / "f.o").unlink(missing_ok=True)
    (tmp / "f.c").write_text(src, encoding="utf-8", newline="\n")
    r = wbm.am.run_limited(f'"{mwcc}" -O4,p {wbm.pc.BASE_FLAGS} {extra} -i "{wbm.ROOT / "include"}" -c f.c -o f.o',
                           cwd=tmp, shell=True)
    if r.returncode == 0 and (tmp / "f.o").exists():
        return None
    raw = (r.stdout or "") + (r.stderr or "")
    if "timeout" in raw[-50:] or r.stderr == "timeout":
        return ("timeout", "timeout", -1, raw)
    msg, _, num = blockmap.compile_message(raw)
    cls, _ = blockmap.classify_compile(raw)
    return (cls[4:], msg, num - 1, raw)


def fix_one(job):
    global cur
    name, prof, out = job
    t0 = time.time()
    try:
        ov = wbm.overlay_index().get(name)
        mod = "main" if ov is None else ("itcm" if ov < 0 else f"ov{ov:03d}")
        if mod != cur:
            wbm.select_module(name)
            cur = mod
        f = wbm.function(name)
        if wbm.covered(f["addr"]):
            return name, None, None
        src, where = wbm.starting_draft(name)
        if not src:
            return name, None, {"why": where}
        src = wbm.am.compile_fixes(src)
        steps = collections.Counter()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            err = first_error(src, prof, tmp)
            n = 0
            while err and n < MAX_STEPS:
                n += 1
                fam, msg, li, _ = err
                rule = RULES.get(fam)
                lines = src.splitlines()
                if rule is None or not (0 <= li < len(lines)) and fam != "label-decl":
                    break
                progressed = False
                seen = set()
                for cand in rule(lines, li, msg, name):
                    if not cand:
                        continue
                    cs = "\n".join(cand) + "\n"
                    if cs in seen or cs == src:
                        continue
                    seen.add(cs)
                    if len(seen) > 30:
                        break
                    e2 = first_error(cs, prof, tmp)
                    if e2 is None or e2[2] > li or (e2[2] == li and e2[1] != msg) or (e2[0] != fam and e2[2] >= li):
                        src, err, progressed = cs, e2, True
                        steps[fam] += 1
                        break
                if not progressed:
                    break
            info = {"steps": dict(steps), "left": None if err is None else f"{err[0]}: {err[1][:120]}",
                    "draft": where}
        (out / f"{name}.c").write_text(src, encoding="utf-8", newline="\n")
        if err is not None:
            return name, {"size": f["size"], "status": "compile", "match": False, "profile": prof, "k": [1, 9999],
                          "mt": os.path.getmtime(out / f"{name}.c"), "t": round(time.time() - t0, 1)}, info
        # compiles: judge on the prior's first profiles (+ the one we fixed with)
        profs = [prof] + [f"{v} {e}".strip() for v, e in wbm.am.profiles_for(name, f["size"], f["addr"])][:3]
        best = None
        for p in dict.fromkeys(profs):
            r = wbm.judge(name, src, p)
            rk = {"match": 0, "near": 1, "size": 2, "compile": 3, "refused": 4}
            if best is None or (rk[r["status"]], r.get("diffs", 0)) < (rk[best["status"]], best.get("diffs", 0)):
                best = dict(r, profile=p)
            if r["status"] == "match":
                break
        st = best["status"]
        info["judge"] = st
        return name, {"size": f["size"], "status": st, "match": st == "match", "profile": best.get("profile"),
                      "k": [0 if st == "match" else 1, best.get("diffs", 999) if st != "compile" else 9999],
                      "mt": os.path.getmtime(out / f"{name}.c"), "t": round(time.time() - t0, 1)}, info
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return name, {"status": "error", "match": False, "k": [1, 9999], "mt": 0, "err": str(e)[:200]}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=8)
    ap.add_argument("--out", default="build/errfix")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry", action="store_true", help="redo the drafts that still do not compile (new rules)")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    names = [m for n in a.names for m in (open(n[1:], encoding="utf-8").read().split() if n.startswith("@") else [n])]
    bm = json.loads(Path("build/blockmap/blockmap.json").read_text(encoding="utf-8"))
    if not names:
        names = sorted((n for n, r in bm.items() if str(r.get("class", "")).startswith("err:")),
                       key=lambda n: bm[n].get("size", 0))
    if a.limit:
        names = names[:a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    resf, infof = out / "results.json", out / "errfix.json"
    res = json.loads(resf.read_text(encoding="utf-8")) if resf.exists() else {}
    info = json.loads(infof.read_text(encoding="utf-8")) if infof.exists() else {}
    if a.retry:
        res = {n: r for n, r in res.items() if r.get("status") not in ("compile", "error")}
    jobs = [(n, bm.get(n, {}).get("profile") or "2.0/sp1p5", out) for n in names if n not in res]
    print(len(jobs), "drafts to repair", flush=True)
    import blockmap
    blockmap.idle()
    t0, done = time.time(), 0
    with Pool(a.j, initializer=init, maxtasksperchild=30) as pool:
        for n, r, inf in pool.imap_unordered(fix_one, jobs, chunksize=1):
            done += 1
            if r is not None:
                res[n] = r
            if inf is not None:
                info[n] = inf
            if done % 20 == 0 or (r and r.get("match")):
                print(n, r and r["status"], f"[{done}/{len(jobs)} {time.time() - t0:.0f}s]", flush=True)
                resf.write_text(json.dumps(res, indent=1), encoding="utf-8")
                infof.write_text(json.dumps(info, indent=1), encoding="utf-8")
    resf.write_text(json.dumps(res, indent=1), encoding="utf-8")
    infof.write_text(json.dumps(info, indent=1), encoding="utf-8")
    st = collections.Counter(r["status"] for n, r in res.items() if n in set(names))
    print("status:", dict(st))
    steps = collections.Counter()
    left = collections.Counter()
    for n, i in info.items():
        steps.update(i.get("steps", {}))
        if i.get("left"):
            left[i["left"].split(":")[0]] += 1
    print("repairs applied per rule:", dict(steps))
    print("still failing, first error family:", dict(left))


if __name__ == "__main__":
    main()
