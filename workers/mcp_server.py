#!/usr/bin/env python3
"""MCP server of DS Decomp Studio: Claude Code, Codex or any MCP client works on the games directly.

    claude mcp add ds-studio -- "<toolbox>/.venv/Scripts/python.exe" "<toolbox>/studio/workers/mcp_server.py"

(or `python studio/studio.py mcp-config` prints the command). Standard library only: JSON-RPC 2.0 over stdio, one
message per line. Every tool works through the game's own tools/workbench.py (compiled and judged exactly like
auto_match: original compiler, byte for byte, fake matches refused) and the studio's blocks (claims shared through
each game's git repository), so an agent here and the Qwen agents never work on the same functions.
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))
_OUT = sys.stdout
sys.stdout = sys.stderr  # anything the studio modules print must not corrupt the protocol

from dsstudio import blocks, config, gameenv, games, toolsync  # noqa: E402

PROTOCOL = "2025-06-18"
INSTRUCTIONS = """DS Decomp Studio: matching decompilation of Nintendo DS games (mwccarm, ARM9 main module).
Workflow: list_games -> claim_block (always claim before working: Qwen agents and people share the queue) ->
for each function of the block: get_function (assembly, draft, calls, data, look-alikes already matched) ->
compile_and_diff in a loop until "match" -> submit_match (puts it in the game and rebuilds the ROM: kept only if it
stays byte-identical) -> after a few matches, commit_matches (full verify once, then a git commit) ->
release_block (finished=true when everything is matched).
Rules: plain C only. asm, new #define/#pragma/#include lines, ##, _Pragma, __declspec/__attribute__ and machine code
written as numbers are refused (fake matches). Never make the function static. ASCII only. Keep the function's name.
Types and prototypes everyone should use go into include/engine.h with edit_header (kept only if every matched file
still compiles to the same bytes). Source files include engine.h BEFORE m2c.h (clang-format sorts includes), so
engine.h must stand alone: put #include "m2c.h" above anything that uses s32/u8/... there. Data (tables, strings) can be declared in C: read_data gives a declaration,
check_data compares what a C file defines with the game."""

AGENT = "claude"


def text(obj) -> dict:
    return {"content": [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, indent=1)}]}


def game(gid: str):
    g = games.get(gid)
    if not g.ready:
        raise KeyError(f"{gid}: the game is not ready (its ROM does not rebuild yet)")
    return g


def with_file(source: str):
    """A temporary .c file holding `source` (workbench reads files)."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".c", delete=False, encoding="utf-8", newline="\n")
    tmp.write(source)
    tmp.close()
    return Path(tmp.name)


_EXAMPLES = None


def similar(lines: list[str], size: int, gid: str, name: str, n: int = 3) -> list[dict]:
    global _EXAMPLES
    try:
        if _EXAMPLES is None:
            sys.path.insert(0, str(STUDIO / "workers"))
            import examples
            import prompt_tools as pt
            _EXAMPLES = (examples.Examples() if examples.DB.exists() else False, pt)
        ex, pt = _EXAMPLES
        if not ex:
            return []
        return [{"similarity": round(s, 2), "game": r[0], "name": r[1], "size": r[2], "asm": r[4], "c": r[5]}
                for s, r in ex.similar(pt.mnemonic_list(lines), size, gid, name, n)]
    except Exception as e:
        return [{"error": f"examples unavailable: {e}"}]


# ---------------------------------------------------------------- tools

def t_list_games(_a):
    rows = []
    for g in games.all_games():
        i = g.info()
        rows.append({k: i.get(k) for k in ("id", "title", "ready", "functions", "matched", "pct_fn", "pct_code",
                                           "pct_main", "remote") if k in i})
    return rows


def t_list_blocks(a):
    g = game(a["game"])
    rows = blocks.view(g)
    if a.get("free_only", True):
        rows = [b for b in rows if b["state"] in ("free", "expired")]
    return [{**{k: b.get(k) for k in ("id", "level", "state", "count", "left", "left_bytes")},
             "who": (b.get("claim") or {}).get("who")} for b in rows][:60]


def t_claim_block(a):
    g = game(a["game"])
    r = blocks.claim(g, a.get("block") or None, a.get("who") or f"{AGENT}-{config.settings()['who']}", "claude",
                     a.get("level"), a.get("note", ""))
    if r.get("ok"):
        bid = r["block"]
        r["functions"] = [f for f in blocks.functions_of(g, bid) if not f.get("done")] if bid else []
    return r


def t_block_functions(a):
    g = game(a["game"])
    return blocks.functions_of(g, a["block"])


def t_release_block(a):
    g = game(a["game"])
    return blocks.release(g, a["block"], None, bool(a.get("finished")))


def t_touch_block(a):
    return blocks.touch(game(a["game"]), a["block"], note=a.get("note"))


def t_get_function(a):
    g = game(a["game"])
    info = gameenv.workbench(g.path, "info", a["name"])
    if "error" not in info:
        info["look_alikes"] = similar(info.pop("lines", []), info["size"], g.id, a["name"], int(a.get("examples", 3)))
    return info


