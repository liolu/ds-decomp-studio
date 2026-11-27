"""a18 helper: write the m2c draft of each NAME to build/hunt/r3/a18/NAME.c (only if absent).
Usage: python a18_draft.py NAME [NAME ...]  -- run from the Sims 2 project dir."""
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
gt = os.path.dirname(here)
out = os.path.join("build", "hunt", "r3", "a18")
os.makedirs(out, exist_ok=True)
for name in sys.argv[1:]:
    r = subprocess.run([sys.executable, os.path.join(gt, "workbench.py"), "info", name],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not line:
        print(name, "no info"); continue
    d = json.loads(line[-1])
    dst = os.path.join(out, name + ".c")
    if os.path.exists(dst):
        print(name, "exists"); continue
    draft = d.get("draft") or "/* no draft */\n"
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(draft)
    print(name, "written", len(draft))
