"""a22: try every order of the local declarations of a C file.

Usage: python a22_declperm.py NAME SRC.c [PROFILE]
Writes each permutation to build/hunt/r3/a22/<NAME>_perm<k>.c and judges it
with workbench.py (so misses are recorded). Declaration lines are the
lines between the function's opening '{' and its first statement that
end with ';' and do not contain '='.
"""
import itertools, os, re, subprocess, sys

name, src = sys.argv[1], sys.argv[2]
profile = sys.argv[3] if len(sys.argv) > 3 else "1.2/sp2p3"
text = open(src, encoding="ascii").read().split("\n")
start = next(i for i, l in enumerate(text) if l.rstrip().endswith("{") and name in l)
decl = []
i = start + 1
while i < len(text) and re.match(r"\s+[\w\s\*]+\s\*?\w+(\[\d+\])?;\s*$", text[i]) and "=" not in text[i]:
    decl.append(text[i]); i += 1
if len(decl) < 2:
    print("no declarations found"); sys.exit(0)
out_dir = os.path.dirname(src)
here = os.getcwd()
best = None
for k, perm in enumerate(itertools.permutations(decl)):
    lines = text[:start + 1] + list(perm) + text[start + 1 + len(decl):]
    p = os.path.join(out_dir, f"{name}_perm{k}.c")
    open(p, "w", encoding="ascii").write("\n".join(lines))
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "workbench.py"),
                        "judge", name, p, "--profile", profile], capture_output=True, text=True)
    m = re.search(r'"status": "(\w+)".*?"diffs": (\d+)', r.stdout)
    st, d = (m.group(1), int(m.group(2))) if m else ("?", 999)
    print(k, st, d, [x.strip() for x in perm])
    if st == "match":
        print("MATCH", p); break
