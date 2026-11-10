"""regfocus.py - targeted mutations of the few statements that drive a wrong register / schedule.

    python ../../studio/gametools/prototypes/regfocus.py NAME FILE.c --lines 56,47 [-p PROFILE] [--rounds 2] [-j 12]

Run from the project dir. Use after regcause.py: it names the statements whose removal fixes the wrong instructions.
For each such line (1-based line numbers of FILE.c) it builds variants of THAT line only, judges them all in parallel,
keeps the best and (with --rounds N) mutates again from it:
  move      the line moved up/down by 1..4 statements (semantics NOT checked: review a winner by hand)
  swap      operands of a top-level + * & | ^ swapped
  reuse     `x = E;` then later lines that repeat E use x instead (hand CSE), and the reverse (x replaced by E)
  split     `x = a op b;` -> `x = a; x op= b;`, and `x = x op b;` <-> `x op= b;`
  cast      RHS wrapped in (s32) / (u32) / (int)
  temp      `x = E;` -> `{ int t_ = E; x = t_; }`
Best files go to build/hunt/regfocus/NAME/; a MATCH is printed (check it with relcheck before submitting).
Born from TnJ 2026-11-10 (regcause pointed at `pal_data = base + size` in func_0203bd24).
"""
import argparse, os, re, sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ASSIGN = re.compile(r"^(\s*)([\w\.\->\[\]\*]+)\s*=\s*(.+);\s*$")
BINOP = re.compile(r"^(.+?)\s*([+*&|^])\s*(.+)$")


def _init(name, prof):
    global NAME, PROF, hunt
    import hunt as h
    hunt = h
    NAME, PROF = name, prof
    hunt._init()


def _judge(src):
    r = hunt._judge((NAME, src, PROF))
    d = r.get("diffs")
    return (d if d is not None else 99999, r.get("size"), bool(r.get("match")), src)


def is_stmt(l):
    s = l.strip()
    return s.endswith(";") and not s.startswith(("return", "for", "if", "while", "case", "break", "default", "}"))


def mutate(lines, i):
    """Variants (list of line lists) of line index i."""
    out = []
    l = lines[i]
    # move
    for step in (-4, -3, -2, -1, 1, 2, 3, 4):
        j = i + step
        if 0 <= j < len(lines) and all(is_stmt(lines[k]) for k in range(min(i, j), max(i, j) + 1)):
            v = lines[:]
            v.pop(i)
            v.insert(j, l)
            out.append(("move%+d" % step, v))
    m = ASSIGN.match(l)
    if m:
        ind, lhs, rhs = m.groups()
        b = BINOP.match(rhs)
        if b and "(" not in rhs:
            a_, op, c_ = b.groups()
            out.append(("swap", lines[:i] + [f"{ind}{lhs} = {c_} {op} {a_};"] + lines[i + 1:]))
            if a_.strip() == lhs:
                out.append(("compound", lines[:i] + [f"{ind}{lhs} {op}= {c_};"] + lines[i + 1:]))
            else:
                out.append(("split", lines[:i] + [f"{ind}{lhs} = {a_};", f"{ind}{lhs} {op}= {c_};"] + lines[i + 1:]))
        for c in ("s32", "u32", "int"):
            out.append((f"cast-{c}", lines[:i] + [f"{ind}{lhs} = ({c})({rhs});"] + lines[i + 1:]))
        out.append(("temp", lines[:i] + [f"{ind}{{ int t_ = {rhs}; {lhs} = t_; }}"] + lines[i + 1:]))
        # reuse / inline in the next 8 lines
        if re.match(r"^\w+$", lhs):
            for k in range(i + 1, min(len(lines), i + 9)):
                if rhs in lines[k] and lhs not in lines[k]:
                    v = lines[:]
                    v[k] = lines[k].replace(f"({rhs})", lhs).replace(rhs, lhs)
                    out.append((f"reuse@{k + 1}", v))
                if re.search(rf"\b{re.escape(lhs)}\b", lines[k]) and not ASSIGN.match(lines[k] or "") is None:
                    pass
                if re.search(rf"\b{re.escape(lhs)}\b", lines[k]) and not re.match(rf"^\s*{re.escape(lhs)}\s*=", lines[k]):
                    v = lines[:]
                    v[k] = re.sub(rf"\b{re.escape(lhs)}\b", f"({rhs})", lines[k])
                    out.append((f"inline@{k + 1}", v))
        mm = re.match(r"^\s*(\w+)\s*=\s*\1\s*([+*&|^-])\s*(.+);\s*$", l)
        if mm:
            out.append(("compound2", lines[:i] + [f"{ind}{mm.group(1)} {mm.group(2)}= {mm.group(3)};"] + lines[i + 1:]))
    mc = re.match(r"^(\s*)(\w+)\s*([+*&|^-])=\s*(.+);\s*$", l)
    if mc:
        ind, x, op, e = mc.groups()
        out.append(("uncompound", lines[:i] + [f"{ind}{x} = {x} {op} {e};"] + lines[i + 1:]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("file")
    ap.add_argument("--lines", required=True)
    ap.add_argument("-p", "--profile", default=None)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("-j", type=int, default=12)
    a = ap.parse_args()
    src = Path(a.file).read_text(encoding="utf-8", errors="replace")
    head = ""
    if src.startswith("// profile:"):
        head, src = src.split("\n", 1)
        head += "\n"
        a.profile = a.profile or head.split(":", 1)[1].strip()
    targets = [l.strip() for l in src.split("\n")]
    want = [targets[int(n) - 1 - (1 if head else 0)] for n in a.lines.split(",")]
    out = Path("build/hunt/regfocus") / a.name
    out.mkdir(parents=True, exist_ok=True)
    with Pool(a.j, initializer=_init, initargs=(a.name, a.profile)) as pool:
        best = pool.apply(_judge, (src,))
        print(f"{a.name}: start {best[0]} diffs, {best[1]} B")
        for rnd in range(a.rounds):
            lines = best[3].split("\n")
            idx = [k for k, l in enumerate(lines) if l.strip() in want]
            vars_ = [(f"L{k + 1}:{tag}", "\n".join(v)) for k in idx for tag, v in mutate(lines, k)]
            res = pool.map(_judge, [v for _, v in vars_], chunksize=1)
            ranked = sorted(zip(res, (t for t, _ in vars_)), key=lambda x: (x[0][0], x[1]))
            for (d, s, m, v), tag in ranked[:5]:
                print(f"  round {rnd + 1} {tag:18s} {d} diffs {s} B" + ("  MATCH" if m else ""))
            (d, s, m, v), tag = ranked[0] if ranked else (best, "none")
            if m:
                (out / "match.c").write_text(head + v, encoding="utf-8")
                print(f"MATCH -> {out / 'match.c'} (check semantics + relcheck)")
                return
            if d >= best[0]:
                break
            best = (d, s, m, v)
            (out / f"r{rnd + 1}.c").write_text(head + v, encoding="utf-8")
            # follow moved lines: keep wanting the same statement texts
    print(f"best {best[0]} diffs")


if __name__ == "__main__":
    main()
