"""a8_jv.py NAME FILE [PROFILE]: judge a C file with workbench and print a compact summary.

Prints status, diff count, sizes, then only the differing ('*') lines of the diff.
Env A8N limits the number of printed differing lines (default 30). Run from the project dir.
"""
import json
import os
import subprocess
import sys

name, path = sys.argv[1], sys.argv[2]
prof = sys.argv[3] if len(sys.argv) > 3 else "1.2/sp2p3"
wb = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workbench.py")
out = subprocess.run([sys.executable, wb, "judge", name, path, "--profile", prof],
                     capture_output=True, text=True).stdout
for line in out.splitlines():
    if line.startswith("{"):
        d = json.loads(line)
        print(name, d.get("status"), "diffs", d.get("diffs"), "size", d.get("size"), "/", d.get("target_size"), d.get("profile"))
        n = 0
        lim = int(os.environ.get("A8N", "30"))
        for l in d.get("diff", "").splitlines():
            if "*" in l[:6] or "|" in l[:6]:
                print(l)
                n += 1
                if n >= lim:
                    break
        break
else:
    print(out[-1500:])
