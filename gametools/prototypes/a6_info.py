"""Print compact asm + calls + data for a list of function names (agent a6 helper)."""
import json
import subprocess
import sys

G = "../../studio/gametools"
for name in sys.argv[1:]:
    out = subprocess.run([sys.executable, G + "/workbench.py", "info", name], capture_output=True, text=True, encoding="utf-8").stdout
    d = json.loads(out[out.index("{"):])
    print("==", d["name"], d["size"], "calls", d["calls"], "data", d["data"])
    print("\n".join(d["lines"]))
