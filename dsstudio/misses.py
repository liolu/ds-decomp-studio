"""What the miss database (gametools/missdb.py, decomp ds/missdb.sqlite) holds, for the web app. Read only."""
import sqlite3

from . import config

DB = config.ROOT / "missdb.sqlite"


def stats(game_id: str) -> dict:
    """Misses recorded for this game, how many can be replayed, matches they gave here (from any game) and
    matches this game's misses gave elsewhere."""
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
