"""Machine tasks (build, verify, auto_match, moulinette, Qwen...) in a queue.

Rules: one task at a time per game (they all write in the project), at most `max_parallel_jobs` tasks at once.
Each task runs in Git Bash after `source env.sh`, its full log goes to data/logs/<n>.log.
"""
import json
import os
import re
import subprocess
import threading
import time

from . import config, games

LOGS = config.DATA / "logs"
LOGS.mkdir(exist_ok=True)
STATE = config.DATA / "jobs.json"
MOULINETTE = config.PROJETS / "rayman-rr" / "tools" / "moulinette.py"

# id: label, scope ("game" runs in the project, "global" in the workspace), expected seconds, description
DEFS = {
    "status": ("Statut de progression", "game", 20, "match.py status"),
    "build": ("Compiler (ninja)", "game", 120, "reconstruit la ROM"),
    "verify": ("Verifier (VERIFY PASSED)", "game", 90, "ROM identique + fichiers complets a 100 %"),
    "dis": ("Desassembler", "game", 60, "regenere build/<ver>/asm"),
    "culprits": ("Trouver ce qui casse la ROM", "game", 900, "compare la ROM reconstruite octet par octet et retire les fichiers fautifs"),
    "auto": ("Auto-match", "game", 3000,
             "1) clone les jumelles deja matchees (ici ou dans nos autres jeux, sans IA), 2) reprend les matchs des "
             "autres decomps (NitroSDK, pret...), 3) m2c + compile + compare sur toutes les fonctions"),
    "permute": ("Auto-match + permuter", "game", 2400, "permuter sur les N near misses"),
    "moulinette": ("Moulinette complete", "game", 1800, "build, brouillons, auto-match, verify, commit (+push)"),
    "qwen": ("Qwen (agents)", "game", 3600, "agents IA locaux (Ollama) sur les fonctions d'un ou plusieurs blocs"),
    "sync_tools": ("Mettre a jour les outils", "game", 60, "copie la derniere version des outils de rayman-rr (auto_match...)"),
    "sync_all": ("Mettre a jour les outils de tous les jeux", "global", 300, "idem pour chaque jeu"),
    "scan": ("Indexer les empreintes (fingerprint)", "global", 180, "met a jour fpdb.sqlite"),
    "donors": ("Reprendre les matchs des autres decomps", "game", 1200,
               "fonctions deja decompilees ailleurs (NitroSDK, pret...) : compile + compare, fichiers fautifs "
               "retires (build ninja + bisection), puis un verify complet"),
    "clone": ("Cloner les jumelles (sans IA)", "game", 900,
              "fonctions au code identique (ou aux constantes pres) a une fonction deja matchee, ici ou dans un autre "
              "de nos jeux : C copie + renomme, compile + compare, puis verify"),
    "clone_all": ("Cloner les jumelles dans tous les jeux", "global", 7200,
                  "le clonage dans chaque jeu (1 match dans un jeu = 1 match dans chaque jeu qui a la meme fonction), verify, puis commit + push des jeux qui passent"),
    "misses": ("Rejouer les essais rates", "game", 1800,
               "base des essais rates (missdb : Qwen, hunt, Claude, editeur) : chaque C rate est essaye sur toutes les "
               "fonctions non matchees du jeu qui ont la meme forme, misses de TOUS nos jeux ; les DONNEES aussi "
               "(.data/.rodata : essais rates + donnees deja matchees dans nos autres jeux), puis verify + commit"),
    "misses_all": ("Rejouer les essais rates dans tous les jeux", "global", 7200,
                   "les essais rates de chaque jeu (A) essayes sur tous les autres jeux (B, C, D...) : import des "
                   "anciens essais, rejeu, verify, commit + push des jeux qui passent"),
    "dataset": ("Exporter le jeu de donnees (LoRA)", "global", 120,
                "paires assembleur -> C exact de tous les jeux, au format d'entrainement (datasets/*.jsonl)"),
    "examples": ("Indexer les exemples pour l'IA", "global", 400,
                 "les fonctions deja matchees de tous les jeux (assembleur -> C exact) : Qwen recoit les plus proches "
                 "de chaque fonction comme exemples"),
    "donors_index": ("Indexer les decomps externes", "global", 1800,
                     "compile les depots de decomps-externes/ et met a jour donors.sqlite"),
    "names": ("Nommer (SDK, MSL...)", "game", 900,
              "vrais noms des fonctions et donnees reprises des autres decomps (empreinte + appels), renomme "
              "symbols.txt, sources et fichiers, puis verifie la ROM"),
    "regroup": ("Regrouper en vrais fichiers", "game", 900,
                "fusionne les src/auto et src/donor voisins venant du meme fichier d'origine (src/nitro/os/os_thread.c...), "
                "chaque fusion compilee et comparee, puis la ROM"),
    "cleanup": ("Nettoyer le C de m2c", "game", 600,
                "retire les notes de m2c (/* extern */...), lignes vides, clang-format ; la ROM est reconstruite"),
    "progress": ("Publier l'avancement", "global", 900,
                 "met a jour la section Progress du README de chaque jeu publie (match.py progress) et le tableau "
                 "de tous les jeux du README du Studio, puis commit + push"),
    "new_project": ("Ajouter un jeu", "global", 600, "dsd init + build depuis une ROM de roms/"),
    "publish": ("Publier sur GitHub", "game", 180, "cree le repo public et pousse"),
    "wb_submit": ("Integrer une fonction (editeur)", "game", 180,
                  "le C de l'editeur dans src/auto + delinks.txt, puis la ROM reconstruite : garde seulement si elle "
                  "reste identique (pas encore commite)"),
    "wb_commit": ("Valider les matchs en attente", "game", 900,
                  "verify complet une fois pour toutes les fonctions integrees (editeur, Claude...), retire les "
                  "fichiers refuses, puis commit (+ push)"),
    "ghidra": ("Brouillons Ghidra", "game", 1800,
               "decompile avec Ghidra les fonctions sans brouillon m2c (build/ghidra/) : un 2e point de depart pour "
               "Qwen et Claude"),
    "split": ("Decouper une fonction fusionnee", "game", 300,
              "coupe une fonction en deux dans symbols.txt (dsd en a fusionne deux), garde seulement si la ROM reste "
              "identique"),
}

