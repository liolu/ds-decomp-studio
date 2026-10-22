"""Discovery of the DS projects and of their functions (matched or not, auto_match result, sharing)."""
import bisect
import json
import re
import sqlite3
import time
from pathlib import Path

from . import config

SYM_RE = re.compile(r"^(\S+)\s+kind:function\((arm|thumb)(?:,size=0x([0-9a-f]+))?.*addr:0x([0-9a-f]+)")
DELINK_RE = re.compile(r"^(src/\S+):\n\s+complete\n\s+\.text\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+)", re.M)
HEALTH = config.DATA / "health.json"

# project dir -> key of the game in fpdb.sqlite (fingerprints were indexed from projets/_analyse)
FP_KEY = {"rayman-rr": "rrr", "heroes-of-mana": "hom", "dragon-ball-origins": "dbo", "eyeshield-21": "0301Eyeshield2",
          "club-house-games": "0595ClubHouseG", "powerpuff-girls-z": "1372GamedeDema", "farm-frenzy": "FarmFrenzyAnim",
          "mysims": "MySimsUSAEnFrE", "nintendogs-dachshund": "NintendogsDach", "fairy-tail-kardia": "OriginalStoryf",
          "resident-evil-deadly-silence": "ResidentEvilDe", "simanimals": "SimAnimalsEuro",
          "simcity-creator": "SimCityCreator", "simpsons-game": "SimpsonsGameTh", "spore-creatures": "SporeCreatures",
          "tom-and-jerry-tales": "TomandJerryTal", "fairy-tail-madoushi": "TVAnimeFairyTa"}
TITLES = {"rayman-rr": "Rayman Raving Rabbids", "heroes-of-mana": "Heroes of Mana", "dragon-ball-origins": "Dragon Ball Origins",
          "eyeshield-21": "Eyeshield 21", "club-house-games": "Club House Games", "powerpuff-girls-z": "Powerpuff Girls Z",
          "farm-frenzy": "Farm Frenzy", "mysims": "MySims", "nintendogs-dachshund": "Nintendogs Dachshund",
          "fairy-tail-kardia": "Fairy Tail: Kardia", "fairy-tail-madoushi": "Fairy Tail: Madoushi",
          "resident-evil-deadly-silence": "Resident Evil: Deadly Silence", "simanimals": "SimAnimals",
          "simcity-creator": "SimCity Creator", "simpsons-game": "The Simpsons Game", "spore-creatures": "Spore Creatures",
          "tom-and-jerry-tales": "Tom and Jerry Tales", "ultimate-spider-man": "Ultimate Spider-Man",
          "lego-star-wars-ii-the-original-trilogy": "LEGO Star Wars II", "harvest-moon-ds": "Harvest Moon DS",
          "spider-man-web-of-shadows": "Spider-Man: Web of Shadows", "blue-dragon-awakened-shadow": "Blue Dragon: Awakened Shadow",
          "code-lyoko": "Code Lyoko", "cooking-mama": "Cooking Mama", "livly-garden": "Livly Garden", "madagascar": "Madagascar",
          "professor-layton-and-the-spectre-s-call": "Professor Layton and the Spectre's Call",
          "spyro-shadow-legacy": "Spyro: Shadow Legacy", "star-wars-episode-iii-revenge-of-the-sit": "Star Wars Episode III",
          "star-wars-lethal-alliance": "Star Wars: Lethal Alliance", "penguins-of-madagascar-the": "The Penguins of Madagascar",
          "shrek-forever-after": "Shrek Forever After"}
STUDIOS = {  # who made the game: games of one studio often share an engine
    "livly-garden": "Brownie Brown", "heroes-of-mana": "Brownie Brown", "blue-dragon-awakened-shadow": "Brownie Brown",
    "professor-layton-and-the-spectre-s-call": "Level-5", "star-wars-episode-iii-revenge-of-the-sit": "Ubisoft",
    "rayman-rr": "Ubisoft Casablanca", "madagascar": "Vicarious Visions", "ultimate-spider-man": "Vicarious Visions",
    "spyro-shadow-legacy": "Amaze Entertainment", "lego-star-wars-ii-the-original-trilogy": "Amaze Entertainment",
    "simpsons-game": "Amaze Entertainment", "spore-creatures": "Amaze Entertainment",
    "spider-man-web-of-shadows": "Amaze Entertainment", "shrek-forever-after": "Griptonite Games",
    "penguins-of-madagascar-the": "Griptonite Games", "mysims": "EA", "simanimals": "EA", "simcity-creator": "EA",
    "nintendogs-dachshund": "Nintendo EAD", "club-house-games": "Agenda", "cooking-mama": "Office Create",
    "harvest-moon-ds": "Marvelous", "dragon-ball-origins": "Game Republic", "code-lyoko": "Game Machine Studios",
    "resident-evil-deadly-silence": "Capcom", "eyeshield-21": "Eighting", "fairy-tail-kardia": "Konami",
    "fairy-tail-madoushi": "Konami", "tom-and-jerry-tales": "Sensory Sweep", "farm-frenzy": "Alawar",
    "powerpuff-girls-z": "Bandai Namco", "star-wars-lethal-alliance": "Ubisoft",
}
# ROM rebuild state seen during onboarding; `verify` jobs update data/health.json, which wins
KNOWN_BROKEN = {}  # all fixed 2026-10-15: gametools rom_build.py (banner icon, DSProtect, empty files), delink_fix.py

