"""a13 helper: judge one function file with several profiles, print a one-line summary per profile.

Usage (from the project dir): python a13_jd.py NAME FILE.c [PROFILE ...]
Default profiles: 1.2/sp2p3, 2.0/sp1p5, 1.2/sp3. Stops at the first match.
"""
import json
import os
import subprocess
import sys

G = os.path.dirname(os.path.abspath(__file__)) + "/.."


def main():
    name, path = sys.argv[1], sys.argv[2]
    profiles = sys.argv[3:] or ["1.2/sp2p3", "2.0/sp1p5", "1.2/sp3"]
    for prof in profiles:
        out = subprocess.run(
            [sys.executable, os.path.join(G, "workbench.py"), "judge", name, path, "--profile", prof],
            capture_output=True, text=True, cwd=os.getcwd(),
        ).stdout
        try:
            d = json.loads(out[out.index("{"):])
        except ValueError:
            print(prof, "PARSE ERROR", out[-300:])
            continue
        print(prof, "status", d.get("status"), "diffs", d.get("diffs"), "size", d.get("size"), "target", d.get("target_size"))
        if d.get("match"):
            print("MATCH", prof)
            return
        if d.get("status") == "size" or "diff" not in d:
            continue


if __name__ == "__main__":
    main()
