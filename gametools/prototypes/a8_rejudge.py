"""Re-judge the best= file of each function in an .info list under its profile.

Copies each best file into the agent dir as NAME.c, runs workbench judge
(profile from the .info, else 1.2/sp2p3) and stores the JSON line in
<agent_dir>/judge_<NAME>_<profile-safe>.json. Usage (from project dir):
  python a8_rejudge.py LIST.info AGENT_DIR [PROFILE_OVERRIDE]
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

info, agent = Path(sys.argv[1]), Path(sys.argv[2])
override = sys.argv[3] if len(sys.argv) > 3 else None
G = Path("../../studio/gametools")
agent.mkdir(parents=True, exist_ok=True)
for line in info.read_text(encoding="utf-8").splitlines():
    m = re.match(r"(\S+)\s+size=\S+\s+diffs=\S+\s+profile=(.*?)\s+tags=", line)
    b = re.search(r"best=(\S+)", line)
    if not m or not b or b.group(1) == "-":
        continue
    name, prof = m.group(1), override or m.group(2).strip()
    src = Path(b.group(1))
    dst = agent / f"{name}.c"
    shutil.copy(src, dst)
    out = subprocess.run([sys.executable, str(G / "workbench.py"), "judge", name, str(dst),
                          "--profile", prof], capture_output=True, text=True).stdout
    safe = prof.replace("/", "_").replace(" ", "")
    (agent / f"judge_{name}_{safe}.json").write_text(out, encoding="utf-8")
    d = re.search(r'"diffs": (\d+)', out)
    print(name, prof, d.group(1) if d else out[-200:].replace("\n", " "), flush=True)
