"""Small git helpers. Everything the studio commits lives in `.studio/` of the game repo, and is committed alone
(`git commit -- .studio`), so work in progress in src/ is never swept into a studio commit."""
import subprocess
import time
from pathlib import Path

from . import config


def git(repo: Path, *args, timeout=120) -> subprocess.CompletedProcess:
    """git in `repo` (a game folder). In All-nds-decomp-games several jobs share one index: a command that finds
    index.lock taken by another job waits and tries again instead of failing."""
    for attempt in range(40):
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout,
                           creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
        if r.returncode == 0 or "index.lock" not in (r.stderr or ""):
            return r
        time.sleep(0.5 + attempt * 0.1)
    return r


def has_remote(repo: Path) -> bool:
    return bool(git(repo, "remote").stdout.strip())


def _pull_monorepo(repo: Path) -> str:
    """All-nds-decomp-games: every game shares one branch and one working tree where other jobs are writing. No rebase
    and no autostash (they would rewrite or stash the files of every game): fetch, and merge only when the remote has
    new commits. A merge leaves the uncommitted files of other games alone; it stops (and is undone) only if a file
    it changes is also changed here."""
    git(repo, "fetch", "-q", "origin")
    behind = git(repo, "rev-list", "--count", "HEAD..@{u}").stdout.strip()
    if behind in ("", "0"):
        return ""
    r = git(repo, "merge", "--no-edit", "-q", "@{u}")
    if r.returncode != 0:
        git(repo, "merge", "--abort")
        return (r.stderr or r.stdout).strip()[-400:]
    return ""


def pull(repo: Path) -> str:
    """Brings the remote state in (claims of the others). Returns an error message or ''."""
    if not has_remote(repo):
        return ""
    if config.in_monorepo(repo):
        return _pull_monorepo(repo)
    r = git(repo, "pull", "--rebase", "--autostash", "-q")
    if r.returncode != 0:
        git(repo, "rebase", "--abort")
        return (r.stderr or r.stdout).strip()[-400:]
    return ""


PRECOMMIT = ".pre-commit-config.yaml"
EXCLUDE_LINE = "exclude: ^\\.studio/  # queue data of DS Decomp Studio (clang-format would reformat the JSON)\n"


def ensure_ci_exclude(repo: Path) -> bool:
    """The game repos run clang-format in CI, and clang-format also formats .json files: keep .studio/ out of
    pre-commit. Returns True if the config file was changed."""
    p = repo / PRECOMMIT
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    if "^\\.studio/" in text:
        return False
    p.write_text(EXCLUDE_LINE + text, encoding="utf-8", newline="\n")
    return True


def commit_studio(repo: Path, message: str) -> str:
    """Commits the .studio folder only (plus the pre-commit exclusion of .studio). Returns an error message or ''."""
    paths = [config.STUDIO_DIR]
    if ensure_ci_exclude(repo) or git(repo, "diff", "--name-only", "--", PRECOMMIT).stdout.strip():
        paths.append(PRECOMMIT)
    git(repo, "add", "-A", "--", *paths)
    if not git(repo, "diff", "--cached", "--name-only", "--", *paths).stdout.strip():
        return ""
    r = git(repo, "commit", "-q", "-m", message, "--", *paths)
    return "" if r.returncode == 0 else (r.stderr or r.stdout).strip()[-400:]


def push(repo: Path) -> str:
    if not has_remote(repo) or not config.settings().get("push_claims", True):
        return ""
    for _ in range(3):
        r = git(repo, "push", "-q", "origin", "HEAD")
        if r.returncode == 0:
            return ""
        err = pull(repo)
        if err:
            return err
    return (r.stderr or r.stdout).strip()[-400:]
