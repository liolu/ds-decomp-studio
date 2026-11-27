"""Print the differing (*) lines of a judge JSON file, compactly.

Usage: python a8_showdiff.py JUDGE.json [JUDGE2.json ...]
Prints the status, diff count and each line marked with '*' (target | candidate).
"""
import json
import re
import sys

for path in sys.argv[1:]:
    raw = open(path, encoding="utf-8").read()
    start = raw.find("{")
    try:
        d = json.loads(raw[start:])
    except ValueError:
        print(path, "NOPARSE", raw[-200:])
        continue
    print("==", path.split("/")[-1], d.get("profile"), "diffs", d.get("diffs"), d.get("status"))
    for ln in d.get("diff", "").splitlines():
        if re.match(r"\s*\d+ \*", ln) or re.match(r"\s*\* ", ln) or ln.lstrip().startswith("*"):
            print("   ", ln)