_lock = threading.RLock()
jobs: dict = {}
_seq = [0]
_procs: dict = {}


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


def _t(game, name: str) -> str:
    """A matching tool for a command run with cwd = the game: its tools/ copy, else gametools/ (quoted)."""
    p = config.game_tool(game.path, name)
    return f"tools/{name}" if p.parent != config.GAMETOOLS else _q(p.as_posix())


def _block_functions(game, block_id: str) -> list[str]:
    from . import blocks as _blocks
    b = next((b for b in _blocks.load(game)["blocks"] if b["id"] == block_id), None)
    if b is None:
        raise KeyError(f"bloc inconnu : {block_id}")
    return b["functions"]


def command(jid: str, game, p: dict) -> str:
    v = game.version if game else ""
    if jid == "status":
        return "python tools/match.py status"
    if jid == "build":
        return "ninja"
    if jid == "verify":
        return "python tools/match.py verify"
    if jid == "culprits":
        return f"python {_t(game, 'find_culprits.py')}" + (" --fix" if p.get("fix") else "") + (" --any" if p.get("any") else "")
    if jid == "dis":
        return f"rm -rf build/{v}/asm; ninja dis"
    if jid in ("auto", "permute"):
        env = "AUTO_FRESH=1 " if p.get("fresh") else ""
        cmd = f"{env}python {_t(game, 'auto_match.py')}"
        if p.get("jobs"):
            cmd += f" -j {int(p['jobs'])}"
        if jid == "permute" or p.get("permute"):
            cmd += f" --permute {int(p.get('permute') or p.get('n') or 10)} --minutes {float(p.get('minutes') or 2)}"
        if p.get("multi"):
            cmd += " --multi"
        if int(p.get("batch") or 0):
            cmd += f" --batch {int(p['batch'])}"
        if p.get("dry_run"):
            cmd += " --dry-run"
        if p.get("cached_only"):
            cmd += " --cached-only"
        if jid == "auto" and not p.get("cached_only") and not p.get("no_reuse"):
            # reuse first (no compiler guessing): twins in our games, then external decomps; a failing step does not stop the next
            pre = []
            dry = " --dry-run" if p.get("dry_run") else ""
            if config.game_tool(game.path, "clone_match.py").exists():
                pre.append(f"python {_t(game, 'clone_match.py')} --other-games" + dry)
            if config.game_tool(game.path, "donor_match.py").exists():
                pre.append(f"python {_t(game, 'donor_match.py')}" + dry + (f" -j {int(p['jobs'])}" if p.get("jobs") else ""))
            cmd = "; ".join(pre + [cmd])
            # the misses of every game (AI, hand sessions, these near misses) on what is still unmatched here
            if config.game_tool(game.path, "missdb.py").exists():
                cmd += f"; python {_t(game, 'missdb.py')} replay --all-games" + (" --dry-run" if p.get("dry_run") else "")
        return cmd
    if jid == "moulinette":
        cmd = f"python {_q(MOULINETTE.as_posix())} --game {_q(game.id)}"
        if not p.get("push"):
            cmd += " --no-push"
        if p.get("permute_near"):
            cmd += f" --permute-near {int(p['permute_near'])} --near-minutes {float(p.get('near_minutes') or 5)}"
        if p.get("restart"):
            cmd += f" --restart {_q(p['restart'])}"
        for flag in ("no_drafts", "no_auto", "no_commit"):
            if p.get(flag):
                cmd += " --" + flag.replace("_", "-")
        return cmd
    if jid == "qwen":
        s = config.settings()
        blocks = p.get("blocks") or p.get("block")
        if isinstance(blocks, list):
            blocks = ",".join(blocks)
        # hard: the functions earlier runs left a few instructions away (build/qwen_auto/hard.json), for a bigger model
        target = " --hard" if p.get("hard") else f" --blocks {_q(blocks)}"
        small = p.get("small_model", s.get("qwen_small_model", ""))
        return (f"python {_q((config.WORKERS / 'qwen_block.py').as_posix())} --project {_q(game.path.as_posix())}"
                f"{target} --model {_q(p.get('model') or (s.get('qwen_hard_model') if p.get('hard') else '') or s['qwen_model'])}"
                + (f" --small-model {_q(small)}" if small and not p.get("hard") else "") +
                f" --minutes {float(p.get('minutes') or s['qwen_minutes'])}"
                f" --agents {int(p.get('agents') or s['qwen_agents'])} --max {int(p.get('max') or 0)}"
                f" --batch {int(p.get('batch') or 10)}"
                f" --variants {int(p.get('variants') or s['qwen_variants'])}"
                f" --group {int(p.get('group') or s['qwen_group'])}"
                f" --backend {_q(p.get('backend') or s['qwen_backend'])} --server {_q(p.get('server') or s['qwen_server'])}")
    if jid == "sync_tools":
        return f"python {_q((config.STUDIO / 'studio.py').as_posix())} sync-tools {_q(game.id)}"
    if jid == "sync_all":
        return f"python {_q((config.STUDIO / 'studio.py').as_posix())} sync-tools"
    if jid == "clone":
        cmd = f"python {_t(game, 'clone_match.py')}"
        if p.get("list"):
            return cmd + " --list"
        if p.get("other_games", True):
            cmd += " --other-games"
        if p.get("block"):
            cmd += " --names " + _q(",".join(_block_functions(game, p["block"])))
        if int(p.get("max") or 0):
            cmd += f" --max {int(p['max'])}"
        if p.get("dry_run"):
            cmd += " --dry-run"
        return cmd
    if jid == "clone_all":
        # one game after the other; a game busy with another pipeline is skipped (its lock), the others go on
        return "; ".join(f"echo {_q('== projets/' + g.id)}; (cd {_q('projets/' + g.id)} && "
                         f"python {_t(g, 'clone_match.py')} --other-games --commit --push)"
                         for g in games.all_games() if g.ready and config.game_tool(g.path, "clone_match.py").exists())
    if jid == "misses":
        cmd = f"python {_t(game, 'missdb.py')}"
        pre = f"{cmd} import; " if p.get("import", True) else ""
        cmd = pre + f"{cmd} replay" + ("" if p.get("this_game") else " --all-games")
        if p.get("block"):
            cmd += " --names " + _q(",".join(_block_functions(game, p["block"])))
        if p.get("dry_run"):
            return cmd + " --dry-run"
        return cmd + " --commit" + (" --push" if p.get("push", True) else "")
    if jid == "misses_all":
        # 1) every game records its older tries, 2) every game replays the misses of all games
        ready = [g for g in games.all_games() if g.ready and config.game_tool(g.path, "missdb.py").exists()]
        imp = "; ".join(f"(cd {_q('projets/' + g.id)} && python {_t(g, 'missdb.py')} import)" for g in ready)
        rep = "; ".join(f"echo {_q('== projets/' + g.id)}; (cd {_q('projets/' + g.id)} && "
                        f"python {_t(g, 'missdb.py')} replay --all-games --commit --push)" for g in ready)
        return f"{imp}; {rep}; python {_t(ready[0], 'missdb.py')} stats" if ready else "echo aucun jeu"
    if jid == "donors":
        # by block (the functions of one block), by batch (--max N matches), or only the list of candidates
        cmd = f"python {_t(game, 'donor_match.py')}"
        if p.get("list"):
            return cmd + " --list"
        if p.get("block"):
            names = _q(",".join(_block_functions(game, p["block"])))
            cmd += " --names " + names
            # the block's twins already matched in our games (or clones here) come first: no compiler guessing
            if config.game_tool(game.path, "clone_match.py").exists():
                cmd = f"python {_t(game, 'clone_match.py')} --other-games --names {names}; " + cmd
        if int(p.get("max") or 0):
            cmd += f" --max {int(p['max'])}"
        if int(p.get("jobs") or 0):
            cmd += f" -j {int(p['jobs'])}"
        if p.get("bisect") not in (None, ""):
            cmd += f" --bisect {int(p['bisect'])}"
        if p.get("dry_run"):
            cmd += " --dry-run"
        return cmd + f" && python {_t(game, 'donor_match.py')} --list"
    if jid == "examples":
        return f"python {_q((config.WORKERS / 'examples.py').as_posix())} build"
    if jid == "dataset":
        return f"python {_q((config.WORKERS / 'dataset.py').as_posix())}"
    if jid == "donors_index":
        return "python tools/donors.py index"
    if jid in ("names", "regroup", "cleanup"):
        return f"python {_t(game, jid + '.py')}" + (" --dry-run" if p.get("dry_run") else "")
    if jid == "progress":
        return (f"python {_q((config.STUDIO / 'studio.py').as_posix())} progress"
                + (f" --game {_q(p['game'])}" if p.get("game") else "") + (" --no-push" if p.get("no_push") else ""))
    if jid == "scan":
        return "python tools/fingerprint.py scan projets/_analyse/*"
    if jid == "new_project":
        return f"python tools/new_project.py {_q(p['slug'])} {_q(p['rom'])}"
    if jid == "wb_submit":
        return f"python {_t(game, 'workbench.py')} submit {_q(p['name'])} {_q(p['file'])} --who {_q(p.get('who') or 'editeur')}"
    if jid == "wb_commit":
        return f"python {_t(game, 'workbench.py')} commit" + (" --push" if p.get("push") else "")
    if jid == "split":
        return f"python {_t(game, 'workbench.py')} split {_q(p['name'])} {_q(p['at'])}"
    if jid == "ghidra":
        cmd = f"python {_t(game, 'ghidra_draft.py')}"
        if p.get("block"):
            cmd += " --names " + _q(",".join(_block_functions(game, p["block"])))
        elif p.get("names"):
            cmd += " --names " + _q(p["names"])
        if int(p.get("max") or 0):
            cmd += f" --max {int(p['max'])}"
        return cmd
    if jid == "publish":
        return f"python {_q((config.STUDIO / 'studio.py').as_posix())} publish {_q(game.id)} --yes"
    raise KeyError(jid)


