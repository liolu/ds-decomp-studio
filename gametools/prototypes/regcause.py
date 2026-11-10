"""regcause.py - which statement controls a wrong register / schedule? (diagnosis, never a match by itself)

    python ../../studio/gametools/prototypes/regcause.py NAME FILE.c [-p PROFILE] [--dup] [-j 12] [--top 15]

Run from the project dir. For a near draft whose remaining diffs are register colouring or scheduling (the C shape is
right), every single-line statement of the function body is deleted in turn (and, with --dup, duplicated), the variant
is compiled, and its listing is aligned with the target with registers masked (so the deleted statement's own
instructions just drop out of the alignment). Then, among the target instructions that are WRONG in the draft, it
counts how many become exactly right (registers included) in the variant, and how many right ones become wrong.

A statement whose removal fixes the wrong instructions without breaking others is what drives the allocator/scheduler
there: change THAT statement's form (type, temp, order, inline, index form...) instead of the block that looks wrong.
Born from TnJ s38 (agents rebuilt this by hand three times: 5th-arg drop.py, 0200c138 probes, 01ff8188 last-vertex).
"""
import argparse, difflib, os, re, sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["WB_FULL"] = "1"

DECL = re.compile(r"^\s*(?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+|static\s+)*[A-Za-z_]\w*(?:\s*\*+\s*|\s+)\**[A-Za-z_]\w*(?:\[[^\]]*\])?\s*(?:,\s*\**\w+(?:\[[^\]]*\])?\s*)*;\s*$")


def mask(l):
    l = l.split("@")[0]
    l = re.sub(r"\b(r\d+|sl|fp|ip|lr|sp|pc)\b", "R", l)
    l = re.sub(r"0x[0-9a-f]+", "A", l)
    l = re.sub(r"#-?\d+", "#N", l)
    return l.strip()


def exact(l):
    l = l.split("@")[0]
    l = re.sub(r"\[pc, #\d+\]", "[pc]", l)
    l = re.sub(r"\b(bl|b|blx)\S*\s+\S+", r"\1 X", l) if l.lstrip().startswith(("bl", "b ")) else l
    return re.sub(r"0x[0-9a-f]+", "A", l).strip()


def _init(name, prof):
    global NAME, PROF, hunt
    import hunt as h
    hunt = h
    NAME, PROF = name, prof
    hunt._init()


def _listing(src):
    r = hunt._judge((NAME, src, PROF))
    full = r.get("full")
    return (r.get("diffs"), r.get("size"), full["t"] if full else None, full["c"] if full else None)


def wrong_set(t, c):
    """Indexes of target lines that are wrong in candidate c (alignment with registers masked)."""
    sm = difflib.SequenceMatcher(None, [mask(x) for x in t], [mask(x) for x in c], autojunk=False)
    right, aligned = set(), set()
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            for k in range(a1 - a0):
                aligned.add(a0 + k)
                if exact(t[a0 + k]) == exact(c[b0 + k]):
                    right.add(a0 + k)
    return set(range(len(t))) - right, aligned


def _job(args):
    lineno, kind, src = args
    d, s, t, c = _listing(src)
    if t is None or c is None:
        return (lineno, kind, None, None, None, d, s)
    wrong, aligned = wrong_set(t, c)
    return (lineno, kind, wrong, aligned, None, d, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("file")
    ap.add_argument("-p", "--profile", default=None)
    ap.add_argument("--dup", action="store_true")
    ap.add_argument("-j", type=int, default=12)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    src = Path(a.file).read_text(encoding="utf-8", errors="replace")
    if src.startswith("// profile:"):
        first, src = src.split("\n", 1)
        a.profile = a.profile or first.split(":", 1)[1].strip()
    lines = src.split("\n")
    start = next(i for i, l in enumerate(lines) if re.match(rf"^[^\s].*\b{re.escape(a.name)}\s*\(", l) and not l.rstrip().endswith(";"))
    jobs = []
    depth = 0
    for i in range(start, len(lines)):
        l = lines[i]
        depth += l.count("{") - l.count("}")
        if i > start and depth <= 0:
            break
        st = l.strip()
        if not st.endswith(";") or st.startswith(("return", "for", "if", "while", "}", "case", "break", "default")) or DECL.match(l):
            continue
        jobs.append((i + 1, "del", "\n".join(lines[:i] + lines[i + 1:])))
        if a.dup:
            jobs.append((i + 1, "dup", "\n".join(lines[:i + 1] + [l] + lines[i + 1:])))
    with Pool(a.j, initializer=_init, initargs=(a.name, a.profile)) as pool:
        base = pool.apply(_listing, (src,))
        res = pool.map(_job, jobs, chunksize=1)
    d0, s0, t0, c0 = base
    if t0 is None:
        sys.exit(f"{a.name}: draft does not compile ({d0})")
    wrong0, _ = wrong_set(t0, c0)
    print(f"{a.name}: draft {d0} diffs, size {s0}, {len(wrong0)} wrong target lines; {len(jobs)} variants")
    rows = []
    for lineno, kind, wrong, aligned, _, d, s in res:
        if wrong is None:
            continue
        fixed = len([k for k in wrong0 if k in aligned and k not in wrong])
        broke = len([k for k in aligned if k in wrong and k not in wrong0])
        rows.append((fixed - broke, fixed, broke, lineno, kind, d, s))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    for score, fixed, broke, lineno, kind, d, s in rows[: a.top]:
        print(f"  {kind} line {lineno:4d}: fixes {fixed}/{len(wrong0)}, breaks {broke}  ({d} diffs, {s} B)  | {lines[lineno - 1].strip()[:70]}")


if __name__ == "__main__":
    main()
