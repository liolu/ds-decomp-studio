"""Paths and settings of DS Decomp Studio.

The studio lives in `<workspace>/studio/`; the workspace is the DS toolbox folder that contains `projets/`, `roms/`,
`tools/`, `env.sh` and `fpdb.sqlite`. Override with the environment variable DSSTUDIO_ROOT.
"""
import json
import os
import shutil
from pathlib import Path

STUDIO = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("DSSTUDIO_ROOT", STUDIO.parent)).resolve()
PROJETS = ROOT / "projets"
# The single repository of every game (github.com/liolu/All-nds-decomp-games): games/<LETTER>/<game>/, one shared
# tools/ at its root. Games with outside contributors stay their own repository in projets/<game>/.
MONOREPO = Path(os.environ.get("DS_MONOREPO", ROOT / "All-nds-decomp-games")).resolve()
MONO_GAMES = MONOREPO / "games"
MONO_TOOLS = MONOREPO / "tools"
ARCHIVE = PROJETS / "_archive"
ANALYSE = PROJETS / "_analyse"
ROMS = ROOT / "roms"
TOOLS = ROOT / "tools"
FPDB = ROOT / "fpdb.sqlite"
ENV_SH = ROOT / "env.sh"
DATA = STUDIO / "data"  # local state, never committed
WEB = STUDIO / "web"
WORKERS = STUDIO / "workers"
# The matching tools: only the build tools are copied into a game's tools/ (toolsync.BUILD_TOOLS), the others run
# from here with cwd = the game (gametools/project.py finds it)
GAMETOOLS = STUDIO / "gametools"


def game_tool(game_path: Path, name: str) -> Path:
    """The studio's copy of a matching tool (also for games that still carry an old copy in tools/), else the game's
    own tool (tools that exist only in that game), else the shared tools/ of All-nds-decomp-games."""
    shared = GAMETOOLS / name
    if shared.exists():
        return shared
    own = Path(game_path) / "tools" / name
    return own if own.exists() or not in_monorepo(game_path) else MONO_TOOLS / name


def letter(slug: str) -> str:
    """Folder of a game in All-nds-decomp-games/games/: first letter in capitals, `0-9` for a digit."""
    c = slug[:1].upper()
    return c if "A" <= c <= "Z" else "0-9"


def in_monorepo(path) -> bool:
    try:
        Path(path).resolve().relative_to(MONO_GAMES)
        return True
    except ValueError:
        return False


def build_tools(game_path: Path) -> Path:
    """Folder of the game's build tools (configure.py, match.py...): <game>/tools/ or All-nds-decomp-games/tools/."""
    return MONO_TOOLS if in_monorepo(game_path) else Path(game_path) / "tools"


def build_tool(game_path: Path, name: str) -> str:
    """A build tool as written in a command run with cwd = the game: tools/x.py or ../../../tools/x.py."""
    return Path(os.path.relpath(build_tools(game_path) / name, Path(game_path).resolve())).as_posix()


def game_dirs() -> list[Path]:
    """Every game folder: projets/<game> (own repositories, local copies) and All-nds-decomp-games/games/<L>/<game>."""
    out = []
    for parent in [PROJETS] + (sorted(d for d in MONO_GAMES.iterdir() if d.is_dir()) if MONO_GAMES.exists() else []):
        if parent.exists():
            out += [d for d in parent.iterdir()
                    if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "config").exists()]
    return sorted(out, key=lambda d: d.name)


def game_path(game_id: str) -> Path:
    """Folder of a game id: projets/<id> if it exists, else All-nds-decomp-games/games/<L>/<id>."""
    p = PROJETS / game_id
    return p if p.is_dir() else MONO_GAMES / letter(game_id) / game_id
PORT = int(os.environ.get("DSSTUDIO_PORT", "8765"))

DATA.mkdir(exist_ok=True)
SETTINGS_FILE = DATA / "settings.json"

# Folder of each game in the studio repo: everything the studio writes inside a game repo goes there
STUDIO_DIR = ".studio"
BLOCK_SIZE = 50
CLAIM_HOURS = 48  # a claimed block nobody touched for this long goes back to the queue


def _find_bash():
    for p in (ROOT.parent.parent / "Git" / "bin" / "bash.exe", Path("C:/Program Files/Git/bin/bash.exe"),
              Path("C:/Program Files (x86)/Git/bin/bash.exe")):
        if p.exists():
            return p
    w = shutil.which("bash")
    return Path(w) if w and "System32" not in w else None


BASH = _find_bash()

DEFAULTS = {
    "who": os.environ.get("USERNAME", "moi"),  # name used for claims
    "github_owner": "",                          # filled from `gh` on first publish
    "qwen_model": "qwen9-ctx",
    "qwen_minutes": 5,
    "qwen_agents": 4,                            # functions worked on at once (Ollama needs OLLAMA_NUM_PARALLEL >= this)
    "qwen_variants": 4,                          # versions asked in one answer, compiled in parallel
    "qwen_group": 6,                             # small functions sent in one request (1 = never batch)
    "qwen_small_model": "",                      # first pass on easy functions (e.g. qwen-ctx = qwen3.5 4b); "" = none
    "qwen_hard_model": "",                       # model for the "difficile" queue (a bigger one); "" = qwen_model
    "qwen_backend": "ollama",                    # or "openai": llama.cpp server (workers/llm_server.py) / vLLM
    "qwen_server": "http://127.0.0.1:8080",      # URL of the OpenAI-compatible server
    "favorites": [],                             # game ids starred in the Jeux tab (shown first)
    "max_parallel_jobs": 2,
    "active_game": "",
    "push_claims": True,                         # claims are pushed to GitHub when the game has a remote
}


def settings() -> dict:
    try:
        s = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    return {**DEFAULTS, **s}


def _typed(k, v):
    """v with the type of the default value of k, or KeyError-free None when it cannot be (kept as before)."""
    d = DEFAULTS[k]
    if isinstance(d, bool):
        return bool(v)
    if isinstance(d, int):
        return int(v)
    if isinstance(d, float):
        return float(v)
    if isinstance(d, list):
        return [str(x) for x in v] if isinstance(v, list) else None
    if isinstance(d, str):
        return None if v is None else str(v)
    return v


def save_settings(changes: dict) -> dict:
    s = settings()
    for k, v in changes.items():
        if k not in DEFAULTS:
            continue
        try:
            v = _typed(k, v)
        except (TypeError, ValueError):
            v = None
        if v is not None:
            s[k] = v
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)
    return s
