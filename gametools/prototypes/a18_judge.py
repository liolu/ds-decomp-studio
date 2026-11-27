"""a18 helper: run workbench judge on NAME's C file and print a compact summary
(status, diffs, size and the differing lines only). Usage: python a18_judge.py NAME FILE PROFILE"""
import json, subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
gt = os.path.dirname(here)
name, path, prof = sys.argv[1], sys.argv[2], sys.argv[3]
r = subprocess.run([sys.executable, os.path.join(gt, "workbench.py"), "judge", name, path, "--profile", prof],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
js = [l for l in r.stdout.splitlines() if l.startswith("{")]
if not js:
    print(name, "NO JSON:", (r.stdout + r.stderr)[-600:]); sys.exit()
d = json.loads(js[-1])
print(name, prof, d.get("status"), "diffs", d.get("diffs"), "size", d.get("size"), "/", d.get("target_size"))
if d.get("diff") is None:
    e = d.get("errors") or str(d)
    msgs = []
    lines_e = e.splitlines()
    for i, l in enumerate(lines_e):
        if "Error:" in l and i + 1 < len(lines_e):
            nxt = lines_e[i + 1].strip().lstrip("#").strip()
            if nxt and "^" not in nxt:
                msgs.append(nxt)
            src = [x for x in lines_e[max(0, i - 2):i] if x.strip().startswith("#") and ":" in x[:12]]
            msgs.extend(x.strip()[:90] for x in src[:1])
    print("ERR:", " || ".join(msgs)[:500] or e[:200]); sys.exit()
lines = d["diff"].splitlines()
starred = [l for l in lines if "*" in l[:12]]
for l in starred[:14]:
    print(l)
if len(starred) > 14: print("...", len(starred) - 14, "more")
