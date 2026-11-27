"""Judge a C file with workbench and print a one-line summary (diffs, status, size).

Usage: python a14_judge.py NAME FILE "PROFILE" [--diff]
Runs `workbench.py judge` from the project dir and prints diffs/status/size,
plus the diff listing when --diff is given.
"""
import json
import re
import subprocess
import sys


def main():
    name, path, prof = sys.argv[1], sys.argv[2], sys.argv[3]
    cmd = [sys.executable, "../../studio/gametools/workbench.py", "judge", name, path, "--profile", prof]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        print(name, prof, "NO OUTPUT", out[-300:])
        return
    d = json.loads(m.group(0))
    print(name, prof, "diffs", d.get("diffs"), d.get("status"), d.get("size"))
    if "--diff" in sys.argv:
        print(d.get("diff", ""))


if __name__ == "__main__":
    main()
