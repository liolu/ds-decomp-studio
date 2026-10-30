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


def query(game_id: str, key: str, mode: str = "users", module: str = "", top: int = 40) -> dict:
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