def _save():
    snap = [{k: v for k, v in j.items() if k != "log"} for j in jobs.values()]
    STATE.write_text(json.dumps(snap[-200:], ensure_ascii=False), encoding="utf-8")


def _restore():
    try:
        for j in json.loads(STATE.read_text(encoding="utf-8")):
            if j["state"] in ("running", "queued"):
                j["state"] = "interrupted"
            j["log"] = []
            jobs[j["n"]] = j
            _seq[0] = max(_seq[0], j["n"])
    except Exception:
        pass


def submit(jid: str, game_id: str | None, params: dict | None = None, who: str = "") -> dict:
    if jid not in DEFS:
        return {"error": f"tache inconnue : {jid}"}
    label, scope, expect, _ = DEFS[jid]
    params = params or {}
    game = None
    if scope == "game":
        try:
            game = games.get(game_id)
        except KeyError as e:
            return {"error": str(e)}
        if not game.ready and jid != "publish":
            return {"error": "projet incomplet : dsd init n'a pas abouti"}
        if jid in ("auto", "permute") and (game.path / ".auto_done").exists() and not params.get("force"):
            return {"error": "auto-match deja termine pour ce jeu (cocher 'forcer' pour relancer)"}
        if jid == "qwen" and not (params.get("block") or params.get("blocks")):
            return {"error": "choisir un bloc pour Qwen"}
    try:
        cmd = command(jid, game, params)
    except KeyError as e:
        return {"error": f"parametre manquant : {e}"}
    with _lock:
        _seq[0] += 1
        n = _seq[0]
        jobs[n] = {"n": n, "id": jid, "label": label, "game": game.id if game else None, "params": params,
                   "cmd": cmd, "who": who, "state": "queued", "queued": time.time(), "started": None, "ended": None,
                   "pct": 0, "expect": expect, "rc": None, "log": []}
        _save()
    _wake.set()
    return {"n": n}


