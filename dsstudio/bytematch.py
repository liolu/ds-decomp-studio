"""ByteMatch (https://bytematch.dev): public progress pages and badges of decompilation projects, fed by objdiff
reports.

The game repos cannot build their report in GitHub's CI (it needs the ROM). Two ways to feed ByteMatch:

1. Automatic (no token): the Studio commits the report it builds locally (build/<version>/report.json, made by
   `tools/match.py progress --rebuild`) as progress/report.json.gz, and the game's workflow
   .github/workflows/progress.yaml publishes it as the artifact `<VERSION>_report`, the way dtk-template projects
   do. Adding the repo once on https://bytematch.dev/manage/new is then enough: ByteMatch reads every new report.
2. Upload API: one token per project (its ByteMatch manage page), kept in data/bytematch.json (never committed):

    python studio.py bytematch rayman-rr --token bm_...    # remember the token (once)
    python studio.py bytematch rayman-rr                   # upload now (the job `progress` does it too)
"""
import gzip
import json
import re
import urllib.parse
import urllib.request

from . import config, gitutil

SITE = "https://bytematch.dev"
TOKENS = config.DATA / "bytematch.json"
START, END = "<!-- bytematch:start -->", "<!-- bytematch:end -->"


def repo_of(g) -> str:
    """owner/repo of the game's ByteMatch project ('' if none): `bytematch = "owner/repo"` in its game.toml (a game
    moved into All-nds-decomp-games keeps the ByteMatch page of its old repository), else its GitHub remote."""
    toml = g.path / "game.toml"
    if toml.exists():
        m = re.search(r'^bytematch\s*=\s*"([^"]+)"', toml.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            return m.group(1)
    if getattr(g, "mono", False):  # one repository for every game: no ByteMatch project of its own yet
        return ""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", g.remote() or "")
    return m.group(1) if m else ""


def tokens() -> dict:
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_token(g, token: str) -> str:
    repo = repo_of(g)
    if not repo:
        raise SystemExit(f"{g.id} n'a pas de depot GitHub : publiez-le d'abord")
    if not token.startswith("bm_"):
        raise SystemExit("un jeton ByteMatch commence par bm_ (page Manage du projet sur bytematch.dev)")
    t = tokens()
    t[repo] = token
    TOKENS.write_text(json.dumps(t, indent=1), encoding="utf-8")
    return repo


def version_of(g) -> str:
    """The version name shown on ByteMatch: the game code of the ROM (AR5E), else the config folder (usa)."""
    return g.code or g.version


MANAGE_NEW = f"{SITE}/manage/new"

# The settings of each project's ByteMatch page (Manage > Settings): official title from the ROM's banner, series,
# first release year (None when not sure). The platform is always "nds" (Nintendo DS).
PAGES = {
    "rayman-rr": ("Rayman Raving Rabbids", "Rayman", 2006),
    "ultimate-spider-man": ("Ultimate Spider-Man", "Spider-Man", 2005),
    "spyro-shadow-legacy": ("Spyro: Shadow Legacy", "Spyro", 2005),
    "spider-man-web-of-shadows": ("Spider-Man: Web of Shadows", "Spider-Man", 2008),
    "simpsons-game": ("The Simpsons Game", "The Simpsons", 2007),
    "resident-evil-deadly-silence": ("Resident Evil: Deadly Silence", "Resident Evil", 2006),
    "nintendogs-dachshund": ("Nintendogs: Dachshund & Friends", "Nintendogs", 2005),
    "powerpuff-girls-z": ("Game de Demashita! Powerpuff Girls Z", "The Powerpuff Girls", None),
    "mysims": ("MySims", "MySims", 2007),
    "livly-garden": ("Livly Garden", "Livly Island", None),
    "blue-dragon-awakened-shadow": ("Blue Dragon: Awakened Shadow", "Blue Dragon", 2009),
    "heroes-of-mana": ("Heroes of Mana", "Mana", 2007),
    "lego-star-wars-ii-the-original-trilogy": ("LEGO Star Wars II: The Original Trilogy", "LEGO Star Wars", 2006),
    "harvest-moon-ds": ("Harvest Moon DS", "Harvest Moon", 2005),
    "farm-frenzy": ("Farm Frenzy: Animal Country", "Farm Frenzy", None),
    "code-lyoko": ("Code Lyoko", "Code Lyoko", 2007),
    "fairy-tail-madoushi": ("Fairy Tail: Gekitou! Madoushi Kessen", "Fairy Tail", None),
    "fairy-tail-kardia": ("Fairy Tail: Gekitotsu! Kardia Daiseidou", "Fairy Tail", None),
    "cooking-mama": ("Cooking Mama", "Cooking Mama", 2006),
    "eyeshield-21": ("Eyeshield 21: Max Devil Power!", "Eyeshield 21", 2005),
    "dragon-ball-origins": ("Dragon Ball: Origins", "Dragon Ball", 2008),
}
REGIONS = {"E": "USA", "P": "Europe", "J": "Japan", "F": "France", "D": "Germany", "X": "Spanish",
           "S": "Spain", "I": "Italy", "U": "Australia", "Y": "Europe", "V": "Europe"}


def page_fields(g) -> dict:
    """What the project's ByteMatch settings should say (see PAGES)."""
    title, franchise, year = PAGES.get(g.id, (g.title, "", None))
    code = version_of(g)
    region = REGIONS.get(code[-1:], "") if len(code) == 4 else ""
    return {"name": f"{title} (DS)", "shortName": title, "platform": "nds", "game": title, "franchise": franchise,
            "releaseYear": str(year or ""), "defaultVersion": code,
            "description": f"Matching decompilation of {title} for the Nintendo DS"
                           + (f" ({region} version, {code})" if region else f" ({code})")
                           + ": C that compiles back to the original ROM, byte for byte."}
WORKFLOW = ".github/workflows/progress.yaml"
REPORT = "progress/report.json.gz"


def workflow_text(g) -> str:
    """The game's workflow that publishes the committed report as the artifact ByteMatch reads."""
    v = version_of(g)
    return f"""# Written by DS Decomp Studio: publishes the objdiff report for ByteMatch (https://bytematch.dev).
# The report needs the ROM to be built, so the Studio builds it locally and commits it as {REPORT};
# this workflow only unpacks it into the artifact ByteMatch expects: <VERSION>_report.
name: Progress report
on:
  push:
    branches:
      - main
  workflow_dispatch:
jobs:
  report:
    name: Publish the objdiff report
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: Unpack the report built by DS Decomp Studio
        run: |
          mkdir -p out
          if [ -f {REPORT} ]; then gunzip -c {REPORT} > out/report.json; fi

      - name: Upload the report
        if: hashFiles('out/report.json') != ''
        uses: actions/upload-artifact@v7
        with:
          name: {v}_report
          path: out/report.json
"""


def export(g) -> list[str]:
    """Writes progress/report.json.gz (from build/<version>/report.json) and the workflow. Returns the paths that
    changed (to commit), [] when there is no report yet."""
    src = g.path / "build" / g.version / "report.json"
    if not src.exists():
        return []
    changed = []
    out = g.path / REPORT
    out.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(src.read_bytes(), compresslevel=9, mtime=0)  # mtime 0: same report, same bytes
    if not out.exists() or out.read_bytes() != data:
        out.write_bytes(data)
        changed.append(REPORT)
    if getattr(g, "mono", False):  # All-nds-decomp-games: one workflow at the root publishes every game's report
        return changed
    wf = g.path / WORKFLOW
    text = workflow_text(g)
    if not wf.exists() or wf.read_text(encoding="utf-8") != text:
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text(text, encoding="utf-8", newline="\n")
        changed.append(WORKFLOW)
    return changed


def registered(g) -> bool:
    """The project exists on ByteMatch (its badge answers): only then are badges added to the README."""
    repo = repo_of(g)
    if not repo:
        return False
    if repo in tokens():
        return True
    req = urllib.request.Request(f"{SITE}/{repo}.svg?label=Code&measure=matched_code_percent",
                                 headers={"User-Agent": "ds-decomp-studio (+https://github.com/liolu/ds-decomp-studio)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def badges(g) -> str:
    repo = repo_of(g)
    page = f"{SITE}/{repo}"
    items = [("Code", "matched_code_percent"), ("Data", "matched_data_percent"), ("Functions", "matched_functions")]
    line = " ".join(f"[![{label}]({page}.svg?label={label}&measure={m})]({page})" for label, m in items)
    return f"{START}\n{line}\n{END}"


def add_badges(g) -> bool:
    """Badges under the README title (once). True if the README changed."""
    p = g.path / "README.md"
    text = p.read_text(encoding="utf-8")
    block = badges(g)
    # the block is always rewritten under the title: `# Title`, or a title underlined with ===== (Rayman's README)
    rest = re.sub(r"\n*" + re.escape(START) + r".*?" + re.escape(END) + r"\n*", "\n\n", text, flags=re.S)
    rest = rest.lstrip("\n")
    m = re.search(r"^# .*\n", rest, re.M) or re.search(r"^=+[ \t]*\n", rest, re.M)
    at = m.end() if m else 0
    new = rest[:at] + "\n" + block + "\n\n" + rest[at:].lstrip("\n")
    if new != text:
        p.write_text(new, encoding="utf-8", newline="\n")
    return new != text


def upload(g, log=print) -> bool:
    """Sends build/<version>/report.json for the commit HEAD (already pushed). False if not set up or refused."""
    repo = repo_of(g)
    token = tokens().get(repo)
    if not token:
        return False
    report = g.path / "build" / g.version / "report.json"
    if not report.exists():
        log("  ByteMatch : pas de report.json (lancer match.py progress --rebuild)")
        return False
    # the last commit of THIS game (`-- .`): in All-nds-decomp-games, HEAD is often another game's commit
    sha = gitutil.git(g.path, "log", "-1", "--format=%H", "--", ".").stdout.strip()
    msg = gitutil.git(g.path, "log", "-1", "--format=%s", "--", ".").stdout.strip()
    when = gitutil.git(g.path, "log", "-1", "--format=%cI", "--", ".").stdout.strip()
    query = urllib.parse.urlencode({"version": version_of(g), "commit": sha, "commit_message": msg,
                                    "commit_timestamp": when})
    req = urllib.request.Request(f"{SITE}/api/v1/projects/{repo}/reports?{query}",
                                 data=gzip.compress(report.read_bytes()), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Encoding": "gzip",
                                          "Content-Type": "application/json",
                                          # Cloudflare refuses Python's default agent (error 1010)
                                          "User-Agent": "ds-decomp-studio (+https://github.com/liolu/ds-decomp-studio)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            answer = json.loads(r.read() or b"{}")
        log(f"  ByteMatch : rapport {version_of(g)} envoye ({answer.get('url', SITE + '/' + repo)})")
        return True
    except urllib.error.HTTPError as e:
        log(f"  ByteMatch : refuse ({e.code}) {e.read()[:300].decode('utf-8', 'replace')}")
    except Exception as e:
        log(f"  ByteMatch : envoi impossible ({e})")
    return False
