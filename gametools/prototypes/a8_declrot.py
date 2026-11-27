"""a8_declrot.py FILE.c PROFILE NAME [N] : judge up to N rotations (default 3) of the leading local declaration
block of the function body, plus the swap of the first two declarations. Writes FILE_rot<k>.c and prints diff counts.
Usage from the project dir. Technique id: decl-order (rotation variant of decl-reverse)."""
import re
import subprocess
import sys
from pathlib import Path

src_path, prof, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 3
lines = src_path.read_text(encoding="utf-8").split("\n")
decl_re = re.compile(r"^(\s+)[\w ]+?[\s\*]+\w+(\[\w*\])?;\s*$")
start = next((i + 1 for i, l in enumerate(lines) if re.match(r"^[\w\s\*]+\(.*\)\s*\{\s*$", l)), None)
idx, i = [], start
while i < len(lines) and decl_re.match(lines[i]) and "=" not in lines[i]:
    idx.append(i)
    i += 1
if len(idx) < 2:
    sys.exit("fewer than two declarations")
block = [lines[k] for k in idx]
variants = []
for r in range(1, len(block)):
    variants.append(("rot%d" % r, block[r:] + block[:r]))
variants.append(("swap01", [block[1], block[0]] + block[2:]))
best = None
for tag, blk in variants[:n]:
    new = lines[:]
    for k, l in zip(idx, blk):
        new[k] = l
    out = src_path.with_name(src_path.stem + "_" + tag + ".c")
    out.write_text("\n".join(new), encoding="utf-8")
    res = subprocess.run([sys.executable, "../../studio/gametools/workbench.py", "judge", name, str(out), "--profile", prof],
                         capture_output=True, text=True).stdout
    m = re.search(r'"diffs": (\d+)', res)
    d = int(m.group(1)) if m else 999
    print(name, tag, d, flush=True)