def t_compile_and_diff(a):
    g = game(a["game"])
    p = with_file(a["source"])
    try:
        args = ["judge", a["name"], str(p)] + (["--profile", a["profile"]] if a.get("profile") else [])
        return gameenv.workbench(g.path, *args, timeout=300)
    finally:
        p.unlink(missing_ok=True)


def t_submit_match(a):
    g = game(a["game"])
    p = with_file(a["source"])
    try:
        return gameenv.workbench(g.path, "submit", a["name"], str(p), "--who", a.get("who") or AGENT, timeout=1800)
    finally:
        p.unlink(missing_ok=True)


_COMMITS: dict[str, subprocess.Popen] = {}


def t_commit_matches(a):
    """Starts the full verify + commit in the background (minutes on a big game)."""
    g = game(a["game"])
    proc = _COMMITS.get(g.id)
    if proc and proc.poll() is None:
        return {"started": False, "note": "a commit is already running for this game: commit_status"}
    log = g.path / "build" / "workbench" / "commit.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.unlink(missing_ok=True)
    f = log.open("w", encoding="utf-8")
    _COMMITS[g.id] = subprocess.Popen([str(gameenv.PYTHON), str(config.game_tool(g.path, "workbench.py")), "commit"] +
                                      (["--push"] if a.get("push") else []), cwd=g.path, env=gameenv.env(), stdin=subprocess.DEVNULL,
                                      stdout=f, stderr=subprocess.STDOUT, text=True)
    return {"started": True, "note": "match.py verify runs on the whole game, then git commit: ask commit_status"}


def t_commit_status(a):
    g = game(a["game"])
    proc = _COMMITS.get(g.id)
    log = g.path / "build" / "workbench" / "commit.json"
    if proc and proc.poll() is None:
        return {"running": True}
    if not log.exists():
        return {"running": False, "result": None}
    lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("{")]
    return {"running": False, "result": json.loads(lines[-1]) if lines else log.read_text()[-2000:]}


def t_pending(a):
    return gameenv.workbench(game(a["game"]).path, "pending")


def t_read_data(a):
    return gameenv.workbench(game(a["game"]).path, "data", a["name"])


def t_check_data(a):
    g = game(a["game"])
    p = with_file(a["source"])
    try:
        return gameenv.workbench(g.path, "datacheck", str(p), timeout=300)
    finally:
        p.unlink(missing_ok=True)


def t_read_file(a):
    g = game(a["game"])
    f = (g.path / a["path"]).resolve()
    if not any(g.path / d in f.parents for d in ("src", "include")) or not f.is_file():
        return {"error": "only files under src/ and include/ can be read"}
    t = f.read_text(encoding="utf-8", errors="replace")
    return t if len(t) < 60000 else t[:60000] + "\n... (cut)"


def t_edit_header(a):
    g = game(a["game"])
    header = a.get("header") or "include/engine.h"
    h = g.path / header
    old = h.read_text(encoding="utf-8", errors="replace") if h.exists() else ""
    if a.get("content") is not None:
        new = a["content"]
    elif a.get("append"):
        new = old.rstrip("\n") + "\n\n" + a["append"].strip("\n") + "\n"
    elif a.get("replace") is not None and a.get("with") is not None:
        if a["replace"] not in old:
            return {"ok": False, "error": "the text to replace is not in the header"}
        new = old.replace(a["replace"], a["with"], 1)
    else:
        return {"ok": False, "error": "give content, append, or replace + with"}
    if "#endif" in old.splitlines()[-1:] and a.get("append"):  # keep an include guard at the end
        body = old.rstrip("\n").rsplit("\n", 1)
        new = body[0] + "\n\n" + a["append"].strip("\n") + "\n\n" + body[1] + "\n"
    p = with_file(new)
    try:
        return gameenv.workbench(g.path, "header", header, str(p), timeout=3600)
    finally:
        p.unlink(missing_ok=True)


def t_split_candidates(a):
    return gameenv.workbench(game(a["game"]).path, "splits")


def t_split_function(a):
    g = game(a["game"])
    args = ["split", a["name"], a["at"]] + (["--new-name", a["new_name"]] if a.get("new_name") else [])
    return gameenv.workbench(g.path, *args, timeout=1800)


def t_search_functions(a):
    from dsstudio import server
    r = server.function_list(a["game"], a.get("level"), a.get("query", ""), a.get("state", "todo"),
                             int(a.get("limit", 50)))
    return {"total": r["total"], "rows": [{k: x.get(k) for k in ("name", "addr", "size", "level", "block", "done", "mode",
                                                                 "module")} for x in r["rows"]]}


