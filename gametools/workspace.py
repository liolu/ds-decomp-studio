"""Where the games are: the one place that knows the layout of the DS workspace (decomp ds/).

Two kinds of game folders:
- `projets/<game>/`: a game that is its own git repository (Lego SW II, Sims 2, Nintendogs: outside contributors);
- `All-nds-decomp-games/games/<LETTER>/<game>/`: a game of the single repository github.com/liolu/All-nds-decomp-games
  (`0-9` for names starting with a digit). Its build tools live once in `All-nds-decomp-games/tools/`.

    from workspace import WORKSPACE, game_dirs, find_game, in_monorepo
"""
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("DS_ROOT") or Path(__file__).resolve().parents[2])  # decomp ds/
PROJETS = WORKSPACE / "projets"
MONOREPO = Path(os.environ.get("DS_MONOREPO") or WORKSPACE / "All-nds-decomp-games")
MONO_GAMES = MONOREPO / "games"
MONO_TOOLS = MONOREPO / "tools"
GAMETOOLS = Path(__file__).resolve().parent


def letter(slug: str) -> str:
    """Folder of a game in All-nds-decomp-games/games/: its first letter in capitals, `0-9` for a digit."""
    c = slug[:1].upper()
    return c if "A" <= c <= "Z" else "0-9"


def mono_path(slug: str) -> Path:
    return MONO_GAMES / letter(slug) / slug


def _games_in(folder: Path, require_config: bool):
    if not folder.exists():
        return
    for d in sorted(folder.iterdir()):
        if d.is_dir() and not d.name.startswith(("_", ".")) and (not require_config or (d / "config").exists()):
            yield d


def game_dirs(require_config: bool = True) -> list[Path]:
    """Every game folder: projets/<game> then All-nds-decomp-games/games/<L>/<game>, sorted by name."""
    out = list(_games_in(PROJETS, require_config))
    if MONO_GAMES.exists():
        for sub in sorted(MONO_GAMES.iterdir()):
            if sub.is_dir():
                out += list(_games_in(sub, require_config))
    return sorted(out, key=lambda p: p.name)


def find_game(name: str) -> Path | None:
    """The folder of the game called `name` (projets/ first, then the single repository)."""
    if not name or any(c in name for c in "/\\") or ".." in name:
        return None
    for p in (PROJETS / name, mono_path(name)):
        if p.is_dir():
            return p
    return None


def in_monorepo(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(MONO_GAMES.resolve())
        return True
    except ValueError:
        return False


def repo_root(game: Path) -> Path:
    """The git repository holding the game: All-nds-decomp-games/ or the game folder itself."""
    return MONOREPO if in_monorepo(game) else Path(game)


def build_tools_dir(game: Path) -> Path:
    """Where the game's build tools are (configure.py, match.py...): All-nds-decomp-games/tools/ or <game>/tools/."""
    return MONO_TOOLS if in_monorepo(game) else Path(game) / "tools"


def rel(target: Path, start: Path) -> str:
    """target relative to start, with / (for commands written in briefs and docs)."""
    return Path(os.path.relpath(Path(target).resolve(), Path(start).resolve())).as_posix()
