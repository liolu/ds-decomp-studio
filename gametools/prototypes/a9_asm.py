"""Print asm lines, calls, data and callers of functions via workbench info (helper for hunt agents)."""
import json, subprocess, sys
G = sys.argv[1]
for name in sys.argv[2:]:
    out = subprocess.run([sys.executable, G + "/workbench.py", "info", name], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    d = json.loads(out[out.index('{"name"'):])
    print("==", name, "size", d["size"], "profiles", d["profiles"][:2], "asm_only", d["asm_only"])
    print("\n".join("  " + l for l in d["asm"].split("\n")[1:-1]))
    if d["calls"]: print("  CALLS", d["calls"])
    if d["data"]: print("  DATA", d["data"])
    if d["callers"]: print("  CALLERS", d["callers"])
