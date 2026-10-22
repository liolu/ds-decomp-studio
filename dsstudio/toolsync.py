"""One version of the matching tools for every game.

The single source is `studio/gametools/`. The tools read everything game-specific (version, ROM name, main .text
range) from the project through `tools/project.py`, so they are byte-identical in every game. A game's repo only
keeps the BUILD_TOOLS (configure, ROM rebuild, `match.py verify`/`progress`, `probe_compiler.py`), so a clone of one
game builds and verifies on its own; every other tool (auto_match, clone_match, workbench...) runs from
studio/gametools/ with cwd = the game (`config.game_tool`). `sync --slim` removes those old copies from a game.
Per-game settings live in <project>/game.toml (read by the shared tools/configure.py). Update protocol: `studio.py sync-tools`
copies the tools, then refreshes README progress + ByteMatch report of each published game (`--no-progress` to skip).
"""
import hashlib
import shutil
import time

from . import config, games, gitutil

SOURCE = config.STUDIO / "gametools"
PER_GAME: set[str] = set()  # nothing: per-game settings live in <project>/game.toml
# what a game needs to build the ROM, verify it and publish its progress (configure.py imports or runs the rest)
BUILD_TOOLS = {"configure.py", "project.py", "get_platform.py", "ninja_syntax.py", "reloc_fixes.py",
               "download_tool.py", "m2ctx.py", "banner_fix.py", "rom_build.py", "sha1.py", "transform_dep.py",
               "match.py", "pipeline_lock.py", "probe_compiler.py"}


def tool_names() -> list[str]:
    return sorted(p.name for p in SOURCE.glob("*.py") if p.name in BUILD_TOOLS and p.name not in PER_GAME)


def studio_only(g) -> list[str]:
    """Copies of studio-only tools still in the game's tools/ (they run from gametools/ now)."""
    return sorted(p.name for p in (g.path / "tools").glob("*.py")
                  if p.name not in BUILD_TOOLS and (SOURCE / p.name).exists())


def adapted(g, name: str) -> str | None:
    """Content the game should have (kept for the callers of the previous, per-game version)."""
    p = SOURCE / name
    return p.read_text(encoding="utf-8") if p.exists() else None


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


_status_cache: dict = {}


def _stamp(p) -> tuple:
    try:
        st = p.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def status(g) -> dict:
    """{'behind': [tools whose content differs from gametools/]}. Files are only read again when their date or
    size changed (the overview asks for every game on each refresh)."""
    if not g.ready:
        return {"behind": []}
    names = tool_names()
    key = (g.id,) + tuple(_stamp(g.path / "tools" / n) + _stamp(SOURCE / n) for n in names)
    if key not in _status_cache:
        _status_cache[key] = _status(g, names)
    return _status_cache[key]


def _status(g, names) -> dict:
    behind = []
    for name in names:
        cur = g.path / "tools" / name
        if not cur.exists() or _norm(cur.read_bytes()) != _norm((SOURCE / name).read_bytes()):
            behind.append(name)
    return {"behind": behind}


def template_version() -> str:
    h = hashlib.sha1()
    for name in tool_names():
        h.update(_norm((SOURCE / name).read_bytes()))
    return h.hexdigest()[:8]


def sync(g, commit=True, push=True, log=print, slim=False) -> dict:
    """Copies the build tools of gametools/ into the game; slim=True also removes the game's copies of the studio-only
    tools. Replaced or removed files are kept in build/tools_backup/<date>/."""
    changed = status(g)["behind"]
    retired = studio_only(g) if slim else []
    if changed or retired:
        backup = g.path / "build" / "tools_backup" / time.strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        for name in changed + retired:
            cur = g.path / "tools" / name
            if cur.exists():
                shutil.copy2(cur, backup / name)
            if name in retired:
                cur.unlink()
            else:
                cur.write_bytes(_norm((SOURCE / name).read_bytes()))
        if changed:
            log(f"{g.id}: {', '.join(changed)} mis a jour (anciens fichiers dans {backup.relative_to(g.path)})")
        if retired:
            log(f"{g.id}: {len(retired)} outil(s) retire(s), ils tournent depuis studio/gametools/ "
                f"(copies dans {backup.relative_to(g.path)})")
    # Commit every shared tool that differs from the last commit (also copies made earlier without a commit)
    names = tool_names() + retired
    dirty = set(gitutil.git(g.path, "status", "--porcelain", "--", *[f"tools/{n}" for n in names])
                .stdout.replace("\\", "/").split())
    changed = [n for n in names if f"tools/{n}" in dirty]
    if not changed:
        return {"ok": True, "changed": []}
    if commit:
        paths = [f"tools/{n}" for n in changed]
        gitutil.git(g.path, "add", "-A", "--", *paths)
        what = f"sync {', '.join(n for n in changed if n not in retired)}" if set(changed) - set(retired) else ""
        if retired:
            what = (what + "; " if what else "") + f"remove {len(retired)} tools that now run from studio/gametools"
        r = gitutil.git(g.path, "commit", "-q", "-m",
                        f"tools: {what} (ds-decomp-studio/gametools {template_version()})",
                        "--", *paths)
        if r.returncode:
            return {"error": r.stderr.strip()[-300:], "changed": changed}
        if push and g.remote():
            err = gitutil.push(g.path)
            if err:
                return {"ok": True, "changed": changed, "warning": f"push : {err}"}
    return {"ok": True, "changed": changed}


def sync_all(log=print) -> list:
    return [{"game": g.id, **sync(g, log=log)} for g in games.all_games() if g.ready]