def _start(j):
    game = games.get(j["game"]) if j["game"] else None
    cwd = game.path if game else config.ROOT
    env_line = f"source {_q(config.ENV_SH.as_posix())} >/dev/null 2>&1; " if config.ENV_SH.exists() else ""
    if config.FPDB.exists() and j["id"] == "qwen":
        env_line += f"export DSSTUDIO_ROOT={_q(config.ROOT.as_posix())}; "
    full = f"{env_line}cd {_q(cwd.as_posix())} && {j['cmd']}"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    j["state"], j["started"] = "running", time.time()
    logf = (LOGS / f"{j['n']}.log").open("w", encoding="utf-8")
    logf.write(f"$ {j['cmd']}\n(dans {cwd})\n\n")
    logf.flush()  # visible in the Queue tab right away, even before the task prints anything
    try:
        p = subprocess.Popen([str(config.BASH), "-c", full], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=env, creationflags=0x08000000)
    except Exception as e:
        j["state"], j["ended"] = "failed", time.time()
        j["log"].append(f"impossible de lancer Git Bash : {e}")
        logf.close()
        return
    _procs[j["n"]] = p

    def pump():
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            logf.write(line + "\n")
            logf.flush()
            j["log"].append(line)
            del j["log"][:-300]
            m = re.search(r"\[(\d+)/(\d+)\]", line)
            if m:
                j["pct"] = max(j["pct"], int(100 * int(m.group(1)) / max(int(m.group(2)), 1)))
        p.wait()
        logf.close()
        with _lock:
            j["rc"], j["ended"] = p.returncode, time.time()
            if j["state"] == "running":
                j["state"] = "done" if p.returncode == 0 else "failed"
            if j["state"] == "done":
                j["pct"] = 100
            if j["id"] == "verify" and j["state"] in ("done", "failed"):
                ok = any("VERIFY PASSED" in l for l in j["log"])
                games.set_health(j["game"], ok, "" if ok else (j["log"][-1] if j["log"] else "echec"))
            _procs.pop(j["n"], None)
            _save()
        _wake.set()
    threading.Thread(target=pump, daemon=True).start()


