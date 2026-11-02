"""The DATA of a game for the web app: every data symbol of .data / .rodata / .bss of every module, its size (up to
the next symbol), whether a complete source file covers it, and how many data misses the miss database keeps for it.
Read only: config/*/delinks.txt + symbols.txt (cached until they change) and missdb.sqlite."""
import bisect
import re
import sqlite3

from . import config, games

SECTIONS = (".data", ".rodata", ".bss", ".sbss")
SECTION_RE = re.compile(r"^\s+(\.\w+)\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+) kind:(\w+)", re.M)
SYM_RE = re.compile(r"^(\S+) kind:(\w+)\S* addr:0x([0-9a-f]+)", re.M)
FILE_RE = re.compile(r"^(src/\S+):\n((?:[ \t]+\S.*\n?)+)", re.M)
RANGE_RE = re.compile(r"(\.\w+)\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+)")


def _module_rows(module: str, folder) -> list[dict]:
    head, _, files = (folder / "delinks.txt").read_text(encoding="utf-8", errors="replace").partition("\n\n")
    secs = {m.group(1): (int(m.group(2), 16), int(m.group(3), 16)) for m in SECTION_RE.finditer(head)
            if m.group(1) in SECTIONS}
    done = []
    for path, body in FILE_RE.findall(files):
        if "complete" in body:
            done += [(int(a, 16), int(b, 16), path, sec) for sec, a, b in RANGE_RE.findall(body) if sec in SECTIONS]
    syms = sorted((int(a, 16), n, k) for n, k, a in SYM_RE.findall(
        (folder / "symbols.txt").read_text(encoding="utf-8", errors="replace")))
    rows = []
    addrs = [x[0] for x in syms]
    for sec, (s, e) in secs.items():
        inside = syms[bisect.bisect_left(addrs, s):bisect.bisect_left(addrs, e)]
        bounds = sorted({a for a, _n, _k in inside} | {e})
        mine = sorted((ds, de, p) for ds, de, p, dsec in done if dsec == sec)
        starts = [m[0] for m in mine]
        for a, n, k in inside:
            if k not in ("data", "bss"):
                continue
            nxt = bounds[bisect.bisect_right(bounds, a)] if a < e else e
            i = bisect.bisect_right(starts, a) - 1  # file ranges do not overlap: only the last one starting <= a
            f = mine[i][2] if i >= 0 and nxt <= mine[i][1] else None
            rows.append({"name": n, "module": module, "section": sec, "addr": a, "size": nxt - a, "done": f is not None,
                         "file": f})
    return rows


def rows(g) -> list[dict]:
    mods = g.modules()
    stamp = tuple(games._mtime(f / n) for _m, f in mods for n in ("symbols.txt", "delinks.txt"))

    def compute():
        out = []
        for m, f in mods:
            if (f / "delinks.txt").exists() and (f / "symbols.txt").exists():
                out += _module_rows(m, f)
        return out
    return games._disk_cached(("data", g.id), stamp, compute)


def summary(g) -> dict:
    """Bytes and symbols of each section kind, matched or not (the same ranges objdiff counts as data)."""
    rs = rows(g)
    by = {}
    for r in rs:
        k = by.setdefault(r["section"], {"symbols": 0, "matched": 0, "bytes": 0, "matched_bytes": 0})
        k["symbols"] += 1
        k["bytes"] += r["size"]
        if r["done"]:
            k["matched"] += 1
            k["matched_bytes"] += r["size"]
    tb, mb = sum(k["bytes"] for k in by.values()), sum(k["matched_bytes"] for k in by.values())
    return {"sections": by, "symbols": len(rs), "matched": sum(r["done"] for r in rs), "bytes": tb,
            "matched_bytes": mb, "pct": round(100 * mb / tb, 2) if tb else 0}


def _misses(game_id: str) -> dict[str, int]:
    db = config.ROOT / "missdb.sqlite"
    if not db.exists():
        return {}
    try:
        c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
        out = dict(c.execute("SELECT func, COUNT(*) FROM misses WHERE game = ? AND status = 'data' GROUP BY func",
                             (game_id,)))
        c.close()
        return out
    except sqlite3.Error:
        return {}


def listing(game_id: str, state: str = "todo", section: str = "", module: str = "", q: str = "",
            limit: int = 400) -> dict:
    g = games.get(game_id)
    rs = rows(g)
    miss = _misses(g.id)
    sel = [r for r in rs if (state == "all" or r["done"] == (state == "done"))
           and (not section or r["section"] == section) and (not module or r["module"] == module)
           and (not q or q.lower() in r["name"].lower())]
    sel.sort(key=lambda r: (r["module"] != "main", r["module"], r["addr"]))
    return {"summary": summary(g), "total": len(sel), "modules": sorted({r["module"] for r in rs}),
            "rows": [{**r, "misses": miss.get(r["name"], 0)} for r in sel[:limit]]}
