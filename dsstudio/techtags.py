"""Tags of every function of every game (gametools/techtag.py, decomp ds/techtags.sqlite), for the web app. Read only:
the job "techtag" rebuilds the file (written aside, then swapped in)."""
import importlib.util
import json
import sqlite3
import threading
import time

from . import config

_spec = importlib.util.spec_from_file_location("techtag", config.GAMETOOLS / "techtag.py")
tt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tt)  # by file path: gametools/ must not go on sys.path (its project.py / auto_match.py)

DB = tt.DB
_cache: dict = {}  # overview, keyed by the file's mtime (the build replaces the file)
_lock = threading.Lock()


def _con():
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=10)


def overview() -> dict:
    """Totals, tags, biggest cross-game families, feature -> technique table. {} before the first build."""
    if not DB.exists():
        return {"built": 0}
    mt = DB.stat().st_mtime
    with _lock:
        if _cache.get("mtime") == mt:
            return _cache["value"]
        c = _con()
        meta = dict(c.execute("SELECT k, v FROM meta"))
        n, m = c.execute("SELECT COUNT(*), SUM(matched) FROM funcs").fetchone()
        tags = [dict(zip(("tag", "n", "matched", "games"), r)) for r in
                c.execute("SELECT tag, n, matched, games FROM tagcount WHERE tag NOT LIKE 'prof:%' ORDER BY n DESC")]
        fams = [dict(zip(("fam", "level", "members", "matched", "games", "size", "techs", "sample"), r)) for r in
                c.execute("SELECT * FROM families WHERE games > 1 ORDER BY (members - matched) * (matched > 0) DESC, "
                          "members DESC LIMIT 300")]
        for f in fams:
            f["techs"], f["sample"] = json.loads(f["techs"]), json.loads(f["sample"])
        tf = [dict(zip(("feat", "tech", "n_feat", "n_both", "p", "lift"), r)) for r in
              c.execute("SELECT * FROM techfeat WHERE n_both >= 10 AND lift >= 2 ORDER BY lift DESC LIMIT 60")]
        per_game = [dict(zip(("game", "functions", "matched", "hinted"), r)) for r in c.execute(
            "SELECT f.game, COUNT(*), SUM(f.matched), COUNT(DISTINCT w.fid) FROM funcs f "
            "LEFT JOIN why w ON w.fid = f.id GROUP BY f.game ORDER BY f.game")]
        c.close()
        v = {"built": float(meta.get("built", 0)), "seconds": meta.get("seconds"), "functions": n, "matched": m,
             "tags": tags, "families": fams, "techfeat": tf, "games": per_game}
        _cache.update(mtime=mt, value=v)
        return v


def function(game: str, name: str) -> dict:
    if not DB.exists():
        return {"error": "pas encore d'index : lance la tache techtag"}
    c = _con()
    try:
        return tt.function(c, game, name) or {"error": f"{game}/{name} absent de l'index"}
    finally:
        c.close()


def family(fam: str, limit: int = 400) -> dict:
    col = {"s": "shape", "k": "skel"}.get(fam[:1])
    if not col or not DB.exists():
        return {"error": "famille inconnue"}
    c = _con()
    rows = c.execute(f"SELECT game, name, matched, size, module, mode, path, tags FROM funcs WHERE {col} = ? "
                     "ORDER BY matched DESC, game, addr LIMIT ?", (fam[2:], limit)).fetchall()
    c.close()
    return {"fam": fam, "level": "shape" if col == "shape" else "skel", "members": [
        {"game": g, "name": n, "matched": m, "size": s, "module": mod, "mode": md, "path": p,
         "tags": [t for t in tg.split() if t.startswith(("tech:", "try:", "prof:", "src:"))]}
        for g, n, m, s, mod, md, p, tg in rows]}


def find(tag: str, game: str = "", todo: bool = False, limit: int = 500) -> dict:
    if not DB.exists():
        return {"rows": []}
    c = _con()
    rows = tt.find(c, tag.strip(), game, todo, limit)
    c.close()
    return {"rows": [dict(zip(("game", "name", "size", "matched", "module", "mode"), r)) for r in rows],
            "limit": limit}


def todo(game: str, tech: str = "", limit: int = 400) -> dict:
    if not DB.exists():
        return {"rows": []}
    c = _con()
    rows = tt.todo(c, game, tech, limit)
    c.close()
    return {"rows": [dict(zip(("name", "size", "module", "mode", "tag", "score", "why"), r)) for r in rows]}


def age() -> float:
    return time.time() - DB.stat().st_mtime if DB.exists() else -1