_wake = threading.Event()


def _scheduler():
    while True:
        _wake.wait(5)
        _wake.clear()
        with _lock:
            limit = int(config.settings().get("max_parallel_jobs", 2))
            running = [j for j in jobs.values() if j["state"] == "running"]
            busy = {j["game"] for j in running}
            for j in sorted((j for j in jobs.values() if j["state"] == "queued"), key=lambda j: j["n"]):
                if len(running) >= limit:
                    break
                if j["game"] in busy and j["game"] is not None:
                    continue
                if j["game"] is None and None in busy:  # global tasks also one at a time
                    continue
                _start(j)
                running.append(j)
                busy.add(j["game"])
            _save()


def start_scheduler():
    _restore()
    threading.Thread(target=_scheduler, daemon=True).start()


def cancel(n: int) -> bool:
    with _lock:
        j = jobs.get(n)
        if not j:
            return False
        if j["state"] == "queued":
            j["state"], j["ended"] = "cancelled", time.time()
            _save()
            return True
        p = _procs.get(n)
        if j["state"] == "running" and p:
            try:  # taskkill /T needs WMI, broken on some PCs: kill the tree with psutil
                import psutil
                parent = psutil.Process(p.pid)
                for c in parent.children(recursive=True):
                    c.kill()
                parent.kill()
            except Exception:
                p.kill()
            j["state"], j["ended"] = "stopped", time.time()
            _save()
            return True
    return False


