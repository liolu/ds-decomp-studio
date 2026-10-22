#!/usr/bin/env python3
"""Database of every MISS of every matching job (Qwen, hunt, Claude agents, the C editor), replayed on every
unmatched function of every game.

    python ../../studio/gametools/missdb.py stats                 # what the database holds (all games)
    python ../../studio/gametools/missdb.py show NAME             # the misses of one function, best first
    python ../../studio/gametools/missdb.py replay                # misses of THIS game on its unmatched functions
    python ../../studio/gametools/missdb.py replay --all-games    # misses of ALL our games on this game
    python ../../studio/gametools/missdb.py replay --commit --push
    python ../../studio/gametools/missdb.py replay --to build/hunt/matched   # write the matches there, integrate nothing
    python ../../studio/gametools/missdb.py import                # add the old tries (qwen memory, hunt, near misses)

Recording is automatic and cannot be skipped: workbench.judge (hunt, fj, agents, MCP, web editor) and
qwen_block.compile_versions call record() for every C that compiles but does not match. A miss keeps the C, the
compiler profile, the error (compile error / N diffs / size) and the FINGERPRINT of the code it compiled to
(calls and loaded addresses masked, the same fingerprints as clone_match).

Why it pays: a C that misses function A is often the exact C of ANOTHER function B (a sibling, a template twin, the
same function in another game). The replay compiles nothing to find those: it looks the miss's fingerprint up among
the unmatched functions (exact, or same instructions with other constants), renames the calls / loaded symbols and
replaces the constants like clone_match, and only then compiles the candidate and checks it word by word,
relocations included. Matches go to src/auto/ + delinks.txt and `match.py verify` (clone_match.integrate_verified).

The database is ONE file for all games: decomp ds/missdb.sqlite (MISSDB=path to change it).
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project import ROOT  # noqa: E402  (the game: DSD_PROJECT or the current folder)

WORKSPACE = Path(__file__).resolve().parents[2]  # decomp ds/
DB = Path(os.environ.get("MISSDB") or WORKSPACE / "missdb.sqlite")
SCHEMA = """
CREATE TABLE IF NOT EXISTS misses (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL, func TEXT NOT NULL, module TEXT NOT NULL DEFAULT 'main',
    addr INTEGER, size INTEGER, profile TEXT NOT NULL,
    code_hash TEXT NOT NULL, code TEXT NOT NULL,
    status TEXT NOT NULL,          -- near (same size) / size / compile
    diffs INTEGER, total INTEGER, error TEXT,
    source TEXT,                   -- qwen / workbench / hunt / import...
    out_size INTEGER, fp_exact TEXT, fp_tpl TEXT,
    words TEXT, relocs TEXT,       -- what the C compiled to (hex words, [[offset, type, symbol, addend]])
    created REAL NOT NULL,
    UNIQUE (game, func, code_hash, profile)
);
CREATE INDEX IF NOT EXISTS misses_exact ON misses (fp_exact);
CREATE INDEX IF NOT EXISTS misses_tpl ON misses (fp_tpl);
CREATE INDEX IF NOT EXISTS misses_func ON misses (game, func);
CREATE TABLE IF NOT EXISTS tried (     -- a miss already compiled for this target (never again)
    miss_id INTEGER NOT NULL, game TEXT NOT NULL, target TEXT NOT NULL, result TEXT, at REAL,
    PRIMARY KEY (miss_id, game, target)
);
CREATE TABLE IF NOT EXISTS wins (      -- misses that matched another function
    miss_id INTEGER NOT NULL, game TEXT NOT NULL, target TEXT NOT NULL, kind TEXT, at REAL,
    PRIMARY KEY (miss_id, game, target)
);
"""

_conn = None
_lock = threading.Lock()


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        c = sqlite3.connect(DB, timeout=60, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _conn = c
    return _conn


def code_hash(code: str) -> str:
    return hashlib.sha1(" ".join(code.split()).encode("utf-8", "replace")).hexdigest()[:20]


# ---------------------------------------------------------------- recording

def fingerprint(obj_path: Path, name: str) -> dict | None:
    """What `name` compiled to in this object: size, clone_match fingerprints, words and relocations. None for
    Thumb code or a missing function."""
    import donorlib
    import clone_match as cm
    obj = donorlib.Obj(obj_path)
    fn = next((f for f in obj.functions() if f[0] == name), None)
    if fn is None or fn[4]:
        return None
    _n, shndx, off, size, _thumb = fn
    code = obj.section_bytes(shndx)[off: off + size]
    relocs = obj.function_relocs(shndx, off, size)
    ext = {o // 4 for o, typ, _s, _a in relocs if typ != donorlib.R_ARM_ABS32}
    ex, tp = cm.shapes(code, ext=ext)
    return {"out_size": size, "fp_exact": ex, "fp_tpl": tp, "words": code.hex(),
            "relocs": json.dumps([[o, t, s, a] for o, t, s, a in relocs])}


def record(name: str, code: str, profile: str, status: str, *, diffs=None, total=None, error: str = "",
           source: str = "", obj: Path | None = None, module: str = "main", addr=None, size=None) -> None:
    """Keeps one miss. Never raises: a matching job must not stop because of its bookkeeping."""
    if status == "match" or not code.strip():
        return
    try:
        fp = None
        if obj is not None and status in ("near", "size") and Path(obj).exists():
            try:
                fp = fingerprint(Path(obj), name)
            except Exception:  # an odd object: keep the miss without its fingerprint
                fp = None
        fp = fp or {}
        row = (ROOT.name, name, module or "main", addr, size, profile or "", code_hash(code), code, status, diffs,
               total, (error or "")[-1500:], source, fp.get("out_size"), fp.get("fp_exact"), fp.get("fp_tpl"),
               fp.get("words"), fp.get("relocs"), time.time())
        with _lock:
            c = db()
            c.execute("INSERT OR IGNORE INTO misses (game, func, module, addr, size, profile, code_hash, code, status, "
                      "diffs, total, error, source, out_size, fp_exact, fp_tpl, words, relocs, created) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            c.commit()
    except Exception as e:  # noqa: BLE001
        print(f"missdb: not recorded ({e})", file=sys.stderr)


# ---------------------------------------------------------------- replay

def pair(m_words: tuple, relocs: list, m_name: str, img, b_name: str):
    """({miss name: target name}, {miss constant: {target constants}}) to turn the miss's C into the C of b_name,
    or None when the two cannot be paired (a loaded address of the target has no symbol...)."""
    import donorlib
    import clone_match as cm
    bw = cm.words(img.code(b_name))
    if len(bw) != len(m_words):
        return None
    pool = donorlib.pool_words(m_words)
    if pool != donorlib.pool_words(bw):
        return None
    rel = {o // 4: (t, s, a) for o, t, s, a in relocs}
    ba = img.funcs[b_name][0]
    names, nums = {m_name: b_name}, {}
    for i, (a, b) in enumerate(zip(m_words, bw)):
        if i in rel:
            typ, sym, add = rel[i]
            if not sym:
                return None
            if typ == donorlib.R_ARM_ABS32:
                new = cm.resolve(img, (b - add) & 0xFFFFFFFF)
            else:
                new = cm.resolve(img, cm.branch_target(b, ba + 4 * i))
            if not new or names.setdefault(sym, new) != new:
                return None
            continue
        if a == b:
            continue
        if i in pool:
            nums.setdefault(a, set()).add(b)
            if a >= 0x80000000:
                nums.setdefault(0x100000000 - a, set()).add((0x100000000 - b) & 0xFFFFFFFF)
            continue
        for x, y in zip(cm.immediates(a), cm.immediates(b)):
            nums.setdefault(x, set()).add(y)
    return {k: v for k, v in names.items() if k != v or k == m_name}, nums


def candidates(row, img, b_name: str) -> list[str]:
    import auto_match as am
    import clone_match as cm
    code = row["code"]
    if code.startswith(am.MARKER):
        code = code.split("\n", 1)[1]
    ws = cm.words(bytes.fromhex(row["words"]))
    pm = pair(ws, json.loads(row["relocs"]), row["func"], img, b_name)
    if pm is None:
        return []
    names, nums = pm
    return [c for v in cm.or_variants(cm.rename(code, names), nums) for c in cm.with_constants(v, nums)]


def replay(games: list[str] | None, jobs: int, targets: set[str] | None = None, log=print):
    """[(target, size, addr, source, miss_id, kind)] of the misses that match an unmatched function of this game."""
    import auto_match as am
    import clone_match as cm
    img = cm.Image(ROOT)
    matched = img.matched()
    stems = {p.stem.lower() for p in (ROOT / "src").rglob("*.c")}
    todo = [n for n in img.funcs if n not in matched and n.lower() not in stems
            and (targets is None or n in targets)]
    ex, tp = {}, {}
    for n in todo:
        e, t = cm.shapes(img.code(n))
        ex.setdefault(e, []).append(n)
        tp.setdefault(t, []).append(n)
    c = db()
    c.row_factory = sqlite3.Row
    where = "fp_exact IS NOT NULL AND module = 'main'"
    args: list = []
    if games is not None:
        where += f" AND game IN ({','.join('?' * len(games))})"
        args += games
    rows = c.execute(f"SELECT id, game, func, profile, code, diffs, words, relocs, fp_exact, fp_tpl FROM misses "
                     f"WHERE {where}", args).fetchall()
    c.row_factory = None
    # a match is tried again (its files may have been rolled back), a failure never
    tried = {(m, t) for m, t in c.execute("SELECT miss_id, target FROM tried WHERE game = ? AND result != 'match'", (ROOT.name,))}
    per_target: dict[str, list] = {}
    for r in rows:
        hits = [(n, "exact") for n in ex.get(r["fp_exact"], [])]
        hits += [(n, "template") for n in tp.get(r["fp_tpl"], []) if (n, "exact") not in hits]
        for n, kind in hits:
            if (r["id"], n) not in tried:
                # same game first, then the closest miss
                per_target.setdefault(n, []).append((kind != "exact", r["game"] != ROOT.name, r["diffs"] or 0, r, kind))
    log(f"{len(rows)} misses with a fingerprint ({'all games' if games is None else ', '.join(games)}), "
        f"{len(todo)} unmatched functions here: {len(per_target)} functions have a miss of the same shape")
    if not per_target:
        return []
    done_rows = []

    def attempt(item):
        n, cands = item
        for *_k, r, kind in sorted(cands, key=lambda x: x[:3])[:12]:
            result = "no pairing"
            profiles = list(dict.fromkeys(p for p in (r["profile"].replace(" -thumb", ""), img.default_cc) if p))
            for src in candidates(r, img, n):
                for prof in profiles:
                    why = cm.check(img, n, src, prof)
                    if not why:
                        done_rows.append((r["id"], n, "match"))
                        return n, src, prof, r["id"], kind, f"{r['game']}:{r['func']}"
                    result = why
            done_rows.append((r["id"], n, result[:200]))
        return None

    found = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for k, res in enumerate(pool.map(attempt, sorted(per_target.items()))):
            if res:
                n, src, prof, mid, kind, frm = res
                a, s = img.funcs[n]
                if prof != img.default_cc:
                    src = f"{am.MARKER}{prof} */\n" + src
                found.append((n, s, a, src, mid, kind))
                log(f"  MATCH {n} <- miss of {frm} ({kind})")
    now = time.time()
    with _lock:
        c.executemany("INSERT OR REPLACE INTO tried VALUES (?,?,?,?,?)",
                      [(m, ROOT.name, t, res, now) for m, t, res in done_rows])
        c.commit()
    return found


def save_wins(found, kept: set[str]) -> None:
    now = time.time()
    with _lock:
        c = db()
        c.executemany("INSERT OR REPLACE INTO wins VALUES (?,?,?,?,?)",
                      [(mid, ROOT.name, n, kind, now) for n, _s, _a, _src, mid, kind in found if n in kept])
        c.commit()


def write_to(found, out: Path) -> None:
    """Matches as a workbench batch: NAME.c + results.json (`workbench.py submit-many DIR`)."""
    import auto_match as am
    out.mkdir(parents=True, exist_ok=True)
    f = out / "results.json"
    try:
        res = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = {}
    default = None
    for n, _s, _a, src, _mid, _kind in found:
        if src.startswith(am.MARKER):
            prof = src[len(am.MARKER):].split(" */", 1)[0]
        else:
            if default is None:
                import clone_match as cm
                default = cm.Image(ROOT).default_cc
            prof = default
        (out / f"{n}.c").write_text(src, encoding="utf-8", newline="\n")
        res[n] = {"status": "match", "match": True, "profile": prof, "k": [0, 0], "mt": time.time(), "from": "missdb"}
    f.write_text(json.dumps(res, indent=1), encoding="utf-8")


def cmd_replay(a) -> None:
    import clone_match as cm
    games = None if a.all_games else [g for g in (a.games.split(",") if a.games else [ROOT.name])]
    targets = set(a.names.split(",")) if a.names else None
    found = replay(games, a.j, targets)
    if a.max:
        found = found[:a.max]
    if not found:
        print("No miss matches another function.")
        return
    if a.dry_run:
        print(f"{len(found)} matches (dry run, nothing added).")
        return
    if a.to:
        write_to(found, a.to)
        save_wins(found, {f[0] for f in found})
        print(f"{len(found)} matches written to {a.to} (python ../../studio/gametools/workbench.py submit-many {a.to})")
        return
    kept = cm.integrate_verified([(n, s, ad, src) for n, s, ad, src, _m, _k in found])
    save_wins(found, set(kept))
    print(f"OK: {len(kept)} functions matched from misses.")
    if kept and a.commit:
        cm.commit(kept, a.push, msg=(f"missdb: {len(kept)} matching functions\n\nC written for another function "
                                     "(a miss of an AI or hand session, here or in another of our DS projects) that "
                                     "compiles exactly to these functions (tools missdb.py replay). VERIFY PASSED.\n"))


# ---------------------------------------------------------------- import of older tries

def cmd_import(a) -> None:
    """Judges the tries the tools kept before the database existed: judge() records them (with a fingerprint)."""
    import workbench as wb
    files = []
    mem = ROOT / "build" / "qwen_auto" / "memory"
    for p in sorted(mem.glob("*.json")) if mem.is_dir() else []:
        try:
            best = json.loads(p.read_text(encoding="utf-8")).get("best")
        except ValueError:
            best = None
        if best:
            files.append((p.stem, best, "import:qwen"))
    for d, tag in (("build/hunt/best", "import:hunt"), ("build/auto/near", "import:near")):
        for p in sorted((ROOT / d).glob("*.c")) if (ROOT / d).is_dir() else []:
            files.append((p.stem, p.read_text(encoding="utf-8", errors="replace"), tag))
    have = {(f, h) for f, h in db().execute("SELECT func, code_hash FROM misses WHERE game = ?", (ROOT.name,))}
    files = [x for x in files if (x[0], code_hash(x[1])) not in have]
    if a.max:
        files = files[:a.max]
    print(f"{len(files)} older tries to judge", flush=True)
    wb.MISS_SOURCE = "import"
    wb.overlay_index()  # built once here: the threads below only read it
    t0, n = time.time(), 0

    def one(item):
        name, code, tag = item
        try:
            if wb.overlay_index().get(name) is not None:
                return None  # the replay works on the main module, like clone_match
            wb.MISS_SOURCE = tag
            return wb.judge(name, code)
        except BaseException as e:  # noqa: BLE001  unknown names raise SystemExit
            if os.environ.get("MISSDB_DEBUG"):
                print(name, repr(e)[:300], flush=True)
            return None
    with ThreadPoolExecutor(max_workers=max(1, a.j)) as pool:
        for k, r in enumerate(pool.map(one, files)):
            n += r is not None
            if (k + 1) % 100 == 0:
                print(f"[{k + 1}/{len(files)} {time.time() - t0:.0f}s]", flush=True)
    print(f"{n} tries judged and recorded")


# ---------------------------------------------------------------- reading

def cmd_stats(a) -> None:
    c = db()
    print(f"{DB}")
    print(f"{'game':40} {'misses':>7} {'replayable':>10} {'functions':>9} {'wins':>5}")
    wins = dict(c.execute("SELECT game, COUNT(*) FROM wins GROUP BY game"))
    for g, n, fp, f in c.execute("SELECT game, COUNT(*), COUNT(fp_exact), COUNT(DISTINCT func) FROM misses "
                                 "GROUP BY game ORDER BY 2 DESC"):
        print(f"{g:40} {n:7} {fp:10} {f:9} {wins.get(g, 0):5}")
    print("errors:", ", ".join(f"{s} {n}" for s, n in c.execute("SELECT status, COUNT(*) FROM misses GROUP BY status")))
    if a.json:
        rows = c.execute("SELECT game, COUNT(*), COUNT(fp_exact), COUNT(DISTINCT func) FROM misses GROUP BY game")
        print(json.dumps({g: {"misses": n, "replayable": fp, "functions": f, "wins": wins.get(g, 0)}
                          for g, n, fp, f in rows}))


def cmd_show(a) -> None:
    c = db()
    rows = c.execute("SELECT id, game, status, diffs, total, profile, source, error, code FROM misses WHERE func = ? "
                     "AND game = ? ORDER BY status != 'near', diffs LIMIT ?", (a.name, ROOT.name, a.n)).fetchall()
    for mid, g, st, d, t, prof, src, err, code in rows:
        print(f"--- #{mid} {st} {d}/{t} diffs  {prof}  ({src})")
        if st == "compile":
            print(err.strip()[-400:])
        if a.code:
            print(code)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("replay", help="try every miss on every unmatched function of this game")
    p.add_argument("--all-games", action="store_true", help="misses of all our games (default: this game)")
    p.add_argument("--games", help="misses of these games (comma separated folder names)")
    p.add_argument("--names", help="only these target functions (comma separated)")
    p.add_argument("--max", type=int, default=0)
    p.add_argument("-j", type=int, default=os.cpu_count() or 4)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--to", type=Path, help="write the matches to this workbench batch folder, integrate nothing")
    p.add_argument("--commit", action="store_true", help="after VERIFY PASSED: commit the new files")
    p.add_argument("--push", action="store_true", help="with --commit: push when the game has a remote")
    p = sp.add_parser("import", help="judge (and so record) the tries kept before the database existed")
    p.add_argument("--max", type=int, default=0)
    p.add_argument("-j", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    p = sp.add_parser("stats")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("show")
    p.add_argument("name")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--code", action="store_true")
    a = ap.parse_args()
    if a.cmd == "replay" and not (a.dry_run or a.to):  # it integrates: same lock as the other pipelines
        from pipeline_lock import pipeline_lock
        with pipeline_lock("missdb"):
            globals()["cmd_" + a.cmd](a)
    else:
        globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
