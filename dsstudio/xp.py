"""XP, levels, loot and achievements (taken over from the old dashboard; its save.json is imported once)."""
import json
import shutil
import threading
import time

from . import config, games

SAVE = config.DATA / "save.json"
OLD_SAVE = config.ROOT / "dashboard" / "save.json"
RANKS = ["Stagiaire", "Apprenti reverser", "Disassembleur", "Compilateur", "Matcheur", "Chasseur de bytes",
         "Maitre du permuter", "Archimage ARM", "Legende du decomp"]
ACHIEVEMENTS = [
    ("first", "Premier sang : 1 fonction matchee", lambda s: s["matched"] >= 1),
    ("f100", "Centurion : 100 fonctions", lambda s: s["matched"] >= 100),
    ("f1000", "Millenaire : 1000 fonctions", lambda s: s["matched"] >= 1000),
    ("f5000", "Titan : 5000 fonctions", lambda s: s["matched"] >= 5000),
    ("f10000", "Colosse : 10000 fonctions", lambda s: s["matched"] >= 10000),
    ("p25", "25 % du code d'un jeu", lambda s: s["best_pct"] >= 25),
    ("p50", "Mi-parcours : 50 %", lambda s: s["best_pct"] >= 50),
    ("p100", "100 % : jeu termine", lambda s: s["best_pct"] >= 100),
    ("block1", "Premier bloc de 50 termine", lambda s: s["blocks_done"] >= 1),
    ("block10", "Dix blocs termines", lambda s: s["blocks_done"] >= 10),
    ("legend", "Legendaire : une fonction de 512+ octets", lambda s: s["legendary"] >= 1),
    ("multi", "Multi-jeux : 10 projets", lambda s: s["projects"] >= 10),
]
_lock = threading.RLock()
_last: dict = {}  # stamp of the previous update -> its result: nothing changed = no work, no 700 KB save.json write


def rarity(size):
    return "legendaire" if size >= 512 else "epique" if size >= 128 else "rare" if size >= 32 else "commun"


def fn_xp(size, shared):
    xp = 10 + min(size // 8, 200)
    return xp * 2 if shared >= 2 else xp


def level_of(xp):
    lvl, need = 1, 100
    while xp >= need:
        xp -= need
        lvl += 1
        need = int(100 * lvl ** 1.4)
    return lvl, xp, need


def _load():
    if not SAVE.exists() and OLD_SAVE.exists():
        shutil.copyfile(OLD_SAVE, SAVE)
    try:
        return json.loads(SAVE.read_text(encoding="utf-8"))
    except Exception:
        return {"xp": 0, "games": {}, "events": [], "achievements": {}}


def update(blocks_done=0) -> dict:
    """Rewards the functions matched since the last call (whoever matched them)."""
    with _lock:
        tables = [(g, *g._functions_and_summary()) for g in games.all_games() if g.ready]
        stamp = (blocks_done,) + tuple((g.id, games._cache[("fns", g.id)][0]) for g, _r, _s in tables)
        if _last.get("stamp") == stamp:
            return _last["result"]
        save = _load()
        stats = {"matched": 0, "best_pct": 0.0, "legendary": 0, "projects": 0, "blocks_done": blocks_done}
        events, gain = [], 0
        for g, rows, s in tables:
            now = {r["uid"] for r in rows if r["done"]}
            gs = save["games"].setdefault(g.id, {"known": None})
            if gs["known"] is None:
                x = sum(fn_xp(r["size"], r["shared"]) for r in rows if r["done"])
                gain += x
                if now:
                    events.append({"t": time.time(), "kind": "info", "text": f"{g.title} : {len(now)} fonctions = +{x} XP"})
            else:
                known = set(gs["known"])
                for r in rows:
                    if r["done"] and r["uid"] not in known:
                        x = fn_xp(r["size"], r["shared"])
                        gain += x
                        events.append({"t": time.time(), "kind": "loot", "game": g.id, "name": r["name"],
                                       "size": r["size"], "rarity": rarity(r["size"]), "xp": x})
            gs["known"] = sorted(now, key=str)
            stats["matched"] += s["matched"]
            stats["best_pct"] = max(stats["best_pct"], s["pct_code"])
            stats["projects"] += 1
            stats["legendary"] += sum(1 for r in rows if r["done"] and r["size"] >= 512)
        save["xp"] = save.get("xp", 0) + gain
        save["events"] = (events[:200] + save.get("events", []))[:300]
        for aid, label, test in ACHIEVEMENTS:
            if aid not in save.setdefault("achievements", {}) and test(stats):
                save["achievements"][aid] = time.time()
                save["events"].insert(0, {"t": time.time(), "kind": "achievement", "text": label})
        SAVE.write_text(json.dumps(save, ensure_ascii=False), encoding="utf-8")
        lvl, cur, need = level_of(save["xp"])
        _last["stamp"] = stamp
        _last["result"] = {"level": lvl, "xp": save["xp"], "xp_in_level": cur, "xp_needed": need,
                "rank": RANKS[min(lvl // 5, len(RANKS) - 1)], "stats": stats, "events": save["events"][:50],
                "achievements": [{"id": a, "label": l, "unlocked": a in save["achievements"]} for a, l, _ in ACHIEVEMENTS]}
        return _last["result"]
