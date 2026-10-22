"""The environment of `env.sh`, for tools the studio starts without Git Bash (the MCP server, the C editor): the
toolbox's tools, compilers, m2c, the ARM toolchain and the venv on PATH."""
import os
import subprocess
import sys
from pathlib import Path

from . import config

ARM_BIN = Path("C:/Program Files (x86)/Arm GNU Toolchain arm-none-eabi/14.2 rel1/bin")
VENV = config.ROOT / ".venv" / "Scripts"
PYTHON = VENV / "python.exe" if (VENV / "python.exe").exists() else Path(sys.executable)


def env() -> dict:
    e = dict(os.environ)
    tools = config.TOOLS
    extra = [tools, tools / "melonDS", tools / "ghidra_11.2.1_PUBLIC", ARM_BIN, VENV]
    winlibs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in winlibs.glob("BrechtSanders.WinLibs*/mingw64/bin") if winlibs.is_dir() else []:
        extra.append(p)
    e["PATH"] = os.pathsep.join(str(p) for p in extra[:5]) + os.pathsep + e.get("PATH", "") + \
        "".join(os.pathsep + str(p) for p in extra[5:])
    e["MWCCARM"] = str(tools / "mwccarm")
    e["M2C_PATH"] = str(tools / "m2c")
    e["PERMUTER_PATH"] = str(tools / "decomp-permuter")
    e["VIRTUAL_ENV"] = str(VENV.parent)
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def workbench(game_path: Path, *args: str, timeout: float = 3600) -> dict:
    """Runs workbench.py (the game's copy, else studio/gametools/) in a game and returns its JSON answer."""
    import json
    from . import config
    r = subprocess.run([str(PYTHON), str(config.game_tool(game_path, "workbench.py")), *args], cwd=game_path, env=env(), capture_output=True, stdin=subprocess.DEVNULL,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"error": "workbench failed", "output": ((r.stdout or "") + (r.stderr or ""))[-3000:]}
