"""Publishes the progress: the "Progress" section of every published game's README (tools/match.py progress), then
the table of every game in the Studio's README (readme.py), each committed and pushed. Every published game also
gets objdiff's report as progress/report.json.gz and the workflow that publishes it as the `<VERSION>_report`
artifact ByteMatch reads (bytematch.export): adding the repo on https://bytematch.dev/manage/new is then enough.
Games known to ByteMatch get its badges; those with an upload token also get the report uploaded directly.

    python studio.py progress                 # every game that has a GitHub repo, then the Studio
    python studio.py progress --game rayman-rr --no-push

A game busy with another tool (build/pipeline.lock held by a running process) is skipped: its report would be
read while it changes.
"""
import json
import re
import subprocess
import sys

from . import bytematch, config, games, gitutil, readme

MSG = "README: progress section (tools/match.py progress)\n\nUpdated by DS Decomp Studio (job progress)."


def busy(g) -> str:
    lock = g.path / "build" / "pipeline.lock"
    if not lock.exists():
        return ""
    try:
        info = json.loads(lock.read_text())
        import psutil
        if psutil.pid_exists(int(info.get("pid", 0))):
            return info.get("owner", "another tool")
    except Exception:
        return "verrou illisible"  # unsure = busy: never commit a README while a pipeline may be writing
    return ""


def fix_title(g) -> None:
    """The README title of the template is the folder name: use the game's real title."""
    p = g.path / "README.md"
    t = p.read_text(encoding="utf-8")
    n = re.sub(r"^# .*? decompilation \(", f"# {g.title} decompilation (", t, count=1, flags=re.M)
    if n != t:
        p.write_text(n, encoding="utf-8", newline="\n")


def push_head(repo) -> object:
    """git push; when GitHub has commits made elsewhere (a README edited on the site), they are taken first
    (rebase: our commits go on top) and the push is tried again."""
    r = gitutil.git(repo, "push", "-q", "origin", "HEAD", timeout=300)
    if r.returncode and "fetch first" in r.stderr + r.stdout and config.in_monorepo(repo):
        # All-nds-decomp-games: merge, never rebase/autostash (other games' jobs write in the same working tree)
        if not gitutil.pull(repo):
            r = gitutil.git(repo, "push", "-q", "origin", "HEAD", timeout=300)
    elif r.returncode and "fetch first" in r.stderr + r.stdout:
        branch = gitutil.git(repo, "branch", "--show-current").stdout.strip() or "main"
        if gitutil.git(repo, "pull", "-q", "--rebase", "--autostash", "origin", branch, timeout=300).returncode == 0:
            r = gitutil.git(repo, "push", "-q", "origin", "HEAD", timeout=300)
        else:
            gitutil.git(repo, "rebase", "--abort")
    return r


def commit_push(repo, paths, message, push=True, log=print) -> None:
    if not gitutil.git(repo, "status", "--porcelain", "--", *paths).stdout.strip():
        ahead = gitutil.git(repo, "rev-list", "--count", "@{u}..HEAD").stdout.strip()
        if push and ahead not in ("", "0") and gitutil.has_remote(repo):
            # README unchanged, but commits wait (matches, tools): they are part of the progress
            r = push_head(repo)
            log(f"  inchange, {ahead} commit(s) pousse(s)" if r.returncode == 0 else "  push rate : " + r.stderr.strip()[-300:])
        else:
            log("  inchange")
        return
    gitutil.git(repo, "add", "--", *paths)  # new files too (report, workflow): commit -- <path> only takes known files
    r = gitutil.git(repo, "commit", "-q", "-m", message, "--", *paths)
    if r.returncode:
        log("  commit impossible : " + (r.stderr or r.stdout).strip()[-300:])
        return
    if push and gitutil.has_remote(repo):
        r = push_head(repo)
        log("  pousse" if r.returncode == 0 else "  push rate : " + r.stderr.strip()[-300:])
    else:
        log("  commite (pas de push)")


def run(game_id: str = "", push: bool = True, log=print) -> None:
    todo = [games.get(game_id)] if game_id else [g for g in games.all_games() if g.ready and g.remote()]
    for i, g in enumerate(todo, 1):
        log(f"[{i}/{len(todo) + 1}] {g.id}")
        who = busy(g)
        if who:
            log(f"  saute : {who} travaille sur ce jeu")
            continue
        # the README needs no build (match.py reads the configuration); ByteMatch needs objdiff's report, which the
        # game's CI publishes from progress/report.json.gz (bytematch.export): always rebuilt for published games
        rebuild = ["--rebuild"] if bytematch.repo_of(g) else []
        if rebuild:
            subprocess.run([sys.executable, config.build_tool(g.path, "configure.py"), g.version], cwd=g.path,
                           capture_output=True)
        r = subprocess.run([sys.executable, config.build_tool(g.path, "match.py"), "progress", *rebuild], cwd=g.path,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            log("  echec : " + (r.stdout + r.stderr).strip().splitlines()[-1][:300] if (r.stdout + r.stderr).strip()
                else "  echec")
            continue
        log("  " + r.stdout.strip().splitlines()[-1])
        fix_title(g)
        if bytematch.registered(g):
            bytematch.add_badges(g)
        files = ["README.md"] + bytematch.export(g)
        commit_push(g.path, files, MSG + "\n", push, log)
        if push:
            bytematch.upload(g, log)  # for the commit now on GitHub; nothing without a token
    log(f"[{len(todo) + 1}/{len(todo) + 1}] DS Decomp Studio")
    readme.update()
    commit_push(config.STUDIO, ["README.md"], "README: progress of every game (job progress)\n", push, log)
