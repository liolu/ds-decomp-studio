"""Engine map: which games share code (studio, SDK, engine) and the memory map of one game."""
import sqlite3
from collections import defaultdict

from . import config, difficulty, games


def memory_map(g) -> dict:
    """Every function of the main module as [addr, size, state, name]; state -1 = matched, else difficulty level."""
    rows = [r for r in g.functions() if r["module"] == "main"]  # one address space (overlays overlap)
    port = games.portable(g)
    out = []
    for r in rows:
        lvl = -1 if r["done"] else difficulty.rate(dict(r), port)["level"]
        out.append([r["addr"], r["size"], lvl, r["name"]])
    return {"functions": out, "start": min((r[0] for r in out), default=0),
            "end": max((r[0] + r[1] for r in out), default=0)}


def cross_games() -> dict:
    """Pairs of indexed games with the number of identical functions, split into SDK (in 5+ games) and engine
    (in 2-4 games: code a studio reused)."""
    if not config.FPDB.exists():
        return {"games": [], "pairs": []}
    con = sqlite3.connect(config.FPDB)
    spread = dict(con.execute("SELECT strict, COUNT(DISTINCT game) FROM fn GROUP BY strict").fetchall())
    by_game = defaultdict(set)
    for game, strict in con.execute("SELECT game, strict FROM fn"):
        by_game[game].add(strict)
    con.close()
    inv = {v: k for k, v in games.FP_KEY.items()}
    keys = sorted(by_game)
    pairs = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            common = by_game[a] & by_game[b]
            if not common:
                continue
            sdk = sum(1 for s in common if spread[s] >= 5)
            pairs.append({"a": inv.get(a, a), "b": inv.get(b, b), "shared": len(common), "sdk": sdk,
                          "engine": len(common) - sdk})
    info = []
    for k in keys:
        gid = inv.get(k, k)
        mine = by_game[k]
        info.append({"id": gid, "key": k, "title": games.TITLES.get(gid, gid), "studio": games.STUDIOS.get(gid, ""),
                     "functions": len(mine), "unique": sum(1 for s in mine if spread[s] == 1),
                     "sdk": sum(1 for s in mine if spread[s] >= 5)})
    pairs.sort(key=lambda p: -p["engine"])
    return {"games": info, "pairs": pairs}


def studios() -> list[dict]:
    """Projects grouped by studio (same studio = often the same engine)."""
    groups = defaultdict(list)
    for g in games.all_games():
        groups[games.STUDIOS.get(g.id, "Inconnu")].append(g.id)
    return [{"studio": s, "games": sorted(v)} for s, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def _best_name(names) -> str:
    """A real symbol name if any game has one, else the first func_XXXX."""
    names = list(names)
    return next((n for n in names if not n.startswith("func_")), names[0] if names else "")


def compare(a: str, b: str) -> dict:
    """Functions identical (strict fingerprint) in games a and b, with their name in each and how many games share them."""
    if not config.FPDB.exists():
        return {"functions": []}
    ka, kb = games.FP_KEY.get(a, a), games.FP_KEY.get(b, b)
    con = sqlite3.connect(config.FPDB)
    rows = con.execute("""SELECT x.strict, x.name, y.name, x.size, x.mode,
                                 (SELECT COUNT(DISTINCT game) FROM fn z WHERE z.strict = x.strict)
                          FROM fn x JOIN fn y ON y.strict = x.strict AND y.game = ?
                          WHERE x.game = ? GROUP BY x.strict ORDER BY x.size DESC""", (kb, ka)).fetchall()
    con.close()
    return {"functions": [{"fp": s, "a": na, "b": nb, "size": sz, "mode": m, "games": n, "sdk": n >= 5}
                          for s, na, nb, sz, m, n in rows]}


def top_functions(limit: int = 300, q: str = "") -> dict:
    """The functions found in the most games (by strict fingerprint)."""
    if not config.FPDB.exists():
        return {"functions": []}
    con = sqlite3.connect(config.FPDB)
    rows = con.execute("""SELECT strict, COUNT(DISTINCT game) n, MAX(size), MAX(mode), GROUP_CONCAT(name, '|')
                          FROM fn GROUP BY strict HAVING n >= 2 ORDER BY n DESC, MAX(size) DESC""").fetchall()
    con.close()
    out = []
    for s, n, sz, m, names in rows:
        name = _best_name(names.split("|"))
        if q and q.lower() not in names.lower():
            continue
        out.append({"fp": s, "name": name, "games": n, "size": sz, "mode": m})
        if len(out) >= limit:
            break
    return {"functions": out, "total_games": len({k for k in games.FP_KEY.values()}) or None}


def function_users(fp: str) -> dict:
    """Every game that contains this function (strict fingerprint), with its name and address there."""
    if not config.FPDB.exists():
        return {"games": []}
    con = sqlite3.connect(config.FPDB)
    rows = con.execute("SELECT game, name, addr, size FROM fn WHERE strict = ? ORDER BY game", (fp,)).fetchall()
    con.close()
    inv = {v: k for k, v in games.FP_KEY.items()}
    return {"name": _best_name(r[1] for r in rows), "size": rows[0][3] if rows else 0,
            "games": [{"id": inv.get(g, g), "title": games.TITLES.get(inv.get(g, g), g), "name": nm, "addr": ad}
                      for g, nm, ad, _ in rows]}
