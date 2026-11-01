"""Cross-references for the "Data" tab: gametools/xref.py on one game (who uses a symbol, table slots, siblings).
Read only; the index of a game is kept until its symbols/relocs/delinks change."""
import importlib.util
import threading

from . import config, games

_spec = importlib.util.spec_from_file_location("xref", config.GAMETOOLS / "xref.py")
xr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xr)  # by file path: gametools/ must not go on sys.path (its project.py)

_cache: dict = {}  # game id -> Index
_lock = threading.Lock()


def _index(game_id: str):
    with _lock:
        ix = _cache.get(game_id)
        if ix is None or ix.stamp() != ix.built:
            ix = xr.Index(games.get(game_id).cfg)
            ix.built = ix.stamp()
            _cache[game_id] = ix
        return ix


_rspec = importlib.util.spec_from_file_location("romarc", config.GAMETOOLS / "romarc.py")
ra = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(ra)


def query(game_id: str, key: str, mode: str = "users", module: str = "", top: int = 40) -> dict:
    if mode == "archive":  # rom.bin-style index archive: loaders, file number -> functions (romarc.py users)
        ix, g = _index(game_id), games.get(game_id)
        if getattr(ix, "archive_cache", None) is None:
            import sys
            sys.modules.setdefault("xref", xr)  # romarc imports xref by name
            ix.archive_cache = ra.users(g.path, g.version, g.cfg)
        res = ix.archive_cache
        if "error" in res:
            return {**res, "mode": mode}
        k = key.strip().lower()
        files = {n: us for n, us in res["files"].items()
                 if not k or k == n or any(k in u["function"].lower() or k in u["how"].lower() for u in us)}
        return {**res, "files": files, "mode": mode}
    if mode == "files":  # ROM file paths found as strings + who loads them (key = filter)
        ix = _index(game_id)
        if getattr(ix, "files_cache", None) is None:
            ix.files_cache = xr.files(ix, games.get(game_id).cfg)
        res = ix.files_cache
        k = key.lower()
        rows = [r for r in res["rows"] if not k or k in r["string"].lower() or any(k in f.lower() for f in r["files"])]
        return {**res, "rows": rows, "mode": mode}
    if mode not in ("users", "table", "siblings"):
        raise KeyError(f"mode inconnu : {mode}")
    return xr.query(_index(game_id), key, mode, module, top)