def view(limit=40) -> list[dict]:
    out = []
    now = time.time()
    for n, j in sorted(jobs.items(), reverse=True)[:limit]:
        el = ((j["ended"] or now) - j["started"]) if j["started"] else 0
        pct = j["pct"]
        if j["state"] == "running" and pct == 0:
            pct = min(int(100 * el / max(j["expect"], 1)), 95)
        out.append({k: j[k] for k in ("n", "id", "label", "game", "state", "who", "params", "rc")} |
                   {"pct": pct, "elapsed": int(el), "queued_at": j["queued"], "log": j["log"][-80:]})
    return out


def full_log(n: int) -> str:
    p = LOGS / f"{int(n)}.log"
    return p.read_text(encoding="utf-8", errors="replace")[-200000:] if p.exists() else ""


def _whole_chars(b: bytes) -> bytes:
    """b without a UTF-8 character cut in the middle at its end (the job is still writing it)."""
    for i in range(1, min(4, len(b)) + 1):
        c = b[-i]
        if c & 0xC0 == 0x80:
            continue
        if c >= 0xC0:
            need = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
            return b if i >= need else b[:-i]
        return b
    return b


def log_since(n: int, start: int = -1) -> dict:
    """{"log", "size", "append"}: the bytes after `start` when the page already has the beginning (append=True),
    else the last 200 KB. The page asks every few seconds: a long log is not sent again in full each time."""
    p = LOGS / f"{int(n)}.log"
    if not p.exists():
        return {"log": "", "size": 0, "append": False}
    size = p.stat().st_size
    if 0 <= start <= size and size - start <= 200000:
        with p.open("rb") as f:
            f.seek(start)
            data = _whole_chars(f.read(size - start))
        return {"log": data.decode("utf-8", errors="replace"), "size": start + len(data), "append": True}
    start = max(0, size - 200000)
    with p.open("rb") as f:
        f.seek(start)
        data = _whole_chars(f.read(size - start))
    return {"log": data.decode("utf-8", errors="replace"), "size": start + len(data), "append": False}