S = {"type": "string"}
GAME = {"game": {"type": "string", "description": "game id (list_games)"}}
TOOLS = {
    "list_games": (t_list_games, "The games of the studio with their progress.", {}, []),
    "list_blocks": (t_list_blocks, "Blocks of 50 functions of one game (free ones by default).",
                    {**GAME, "free_only": {"type": "boolean"}}, ["game"]),
    "claim_block": (t_claim_block, "Claim a block before working on it (the next free one, or `block`, or the next of "
                                   "`level` 0 easy .. 5 legendary). Returns its functions left to do.",
                    {**GAME, "block": S, "level": {"type": "integer"}, "note": S}, ["game"]),
    "block_functions": (t_block_functions, "Functions of a block and their state.", {**GAME, "block": S},
                        ["game", "block"]),
    "touch_block": (t_touch_block, "Still working on a block (claims expire after 48 h): optional note.",
                    {**GAME, "block": S, "note": S}, ["game", "block"]),
    "release_block": (t_release_block, "Give a block back (finished=true when all its functions are matched).",
                      {**GAME, "block": S, "finished": {"type": "boolean"}}, ["game", "block"]),
    "search_functions": (t_search_functions, "Find functions by name; state todo (default) or done.",
                         {**GAME, "query": S, "state": S, "level": {"type": "integer"}, "limit": {"type": "integer"}},
                         ["game"]),
    "get_function": (t_get_function, "Everything about one function: assembly, best draft so far, compiler profiles, "
                                     "calls with their prototypes, data it loads, callers, and matched look-alikes "
                                     "from all games (their asm and the exact C).",
                     {**GAME, "name": S, "examples": {"type": "integer"}}, ["game", "name"]),
    "compile_and_diff": (t_compile_and_diff, "Compile a whole C file for the function with the game's compilers and "
                                             "compare it with the original: match, or the instruction diff "
                                             "(TARGET | CANDIDATE) or the compiler errors.",
                         {**GAME, "name": S, "source": S, "profile": S}, ["game", "name", "source"]),
    "submit_match": (t_submit_match, "Put a matching file into the game (src/auto + delinks.txt) and rebuild the ROM "
                                     "(1-3 min): kept only if the ROM stays byte-identical. Not committed yet.",
                     {**GAME, "name": S, "source": S, "who": S}, ["game", "name", "source"]),
    "pending_matches": (t_pending, "Submitted matches waiting for commit_matches.", {**GAME}, ["game"]),
    "commit_matches": (t_commit_matches, "Full verify of the game once for all submitted matches (files it rejects "
                                         "are dropped), then a git commit (push=true to push). Runs in the "
                                         "background: commit_status.", {**GAME, "push": {"type": "boolean"}},
                       ["game"]),
    "commit_status": (t_commit_status, "Result of the last commit_matches.", {**GAME}, ["game"]),
    "read_data": (t_read_data, "A data symbol (name or 0xADDR): bytes decoded, string, pointers, who uses it, and a C "
                               "declaration of it.", {**GAME, "name": S}, ["game", "name"]),
    "check_data": (t_check_data, "Compile a C file and compare every data symbol it defines with the game (values, "
                                 "pointers by target, sizes, order).", {**GAME, "source": S}, ["game", "source"]),
    "read_file": (t_read_file, "Read a file of the game under src/ or include/.", {**GAME, "path": S},
                  ["game", "path"]),
    "edit_header": (t_edit_header, "Change a shared header (default include/engine.h): `append` text, `replace` + "
                                   "`with`, or the whole `content`. Every matched file is recompiled and the change "
                                   "is kept only if the ROM stays byte-identical.",
                    {**GAME, "header": S, "append": S, "replace": S, "with": S, "content": S}, ["game"]),
    "split_candidates": (t_split_candidates, "Functions called in their middle: dsd probably merged two functions.",
                         {**GAME}, ["game"]),
    "split_function": (t_split_function, "Cut a function in two at `at` (0xADDR) in symbols.txt; kept only if the ROM "
                                         "stays byte-identical.", {**GAME, "name": S, "at": S, "new_name": S},
                       ["game", "name", "at"]),
}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": req}}
            for n, (_f, d, props, req) in TOOLS.items()]


def handle(msg: dict):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return {"protocolVersion": want, "capabilities": {"tools": {}},
                "serverInfo": {"name": "ds-decomp-studio", "version": "1"}, "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in TOOLS:
            return {**text(f"unknown tool {name}"), "isError": True}
        try:
            res = TOOLS[name][0](args)
            err = isinstance(res, dict) and ("error" in res or res.get("ok") is False)
            return {**text(res), "isError": bool(err)}
        except KeyError as e:
            return {**text(f"missing or unknown: {e}"), "isError": True}
        except Exception as e:
            traceback.print_exc()
            return {**text(f"{type(e).__name__}: {e}"), "isError": True}
    if mid is None:
        return None  # notification
    raise LookupError(method)


_write_lock = threading.Lock()


def send(obj):
    with _write_lock:
        _OUT.write(json.dumps(obj) + "\n")
        _OUT.flush()


def serve():
    def work(msg):
        mid = msg.get("id")
        try:
            res = handle(msg)
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid, "result": res if res is not None else {}})
        except LookupError as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {e}"}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": repr(e)}})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        for m in msg if isinstance(msg, list) else [msg]:
            # long tools (submit, header) must not block quick ones: one thread per request
            threading.Thread(target=work, args=(m,), daemon=True).start()
    time.sleep(0.2)


if __name__ == "__main__":
    for stream in (sys.stdin, _OUT, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    serve()