_cache: dict = {}  # key -> (stamp, value): one entry per key, an outdated value is replaced (no growth over time)


def _cached(key, path_or_mtime, fn):
    m = path_or_mtime.stat().st_mtime if isinstance(path_or_mtime, Path) else path_or_mtime
    hit = _cache.get(key)
    if hit is None or hit[0] != m:
        hit = _cache[key] = (m, fn())
    return hit[1]


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0


def health() -> dict:
    try:
        return json.loads(HEALTH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_health(game: str, ok: bool, note: str = ""):
    h = health()
    h[game] = {"ok": ok, "note": note, "t": time.time()}
    HEALTH.write_text(json.dumps(h, indent=1), encoding="utf-8")


class Game:
    def __init__(self, path: Path):
        self.path = path
        self.id = path.name
        vers = sorted(p.name for p in (path / "config").iterdir() if (p / "arm9" / "symbols.txt").exists()) \
            if (path / "config").exists() else []
        self.version = vers[0] if vers else None
        self.ready = self.version is not None and (path / ".git").exists()

    # ---- metadata ----
    @property
    def cfg(self) -> Path:
        return self.path / "config" / (self.version or "?") / "arm9"

    @property
    def title(self) -> str:
        if self.id in TITLES:
            return TITLES[self.id]
        r = self.path / "README.md"
        if r.exists():
            m = re.match(r"#\s*(.+?) decompilation", r.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(1)
        return self.id.replace("-", " ").title()

    @property
    def code(self) -> str:
        r = self.path / "extract" / "README.md"
        if r.exists():
            m = re.search(r"Game code `(\w{4})`", r.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(1)
        return "AR5E" if self.id == "rayman-rr" else ""

    def remote(self) -> str:
        cfg = self.path / ".git" / "config"
        if not cfg.exists():
            return ""
        m = re.search(r'\[remote "origin"\][^\[]*?url = (\S+)', cfg.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else ""

    def rom_state(self) -> dict:
        if not self.ready:
            rom = next((self.path / "extract").glob("baserom*.nds"), None)
            try:
                dsi = rom is not None and rom.open("rb").read(0x13)[0x12] & 0x02
            except OSError:
                dsi = False
            if dsi:
                return {"ok": False, "note": "ROM DSi (NDSi Enhanced) : dsd 0.12 ne sait pas l'extraire"}
            return {"ok": False, "note": "projet incomplet (dsd init a echoue)"}
        h = health().get(self.id)
        if h:
            return h
        if self.id in KNOWN_BROKEN:
            return {"ok": False, "note": KNOWN_BROKEN[self.id]}
        return {"ok": True, "note": ""}

    # ---- functions ----
    def modules(self) -> list[tuple[str, Path]]:
        """[(module, its config folder)]: "main" (the ARM9 main module), "itcm", "dtcm", "ov000"... Overlays share
        addresses with each other, so a function is identified by module + address."""
        out = [("main", self.cfg)] if (self.cfg / "symbols.txt").exists() else []
        for sub in ("itcm", "dtcm"):
            if (self.cfg / sub / "symbols.txt").exists():
                out.append((sub, self.cfg / sub))
        ov = self.cfg / "overlays"
        if ov.exists():
            out += [(d.name, d) for d in sorted(ov.iterdir()) if (d / "symbols.txt").exists()]
        return out

    def _symbols_of(self, folder: Path):
        p = folder / "symbols.txt"

        def parse():
            out = []
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = SYM_RE.match(line)
                if m and m.group(3):
                    out.append((m.group(1), int(m.group(4), 16), int(m.group(3), 16), m.group(2)))
            return out
        return _cached(("sym", str(p)), p, parse) if p.exists() else []

    def _ranges_of(self, folder: Path):
        p = folder / "delinks.txt"
        if not p.exists():
            return []
        return _cached(("dl", str(p)), p, lambda: sorted(
            (int(a, 16), int(b, 16), f) for f, a, b in DELINK_RE.findall(p.read_text(encoding="utf-8", errors="replace"))))

    def symbols(self):
        """(name, addr, size, mode) of the main module (the one the automatic tools and the fingerprints cover)."""
        return self._symbols_of(self.cfg) if (self.cfg / "symbols.txt").exists() else []

    def done_ranges(self):
        """Matched (start, end, file) of the main module."""
        return self._ranges_of(self.cfg)

    def auto_status(self) -> dict:
        """{name: 'near'|'size'|'compile'|'m2c'} from the last auto_match pass (build/auto/status.json)."""
        p = self.path / "build" / "auto" / "status.json"
        if not p.exists():
            return {}
        try:
            return _cached(("st", str(p)), p, lambda: {r[0]: r[3] for r in json.loads(p.read_text())})
        except Exception:
            return {}

    def functions(self) -> list[dict]:
        """Every function of every ARM9 module (main, ITCM, DTCM, overlays; ARM and Thumb) with its state.
        `uid` identifies a function across modules: its address in the main module, "<module>:<addr>" elsewhere.
        The automatic tools (auto_match, donor_match) only handle ARM functions of the main module: `auto_tools`."""
        return self._functions_and_summary()[0]

    def _stamp(self, mods) -> tuple:
        """Dates of every file functions() reads: unchanged stamp = same rows."""
        b = self.path / "build"
        return tuple(_mtime(f / n) for _m, f in mods for n in ("symbols.txt", "delinks.txt")) + (
            _mtime(b / "clone" / "families.json"), _mtime(b / "auto" / "status.json"), _mtime(config.FPDB))

    def _functions_and_summary(self):
        mods = self.modules()
        stamp = self._stamp(mods)
        return _cached(("fns", self.id), stamp, lambda: self._compute(mods))

    def _compute(self, mods):
        st = self.auto_status()
        shared = shared_counts(FP_KEY.get(self.id))
        fam = clone_families(self)
        rows = []
        for module, folder in mods:
            ranges = self._ranges_of(folder)
            starts = [r[0] for r in ranges]
            main = module == "main"
            for name, addr, size, mode in self._symbols_of(folder):
                i = bisect.bisect_right(starts, addr) - 1
                f = ranges[i][2] if i >= 0 and ranges[i][0] <= addr < ranges[i][1] else None
                rows.append({"name": name, "addr": addr, "size": size, "mode": mode, "module": module,
                             "uid": addr if main else f"{module}:{addr:08x}", "done": f is not None, "file": f,
                             "auto": st.get(name, ""), "shared": shared.get(addr, 0) if main else 0,
                             "family": family_size(fam.get(name)) if main else 0,
                             "auto_tools": main and mode == "arm"})
        return rows, self._summarize(rows)

    def summary(self) -> dict:
        return self._functions_and_summary()[1] if self.ready else self._summarize([])

    @staticmethod
    def _summarize(rows) -> dict:
        tot, got = len(rows), sum(r["done"] for r in rows)
        tb, gb = sum(r["size"] for r in rows), sum(r["size"] for r in rows if r["done"])
        main = [r for r in rows if r["module"] == "main"]
        mb, mgb = sum(r["size"] for r in main), sum(r["size"] for r in main if r["done"])
        return {"functions": tot, "matched": got, "bytes": tb, "matched_bytes": gb,
                "pct_fn": round(100 * got / tot, 2) if tot else 0, "pct_code": round(100 * gb / tb, 2) if tb else 0,
                "pct_main": round(100 * mgb / mb, 2) if mb else 0, "modules": len({r["module"] for r in rows}),
                "left_manual": sum(1 for r in rows if not r["done"] and not r["auto_tools"])}

    def info(self) -> dict:
        return {"id": self.id, "title": self.title, "version": self.version, "code": self.code, "ready": self.ready,
                "studio": STUDIOS.get(self.id, ""), "remote": self.remote(), "rom": self.rom_state(),
                "auto_done": (self.path / ".auto_done").exists(), **self.summary()}


def all_games(include_broken=True) -> list[Game]:
    out = []
    if not config.PROJETS.exists():
        return out
    for d in sorted(config.PROJETS.iterdir()):
        if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "config").exists():
            g = Game(d)
            if include_broken or g.ready:
                out.append(g)
    return out


def get(game_id: str) -> Game:
    d = config.PROJETS / game_id
    if not game_id or "/" in game_id or "\\" in game_id or ".." in game_id or not d.is_dir():
        raise KeyError(f"jeu inconnu : {game_id}")
    return Game(d)


# ---- cross-game sharing (fingerprint DB) ----
def _db():
    return sqlite3.connect(config.FPDB) if config.FPDB.exists() else None


def shared_counts(key) -> dict:
    """{addr: number of OTHER games containing the same function (strict hash)}."""
    if not key or not config.FPDB.exists():
        return {}

    def q():
        con = _db()
        rows = con.execute("""SELECT x.addr, COUNT(DISTINCT y.game) FROM fn x JOIN fn y
                              ON x.strict=y.strict AND y.game<>x.game WHERE x.game=? GROUP BY x.addr""", (key,)).fetchall()
        con.close()
        return dict(rows)
    return _cached(("shared", key), config.FPDB, q)


def donor_hits(game: Game) -> dict:
    """{function name: [donor repo, donor function, donor file]} written by `tools/donor_match.py --list`: functions
    with a twin in another public decompilation (decomps-externes/), reusable with the "donors" task."""
    p = game.path / "build" / "donor" / "hits.json"
    if not p.exists():
        return {}
    try:
        return _cached(("donors", str(p)), p, lambda: json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return {}


def clone_families(game: Game) -> dict:
    """{function name: {"dup": n, "template": n, "twin": matched twin here or None, "first": representative,
    "game": [game, function, file] or absent}} written by `tools/clone_match.py --list`: unmatched functions with the
    same machine code (dup) or the same instructions with other constants (template) as other functions."""
    p = game.path / "build" / "clone" / "families.json"
    if not p.exists():
        return {}
    try:
        return _cached(("clone", str(p)), p, lambda: json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return {}


def family_size(row) -> int:
    """How many OTHER unmatched functions of the game one match of this function gives (by cloning)."""
    return max(row.get("dup", 0), row.get("template", 0)) if row else 0


def weight(fn: dict) -> int:
    """Matches one match of this function is worth beyond itself: other games with the same code + its clones here."""
    return fn.get("shared", 0) + fn.get("family", 0)


def portable(game: Game) -> dict:
    """{addr: (source, function name, source file)} for unmatched functions whose exact twin is already matched
    elsewhere: in another of our projects (source = game id), in this game (source = "clone:<twin>", copied with
    tools/clone_match.py), or in an external decompilation (source = "donor:<repo>", see donor_hits)."""
    out = dict(_portable_projects(game))
    hits, fam = donor_hits(game), clone_families(game)
    if hits or fam:
        for name, addr, _size, _mode in game.symbols():
            if addr in out:
                continue
            row = fam.get(name)
            if row and isinstance(row.get("game"), list) and len(row["game"]) == 3:
                out[addr] = tuple(row["game"])
            elif row and row.get("twin"):
                out[addr] = ("clone:" + game.id, row["twin"], "src/auto/" + row["twin"] + ".c")
            elif name in hits:
                repo, dname, rel = hits[name]
                out[addr] = ("donor:" + repo, dname, rel)
    return out


def _portable_projects(game: Game) -> dict:
    key = FP_KEY.get(game.id)
    if not key or not config.FPDB.exists():
        return {}
    others = {FP_KEY[g.id]: g for g in all_games() if g.id in FP_KEY and g.id != game.id and g.ready}
    stamp = (config.FPDB.stat().st_mtime,) + tuple(
        (g.cfg / "delinks.txt").stat().st_mtime for g in others.values() if (g.cfg / "delinks.txt").exists())

    def q():
        con = _db()
        rows = con.execute("""SELECT x.addr, y.game, y.addr, y.name FROM fn x JOIN fn y
                              ON x.strict=y.strict AND y.game<>x.game WHERE x.game=?""", (key,)).fetchall()
        con.close()
        out = {}
        for addr, ogame, oaddr, oname in rows:
            g = others.get(ogame)
            if g is None or addr in out:
                continue
            rng = g.done_ranges()
            i = bisect.bisect_right([r[0] for r in rng], oaddr) - 1
            if i >= 0 and rng[i][0] <= oaddr < rng[i][1]:
                out[addr] = (g.id, oname, rng[i][2])
        return out
    return _cached(("portable", game.id), hash(stamp), q)
