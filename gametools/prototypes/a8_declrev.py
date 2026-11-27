"""a8_declrev.py NAME.c PROFILE : write NAME_rev.c with the leading local declaration block of the
function body reversed (one cheap register-order variant), judge it, print the diff count.
Only the declarations before the first statement are touched (no '=' in them, indented 4 or 8 spaces).
Usage from the project dir: python a8_declrev.py FILE.c "1.2/sp2p3" NAME"""
import json
import re
import subprocess
import sys
from pathlib import Path

src_path, prof, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = src_path.read_text(encoding="utf-8").split("\n")
decl_re = re.compile(r"^(\s+)[\w ]+?[\s\*]+\w+(\[\w*\])?;\s*$")
start = None
for i, l in enumerate(lines):
    if re.match(r"^[\w\s\*]+\(.*\)\s*\{\s*$", l):
        start = i + 1
        break
if start is None:
    sys.exit("no function header")
idx = []
i = start
while i < len(lines) and decl_re.match(lines[i]) and "=" not in lines[i]:
    idx.append(i)
    i += 1
if len(idx) < 2:
    sys.exit("fewer than two declarations")
block = [lines[k] for k in idx][::-1]
for k, l in zip(idx, block):
    lines[k] = l
out = src_path.with_name(src_path.stem + "_rev.c")
out.write_text("\n".join(lines), encoding="utf-8")
res = subprocess.run([sys.executable, "../../studio/gametools/workbench.py", "judge", name, str(out), "--profile", prof],
                     capture_output=True, text=True).stdout
m = re.search(r'"diffs": (\d+)', res)
print(name, prof, "rev", m.group(1) if m else res[-120:].replace("\n", " "))
