"""Batch helper for hunt agent a5: write the m2c draft (or a given C file) of each
function to build/hunt/r3/a5/NAME.c and judge it with workbench.py (profile arg).

Usage: python a5_draft_judge.py PROFILE NAME [NAME ...]
Only uses workbench.py info/judge, so misses are recorded as usual.
"""
import json
import subprocess
import sys

G = "../../studio/gametools"
PY = sys.executable


def main():
    profile = sys.argv[1]
    for name in sys.argv[2:]:
        info = subprocess.run([PY, G + "/workbench.py", "info", name],
                              capture_output=True, text=True).stdout
        start = info.find("{")
        data = json.loads(info[start:])
        draft = data.get("draft") or ""
        path = "build/hunt/r3/a5/%s.c" % name
        with open(path, "w", encoding="ascii", errors="replace") as f:
            f.write(draft)
        out = subprocess.run([PY, G + "/workbench.py", "judge", name, path,
                              "--profile", profile], capture_output=True, text=True).stdout
        print(name, out.strip().splitlines()[-1] if out.strip() else "no output")


if __name__ == "__main__":
    main()
