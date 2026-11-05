"""Functions that look like each other, in one game and across all our games, for the web app.

Source: the tag index (gametools/techtag.py, decomp ds/techtags.sqlite, job "techtag"), two levels:
  shape     the same instruction sequence once registers, immediates and pool words are masked: the same C,
            often with other struct offsets or constants (an exact copy has the same shape and the same size);
  skeleton  the same run of loads / stores / ALU / tests / branches / calls: written the same way, sizes may differ.
Whether a function is matched comes from each game as it is now (Game.functions), not from the index, which is only
as recent as the last techtag run.

The counts of a whole game need every shape of the index: they are computed in the background, answered from
memory, and a page never waits more than FIRST_WAIT for them."""
import collections
import sqlite3
import threading
import time

from . import games, techtags

FIRST_WAIT = 1.0
LIST_LIMIT = 120  # members shown per level in the detail of one function
_index: dict = {}  # "mtime", "by_shape": shape -> [(game, module, addr)], "games": set of indexed games
_counts: dict = {}  # game id -> (index mtime, functions stamp, {(module, addr): counts})
_lock = threading.Lock()
_busy: dict = {}


def _con():
    return sqlite3.connect(f"file:{techtags.DB.as_posix()}?mode=ro", uri=True, timeout=10)


def _mtime() -> float:
    return techtags.DB.stat().st_mtime if techtags.DB.exists() else 0


def _load_index():
    mt = _mtime()
    if _index.get("mtime") == mt:
        return _index
    by_shape = collections.defaultdict(list)
    indexed = set()
    if mt:
        c = _con()
        for game, module, addr, shape in c.execute("SELECT game, module, addr, shape FROM funcs"):
            indexed.add(game)
            if shape:
                by_shape[shape].append((game, module, addr))
        c.close()
    by_shape = {k: v for k, v in by_shape.items() if len(v) > 1}
    _index.clear()
    _index.update(mtime=mt, by_shape=by_shape, games=indexed, shape_of={})
    for shape, members in by_shape.items():
        for m in members:
            _index["shape_of"][m] = shape
    return _index


def _done(game_id: str) -> dict:
    """{(module, addr): source file} of the matched functions of a game, as it is now ({} for an unknown game)."""
    try:
        g = games.get(game_id)
        return {(r["module"], r["addr"]): r["file"] for r in g.functions() if r["done"]}
    except Exception:
        return {}


def _compute(game_id: str) -> dict:
    idx = _load_index()
    done_of = {}

    def done(gid):
        if gid not in done_of:
            done_of[gid] = _done(gid)
        return done_of[gid]

    out = {}
    for (gid, module, addr), shape in idx["shape_of"].items():
        if gid != game_id:
            continue
        here = here_done = other = other_done = 0
        other_games = set()
        for m in idx["by_shape"][shape]:
            if m == (gid, module, addr):
                continue
            ok = (m[1], m[2]) in done(m[0])
            if m[0] == game_id:
                here += 1
                here_done += ok
            else:
                other += 1
                other_done += ok
                other_games.add(m[0])
        out[(module, addr)] = {"here": here, "here_done": here_done, "other": other, "other_done": other_done,
                               "games": len(other_games)}
    return out


def _refresh(game_id: str, ev: threading.Event):
    try:
        mt = _mtime()
        _counts[game_id] = (mt, time.time(), _compute(game_id))
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        with _lock:
            _busy.pop(game_id, None)
        ev.set()


def counts(game_id: str, max_age: float = 600) -> dict:
    """{(module, addr): {"here", "here_done", "other", "other_done", "games"}} for the functions of a game that have
    look-alikes of the same shape. Recomputed in the background when the index changed or after max_age seconds
    (matches made since); {} while the first value is not there yet."""
    hit = _counts.get(game_id)
    if hit and hit[0] == _mtime() and time.time() - hit[1] < max_age:
        return hit[2]
    with _lock:
        ev = _busy.get(game_id)
        if ev is None:
            ev = _busy[game_id] = threading.Event()
            threading.Thread(target=_refresh, args=(game_id, ev), daemon=True).start()
    if hit:
        return hit[2]
    ev.wait(FIRST_WAIT)
    hit = _counts.get(game_id)
    return hit[2] if hit else {}


