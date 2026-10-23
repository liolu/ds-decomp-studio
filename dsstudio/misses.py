"""What the miss database (gametools/missdb.py, decomp ds/missdb.sqlite) holds, for the web app. Read only."""
import sqlite3
import threading
import time

from . import config

DB = config.ROOT / "missdb.sqlite"
STATS_TTL = 30  # seconds: an older value is still answered at once, and recomputed in the background
FIRST_WAIT = 1.0  # seconds a game page waits for the very first value before showing the page without it

# The counts scan every miss of the game (26 000+ for Heroes of Mana, in a 130 MB file a running workbench keeps
# writing to): 0 to 3 s per call, sometimes far more. A game page must never wait for that.
_stats: dict = {}  # game id -> (time, value)
_busy: dict = {}  # game id -> threading.Event set when the running refresh ends
_lock = threading.Lock()


def _query(game_id: str) -> dict:
    if not DB.exists():
        return {"misses": 0}
    try:
        c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=5)
        n, fp, funcs = c.execute("SELECT COUNT(*), COUNT(fp_exact), COUNT(DISTINCT func) FROM misses WHERE game = ?",
                                 (game_id,)).fetchone()
        won_here = c.execute("SELECT COUNT(*) FROM wins WHERE game = ?", (game_id,)).fetchone()[0]
        given = c.execute("SELECT COUNT(*) FROM wins w JOIN misses m ON m.id = w.miss_id WHERE m.game = ? "
                          "AND w.game != ?", (game_id, game_id)).fetchone()[0]
        by = dict(c.execute("SELECT source, COUNT(*) FROM misses WHERE game = ? GROUP BY source", (game_id,)))
        c.close()
    except sqlite3.Error as e:
        return {"misses": 0, "error": str(e)}
    return {"misses": n, "replayable": fp, "functions": funcs, "won_here": won_here, "given": given, "by": by}


def _refresh(game_id: str, done: threading.Event):
    try:
        _stats[game_id] = (time.time(), _query(game_id))
    finally:
        with _lock:
            _busy.pop(game_id, None)
        done.set()


def stats(game_id: str) -> dict:
    """Misses recorded for this game, how many can be replayed, matches they gave here (from any game) and
    matches this game's misses gave elsewhere. Served from memory, recomputed in the background; {} while the
    first value is not there yet."""
    hit = _stats.get(game_id)
    if hit and time.time() - hit[0] < STATS_TTL:
        return hit[1]
    with _lock:
        done = _busy.get(game_id)
        if done is None:
            done = _busy[game_id] = threading.Event()
            threading.Thread(target=_refresh, args=(game_id, done), daemon=True).start()
    if hit:
        return hit[1]
    done.wait(FIRST_WAIT)
    return _stats.get(game_id, (0, {}))[1]
