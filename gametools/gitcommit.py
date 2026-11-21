"""Commit exactly the files a tool changed, nothing else, safely in a repository shared by many games.

In All-nds-decomp-games every game shares one index: `git commit` alone would also commit what another job staged
for another game. commit_paths() commits only the given paths (`git commit -- <paths>`, read from a file so the
command line never gets too long), with their current content, and retries while another job holds index.lock.

    import gitcommit
    ok, err = gitcommit.commit_paths(ROOT, ["src/auto/f.c", "config/eu"], "Match 1 function")
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path


def git(cwd, *args, **kw) -> subprocess.CompletedProcess:
    for attempt in range(40):
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace", **kw)
        if r.returncode == 0 or "index.lock" not in (r.stderr or ""):
            return r
        time.sleep(0.5 + attempt * 0.1)
    return r


def _known(cwd: Path, paths: list[str]) -> list[str]:
    """Paths git can take: existing files/folders, or tracked files that were deleted (relative to cwd)."""
    missing = [p for p in paths if not (Path(cwd) / p).exists()]
    if not missing:
        return list(paths)
    tracked = set(git(cwd, "ls-files", "-z", "--", *missing).stdout.split("\0")) if len(missing) < 200 else \
        set(git(cwd, "ls-files", "-z").stdout.split("\0"))
    return [p for p in paths if (Path(cwd) / p).exists() or p in tracked]


def commit_paths(cwd, paths, message: str, exclude=()) -> tuple[bool, str]:
    """git add + git commit of `paths` only (relative to cwd = the game). `exclude`: paths inside them to leave out
    (generated files). Returns (committed, error); (False, '') when there was nothing to commit."""
    cwd = Path(cwd)
    paths = _known(cwd, [str(p).replace("\\", "/") for p in paths])
    if not paths:
        return False, ""
    specs = paths + [f":(exclude){e}" for e in exclude]
    with tempfile.TemporaryDirectory() as tmp:
        spec_file = Path(tmp) / "paths"
        spec_file.write_bytes(b"\0".join(s.encode("utf-8") for s in specs))
        msg_file = Path(tmp) / "msg"
        msg_file.write_text(message.rstrip("\n") + _trailer(message), encoding="utf-8", newline="\n")
        common = [f"--pathspec-from-file={spec_file}", "--pathspec-file-nul"]
        r = git(cwd, "add", "-A", *common)
        if r.returncode:
            return False, (r.stderr or r.stdout).strip()[-400:]
        r = git(cwd, "commit", "-q", "-F", str(msg_file), *common)
        if r.returncode:
            text = (r.stderr or "") + (r.stdout or "")
            if any(s in text for s in ("nothing to commit", "nothing added to commit", "no changes added to commit")):
                return False, ""
            return False, text.strip()[-400:]
    return True, ""


def _trailer(message: str) -> str:
    """$COMMIT_TRAILER (e.g. a Co-Authored-By line set by an agent round) added once at the end."""
    t = os.environ.get("COMMIT_TRAILER", "").strip()
    return "\n" if not t or t in message else f"\n\n{t}\n"


def push(cwd) -> tuple[bool, str]:
    """git push of the current branch when the repository has a remote (the whole single repository: fine)."""
    if not git(cwd, "remote").stdout.strip():
        return False, ""
    r = git(cwd, "push", "-q", "origin", "HEAD")
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-300:]


def game_log(cwd, *args) -> str:
    """git log restricted to this game's folder (`-- .`): in the single repository HEAD may be another game's."""
    return git(cwd, "log", *args, "--", ".").stdout
