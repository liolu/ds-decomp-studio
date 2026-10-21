"""Adding, archiving, cloning and publishing game projects."""
import re
import shutil
import subprocess
import time

from . import config, games, gitutil

# Never published: game data, build outputs, binaries we are not allowed to distribute
FORBIDDEN_EXT = {".nds", ".bin", ".srl", ".sav", ".narc", ".sdat", ".nftr", ".nclr", ".ncgr", ".nscr", ".exe",
                 ".dll", ".o", ".elf", ".zip", ".7z"}
MAX_FILE = 20 * 1024 * 1024
# 4th letter of the game code -> config/<version> name (same table as tools/new_project.py)
REGIONS = {"E": "usa", "P": "eu", "V": "eu", "X": "eu", "Y": "eu", "J": "jp", "K": "kor", "U": "aus", "D": "ger",
           "F": "fra", "I": "ita", "S": "spa"}


def roms_without_project() -> list[dict]:
    known = {g.code: g.id for g in games.all_games() if g.code}
    taken = {p.name for p in config.PROJETS.iterdir()} if config.PROJETS.exists() else set()
    out, seen = [], set()
    for rom in sorted(config.ROMS.glob("*.nds")) if config.ROMS.exists() else []:
        try:
            with open(rom, "rb") as f:
                h = f.read(0x20)
            code, title = h[12:16].decode("latin1"), h[:12].split(b"\0")[0].decode("latin1")
        except Exception:
            continue
        if code in known or code in seen:
            continue
        seen.add(code)
        slug = slug_of(rom.name)
        if slug in taken:
            # same game in another region (USA / Europe...): one project per ROM, named after its region
            base = f"{slug[:36]}-{REGIONS.get(code[3:4], code[3:4].lower() or 'x')}"
            slug, n = base, 2
            while slug in taken:
                slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        out.append({"rom": rom.name, "code": code, "title": title, "mb": rom.stat().st_size // 2 ** 20,
                    "slug": slug})
    return out


def slug_of(name: str) -> str:
    import unicodedata
    s = re.sub(r"^\d+ - ", "", name[:-4])
    s = re.sub(r"\s*[\(\[].*", "", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:40] or "game"


def archive(game_id: str) -> dict:
    """Removes a game from the studio by moving it to projets/_archive/ (nothing is deleted)."""
    g = games.get(game_id)
    config.ARCHIVE.mkdir(exist_ok=True)
    dest = config.ARCHIVE / g.id
    if dest.exists():
        dest = config.ARCHIVE / f"{g.id}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        shutil.move(str(g.path), str(dest))
    except Exception as e:
        return {"error": f"impossible de deplacer (dossier ouvert ailleurs ?) : {e}"}
    return {"ok": True, "moved_to": str(dest)}


def archived() -> list[str]:
    return sorted(p.name for p in config.ARCHIVE.iterdir() if p.is_dir()) if config.ARCHIVE.exists() else []


def restore(name: str) -> dict:
    src = config.ARCHIVE / name
    if not src.is_dir() or "/" in name or ".." in name:
        return {"error": "archive inconnue"}
    dest = config.PROJETS / re.sub(r"-\d{8}-\d{6}$", "", name)
    if dest.exists():
        return {"error": f"{dest.name} existe deja"}
    shutil.move(str(src), str(dest))
    return {"ok": True}


def clone(url: str) -> dict:
    """Takes a game someone published (GitHub URL): clones it into projets/."""
    m = re.match(r"^https://github\.com/[\w.-]+/([\w.-]+?)(\.git)?/?$", url.strip())
    if not m:
        return {"error": "URL GitHub attendue : https://github.com/<proprietaire>/<repo>"}
    name = re.sub(r"-decomp$", "", m.group(1).lower())
    dest = config.PROJETS / name
    if dest.exists():
        return {"error": f"{name} existe deja"}
    r = subprocess.run(["git", "clone", "-q", url.strip(), str(dest)], capture_output=True, text=True)
    if r.returncode:
        return {"error": r.stderr.strip()[-400:]}
    return {"ok": True, "game": name,
            "next": "Mettre la ROM dans extract/ (voir extract/README.md), puis lancer 'Compiler'."}


# ---------- publishing ----------
def unsafe_files(g) -> list[str]:
    """Tracked files that must never be in a public repo."""
    files = gitutil.git(g.path, "ls-files", "-z").stdout.split("\0")
    bad = []
    for f in files:
        if not f:
            continue
        p = g.path / f
        ext = p.suffix.lower()
        if ext in FORBIDDEN_EXT or f.startswith(("extract/", "build/")) and f != "extract/README.md":
            bad.append(f)
        elif p.exists() and p.stat().st_size > MAX_FILE:
            bad.append(f + " (trop gros)")
    return bad


TOPICS = ["decompilation", "matching-decompilation", "nintendo-ds", "reverse-engineering", "ds-decomp-studio"]


def set_topics(full_name: str):
    """Same topics on every game repo (the topic ds-decomp-studio is how the app finds published games)."""
    args = ["gh", "repo", "edit", full_name]
    for t in TOPICS:
        args += ["--add-topic", t]
    return subprocess.run(args, capture_output=True, text=True)


def repo_name(g) -> str:
    return f"{g.id}-decomp"


def publish(game_id: str, public=True, log=print) -> dict:
    g = games.get(game_id)
    if not g.ready:
        return {"error": "projet incomplet"}
    if g.remote():
        r = gitutil.git(g.path, "push", "-q", "origin", "HEAD")
        return {"ok": r.returncode == 0, "remote": g.remote(), "error": r.stderr.strip() if r.returncode else None}
    bad = unsafe_files(g)
    if bad:
        return {"error": "fichiers interdits suivis par git : " + ", ".join(bad[:10])}
    owner = config.settings().get("github_owner") or subprocess.run(
        ["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True).stdout.strip()
    if not owner:
        return {"error": "gh n'est pas connecte (gh auth login)"}
    config.save_settings({"github_owner": owner})
    name = repo_name(g)
    desc = f"Matching decompilation of {g.title} (Nintendo DS, {g.code or g.version}). No game assets included."
    log(f"creation de {owner}/{name} ({'public' if public else 'prive'})")
    r = subprocess.run(["gh", "repo", "create", f"{owner}/{name}", "--public" if public else "--private",
                        "--description", desc, "--source", str(g.path), "--remote", "origin"],
                       capture_output=True, text=True)
    if r.returncode:
        return {"error": (r.stderr or r.stdout).strip()[-400:]}
    branch = gitutil.git(g.path, "branch", "--show-current").stdout.strip() or "main"
    if branch != "main":
        gitutil.git(g.path, "branch", "-M", "main")
    r = gitutil.git(g.path, "push", "-q", "-u", "origin", "main", timeout=600)
    if r.returncode:
        return {"error": r.stderr.strip()[-400:]}
    set_topics(f"{owner}/{name}")
    return {"ok": True, "remote": f"https://github.com/{owner}/{name}"}


def published_on_github() -> list[dict]:
    """Games published by anyone with the topic ds-decomp-studio (to clone them)."""
    r = subprocess.run(["gh", "search", "repos", "--topic", "ds-decomp-studio", "--limit", "100", "--json",
                        "fullName,description,url"], capture_output=True, text=True)
    try:
        import json
        return json.loads(r.stdout)
    except Exception:
        return []