def busy(game_id: str) -> bool:
    return game_id in _busy


def state(game_id: str) -> dict:
    """Whether the index knows this game and how old it is (the web app proposes the techtag job)."""
    if not techtags.DB.exists():
        return {"indexed": False, "age": -1}
    c = _con()
    n = c.execute("SELECT COUNT(*) FROM funcs WHERE game = ?", (game_id,)).fetchone()[0]
    c.close()
    return {"indexed": n > 0, "functions": n, "age": round(techtags.age())}


def of(game_id: str, name: str = "", module: str = "", addr: int | None = None) -> dict:
    """Look-alikes of one function: {"here": [...], "other": [...]} (each: game, name, size, how, matched, file),
    matched ones first, then the closest (same shape before same skeleton, same size first)."""
    if not techtags.DB.exists():
        return {"error": "pas encore d'index des ressemblances : lance la tache \"Taguer les fonctions de tous les jeux\"",
                "here": [], "other": []}
    c = _con()
    try:
        if addr is not None:
            r = c.execute("SELECT id, module, addr, name, size, shape, skel FROM funcs WHERE game = ? AND module = ? "
                          "AND addr = ?", (game_id, module or "main", addr)).fetchone()
        else:
            r = c.execute("SELECT id, module, addr, name, size, shape, skel FROM funcs WHERE game = ? AND name = ?",
                          (game_id, name)).fetchone()
        if not r:
            st = state(game_id)
            why = ("ce jeu n'est pas encore dans l'index des ressemblances" if not st["indexed"] else
                   "fonction absente de l'index (renommee ou decoupee depuis)")
            return {"error": why + " : lance la tache \"Taguer les fonctions de tous les jeux\"", "here": [], "other": []}
        fid, module, addr, _n, size, shape, skel = r
        seen, rows = {fid}, []
        for col, key, how in (("shape", shape, "meme forme"), ("skel", skel, "meme squelette")):
            if not key:
                continue
            for oid, g, mod, a, n, s in c.execute(f"SELECT id, game, module, addr, name, size FROM funcs WHERE {col} = ? "
                                                  "LIMIT 2000", (key,)):
                if oid in seen:
                    continue
                seen.add(oid)
                rows.append({"game": g, "module": mod, "addr": a, "name": n, "size": s,
                             "how": "meme code" if how == "meme forme" and s == size else how})
    finally:
        c.close()
    done_of = {}
    for x in rows:
        if x["game"] not in done_of:
            done_of[x["game"]] = _done(x["game"])
        f = done_of[x["game"]].get((x["module"], x["addr"]))
        x["matched"], x["file"] = f is not None, f or ""
    rank = {"meme code": 0, "meme forme": 1, "meme squelette": 2}
    rows.sort(key=lambda x: (not x["matched"], rank[x["how"]], abs(x["size"] - size), x["game"], x["addr"]))
    here = [x for x in rows if x["game"] == game_id]
    other = [x for x in rows if x["game"] != game_id]
    return {"module": module, "addr": addr, "size": size, "here": here[:LIST_LIMIT], "other": other[:LIST_LIMIT],
            "n_here": len(here), "n_other": len(other), "games": len({x["game"] for x in other}),
            "matched_here": sum(x["matched"] for x in here), "matched_other": sum(x["matched"] for x in other)}


def source(game_id: str, rel: str) -> dict:
    """Text of a matched function's source file (inside the game's src/ only)."""
    g = games.get(game_id)
    p = (g.path / rel).resolve()
    if (g.path / "src").resolve() not in p.parents or not p.is_file():
        return {"error": "fichier introuvable"}
    return {"game": game_id, "file": rel, "text": p.read_text(encoding="utf-8", errors="replace")[:200_000]}
