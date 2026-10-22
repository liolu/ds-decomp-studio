#!/usr/bin/env python3
"""Qwen agents (Ollama, local) work on the functions of studio blocks of any game.

    python workers/qwen_block.py --project <game dir> --blocks L1-01003,L1-01004 [--agents 4] [--minutes 5] [--max 0]

Generic version of rayman-rr/tools/qwen_auto.py, with several agents at once. Each agent takes the next unmatched
function that has a starting draft (build/auto/near/, auto_match cache, build/drafts/) and asks the model to
rewrite it until the project's probe_compiler.py says MATCH. Each request is made to give several tries, because
reading the prompt is the slow part (qwen3.5 serves one request at a time):
  - several versions per answer (--variants), all compiled in parallel; the best one is the base of the next request;
  - small functions (--group-size) go by batches of neighbours (--group) in one request;
  - big functions (--patch-size / --patch-lines) get SEARCH/REPLACE edits instead of the whole file (less to write);
  - the prompt starts with what never changes (rules, target assembly, context) so the server reuses its cache;
  - all versions of a function are compiled in one compiler call, in this process (no probe subprocess per try);
  - with a server that answers one request at a time (Ollama + qwen3.5), 2 agents take turns: one compiles while
    the other generates, and the time limit only counts generation;
  - --backend openai: llama.cpp server (workers/llm_server.py, started on demand) or vLLM, real parallel requests.
Time goes where it pays: a quick first pass on every function (--pass1-minutes), each one dropped after --plateau
rounds without progress; then the close ones (--pass2-diffs) get other compilers/flags (sweep_profiles), the
permuter in the background (--permute-at), and a long second pass (--minutes) with thinking for the closest
(--think-at). Each round also tries, without the model, rule fixes and crossovers of the best candidates. Failed
tries are kept between runs (build/qwen_auto/memory/), functions left 1-3 instructions away go to the "difficile"
queue (build/qwen_auto/hard.json, `--hard` with a bigger model). Functions without a draft get one from m2c.
Agents never touch the project: matches go to one
integrator, which adds them in batches (src/auto/ + delinks.txt, clang-format), runs `match.py verify`, and
commits (+ pushes) only if it passes; a failing batch is retried one function at a time.
Ollama answers N requests at once only if it was started with OLLAMA_NUM_PARALLEL >= N.
Create <project>/build/qwen_auto/STOP to stop: agents finish their current function, the integrator flushes.
"""
import argparse
import difflib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--project", required=True, type=Path)
ap.add_argument("--blocks", "--block", dest="blocks", default="", help="block ids, comma separated (not needed with --hard)")
ap.add_argument("--model", default="qwen9-ctx")
ap.add_argument("--minutes", type=float, default=5.0, help="time limit per function")
ap.add_argument("--agents", type=int, default=1, help="functions worked on at the same time")
ap.add_argument("--max", type=int, default=0, help="at most this many functions (0 = all)")
ap.add_argument("--batch", type=int, default=10, help="matches verified together")
ap.add_argument("--variants", type=int, default=4, help="versions asked in one answer (all compiled in parallel)")
ap.add_argument("--group", type=int, default=6, help="small functions sent in one request (1 = never batch)")
ap.add_argument("--group-size", type=int, default=64, help="functions up to this many bytes go by batches")
ap.add_argument("--group-variants", type=int, default=2, help="versions per function in a batch answer")
ap.add_argument("--patch-size", type=int, default=400, help="functions from this many bytes get edits, not whole files")
ap.add_argument("--patch-lines", type=int, default=60, help="... or whose C has this many lines")
ap.add_argument("--max-tokens", type=int, default=8192, help="cap of one answer")
ap.add_argument("--compile-jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2), help="compilers at once")
ap.add_argument("--pass1-minutes", type=float, default=1.5,
                help="first quick pass on every function; --minutes is the second pass, only for the close ones")
ap.add_argument("--pass2-diffs", type=int, default=3, help="second pass for functions this close after the first")
ap.add_argument("--plateau", type=int, default=4, help="stop a function after this many rounds without progress")
ap.add_argument("--permute-at", type=int, default=4, help="give a function this close to the permuter (0 = never)")
ap.add_argument("--permute-minutes", type=float, default=5.0, help="permuter time per function")
ap.add_argument("--think-at", type=int, default=2, help="second pass: thinking mode for functions this close (0 = no)")
ap.add_argument("--think-tokens", type=int, default=4096, help="extra tokens for the thinking")
ap.add_argument("--small-model", default="", help="model for the easy functions of the first pass (e.g. qwen-ctx)")
ap.add_argument("--hard", action="store_true",
                help="work on the queue of functions left a few instructions away (build/qwen_auto/hard.json) "
                     "instead of blocks, usually with a bigger --model")
ap.add_argument("--examples", type=int, default=3,
                help="matched functions with the closest code shown in the prompt (workers/examples.py index; 0 = none)")
ap.add_argument("--backend", choices=["ollama", "openai"], default="ollama",
                help="ollama, or openai = any OpenAI-compatible server (llama.cpp server, vLLM): real parallel requests")
ap.add_argument("--server", default="http://127.0.0.1:8080", help="URL of the OpenAI-compatible server")
ap.add_argument("--no-push", action="store_true")
ap.add_argument("--no-neighbours", action="store_true",
                help="after a match, do not retry its callers / callees with auto_match (clones are always made)")
args = ap.parse_args()
BLOCKS = [b.strip() for b in args.blocks.split(",") if b.strip()]
for _stream in (sys.stdout, sys.stderr):  # Windows consoles (cp932...) cannot print every message (Ollama errors)
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
_log_lock = threading.Lock()

ROOT = args.project.resolve()
os.environ["DSD_PROJECT"] = str(ROOT)  # gametools/project.py: this game, whatever the cwd
TOOLS = Path(__file__).resolve().parent.parent / "gametools"  # the matching tools (only build tools are in the game)
sys.path.insert(0, str(TOOLS))
import missdb  # noqa: E402  (every miss of this job is kept: gametools/missdb.py)
VERSION = next(p.name for p in sorted((ROOT / "config").iterdir()) if (p / "arm9" / "symbols.txt").exists())
WORK = ROOT / "build" / "qwen_auto"
WORK.mkdir(parents=True, exist_ok=True)
STOP = WORK / "STOP"
LOG = WORK / "log.txt"
FLAGS = "-O4,p"

RULES = """You fix C code for a matching decompilation (Nintendo DS, Metrowerks mwccarm, ARM, -O4,p).
You receive a C file and the ARM disassembly of the ORIGINAL function (TARGET) next to the one your code produces
(CANDIDATE); lines marked * differ. Rewrite the C so that the compiled code becomes identical.
Allowed changes: loop form (for/while/do-while, *p++ vs index), declaration order, temporaries, types
(s32/u32/s16/u16/s8/u8, signed/unsigned), casts, splitting or merging expressions, returning a value.
Keep the first lines (#define / #include) and the function name. Never make the function static
(the game exports it). ASCII only.
A short context may come first (which library or part of the game the function is in, what it calls, by real name
when known): use it to choose meaningful types and variable names, but the target assembly always decides.
Never give back a file unchanged: every version must change something.

How mwccarm decides the code (use it to choose what to change):
- Registers: r0-r3 arguments and scratch, r4-r11 saved (pushed together: stmdb sp!, {r4-r8, lr}). Which local gets
  which saved register follows the declaration order and first use: when only registers differ, swap two
  declarations or two independent statements, or make a value a separate local / recompute it. A compiler flag is
  almost never the cause.
- Stack frame (sub sp / add sp, every [sp, #n]): it holds every local and temporary, struct copies and the locals of
  inlined code included. Frame too small: the original had one more local or struct; too big: you have one too many.
  Locals sit in declaration order. When everything matches but the frame, the logic is right: fix the locals.
- Inlining (-O4): small functions defined earlier in the same file, and inline functions of headers, are inlined. If
  the target calls a function, call it; if the target has its code inlined, write it out.
- if/else keeps the source order: the fall-through block is the first branch written. A ternary can compile
  differently from if/else: try both. Loops with a known count become pointer walks and may be unrolled.
- No FPU: float math calls _fadd/_fsub/_fmul/_fdiv/_ffix/_fflt/_fls/_fgr..., double math _dadd/_dmul...; / and %
  call _s32_div_f/_u32_div_f. Constants and addresses come from the literal pool after the function, in the order
  of their first use in the C.
- Respellings worth trying, in this order: a condition as a value vs a comparison; the comparison the other way round
  (a < b / b > a); one return vs a return in each branch; the declaration order; a local vs the expression written
  inline; the grouping of a + b + c; bitfields vs masks.
Forbidden, refused without compiling (fake matches): asm in any form, new #define/#pragma/#include/#if lines, ##,
_Pragma, __declspec, __attribute__, machine code written as numbers. volatile only for hardware registers
(0x04xxxxxx); no empty statements or do {} while (0) that only exist to move the score.
"""
# One request gives several tries: the prompt is read once (qwen3.5 serves one request at a time), the candidates
# are compiled in parallel.
FMT_FULL = """Answer with {n} DIFFERENT complete versions of the C file (each one tries another idea), each in its own
```c code block, and nothing else."""
# Big functions: only the lines to change, far less text to generate than the whole file
FMT_PATCH = """Do not rewrite the whole file. Answer with {n} DIFFERENT versions (each one tries another idea). Each version
starts with a line `### Version <k>` followed by one or more edit blocks:
<<<<<<< SEARCH
lines copied exactly from the file
=======
the new lines
>>>>>>> REPLACE
Example of one version:
### Version 1
<<<<<<< SEARCH
    s32 i = 0;
    while (i < n) {
=======
    s32 i;
    for (i = 0; i < n; i++) {
>>>>>>> REPLACE
Nothing else: no full file, no explanation."""
# Small functions: several of them in one request
FMT_GROUP = """You receive several files, one per function, each under a line `### <function name>`. For EACH function,
answer the line `### <function name>` then {n} DIFFERENT complete versions of its file, each in its own ```c code
block. Nothing else."""


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def log(msg):
    with _log_lock:
        print(msg, flush=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def probe(path, name, addr, profile, show=True):
    cmd = [sys.executable, "tools/probe_compiler.py", str(path), name, str(addr), "--only", profile, f"--flags={FLAGS}"]
    if show:
        cmd.append("--show")
    try:
        out = run(cmd, timeout=180).stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "(probe timeout)"
    last = out.splitlines()[-1] if out else ""
    return last.rstrip().endswith("MATCH"), out


def score(out):
    last = out.strip().splitlines()[-1] if out.strip() else ""
    if last.rstrip().endswith("MATCH"):
        return 0
    m = re.search(r"(\d+)/\d+ diff", last)
    if not m:
        return 10000
    return int(m.group(1)) + (1000 if "(size" in last else 0)


def starting_draft(name):
    for p in (ROOT / "build" / "auto" / "near" / f"{name}.c", ROOT / "build" / "drafts" / f"{name}.c"):
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            if "m2c failed" not in text[:300]:
                return text
    cache = ROOT / "build" / "auto" / "cache.jsonl"
    if cache.exists():
        best = None
        for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)["r"]
            except Exception:
                continue
            if r[0] == name and len(r) > 4 and r[4]:
                best = r[4]
        if best:
            return best
    # no m2c draft: Ghidra's reading (tools/ghidra_draft.py), a start that at least has the right structure
    p = ROOT / "build" / "ghidra" / f"{name}.c"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None


def ghidra_reading(name: str) -> str:
    """Ghidra's decompilation of the function, when tools/ghidra_draft.py made one (without its header)."""
    p = ROOT / "build" / "ghidra" / f"{name}.c"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    return text.split('#include "m2c.h"', 1)[-1].strip()[:4000]


CODE_BLOCK = re.compile(r"```[a-zA-Z]*[ \t]*\n.*?```", re.S)


OLLAMA = "http://127.0.0.1:11434"


def ask(messages, temp, deadline, blocks=1, num_predict=2048, model=None, think=False) -> tuple[str, dict]:
    """The model's answer, read as it is written and cut as soon as `blocks` ```c blocks are closed: some models go on
    writing after the code (explanations, another version...) and would use the whole time of the function.
    blocks=0: read until the model stops (patch answers have no fixed number of blocks).
    Backends: Ollama (/api/chat) or any OpenAI-compatible server (llama.cpp server, vLLM: /v1/chat/completions).
    Also returns timings: `ttft` (seconds to the first token: reading the prompt, short when its start was cached),
    `gen` (whole answer), and the server's own counts when it sends them (prompt tokens, cached tokens).
    think=True: the model reasons first (its reasoning is not part of the answer), for the last differences."""
    model = model or args.model
    if args.backend == "openai":
        body = {"model": model, "messages": messages, "stream": True, "temperature": temp,
                "max_tokens": num_predict, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5,
                "cache_prompt": True,  # llama.cpp: keep the KV cache of the prompt's start for the next request
                "chat_template_kwargs": {"enable_thinking": bool(think)}}
        url = args.server.rstrip("/") + "/v1/chat/completions"
    else:
        body = {"model": model, "messages": messages, "stream": True,
                "options": {"temperature": temp, "num_predict": num_predict}, "think": bool(think)}
        url = OLLAMA + "/api/chat"
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    text, t0, info = [], time.time(), {}
    with urllib.request.urlopen(req, timeout=max(30, deadline - time.time())) as r:
        for line in r:  # Ollama: one JSON object per line; OpenAI: server-sent events "data: {...}"
            line = line.strip()
            if not line:
                continue
            if args.backend == "openai":
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                part = json.loads(data)
                if part.get("timings"):  # llama.cpp
                    tm = part["timings"]
                    info.update(prompt=tm.get("prompt_n"), cached=tm.get("cache_n"), prompt_s=(tm.get("prompt_ms") or 0) / 1000)
                choice = (part.get("choices") or [{}])[0]
                piece, done = (choice.get("delta") or {}).get("content") or "", choice.get("finish_reason") is not None
            else:
                part = json.loads(line)
                piece, done = part.get("message", {}).get("content", ""), part.get("done")
                if done and part.get("prompt_eval_count") is not None:
                    info.update(prompt=part["prompt_eval_count"], prompt_s=part.get("prompt_eval_duration", 0) / 1e9)
            if piece and "ttft" not in info:
                info["ttft"] = time.time() - t0
            text.append(piece)
            if done or time.time() > deadline:
                break
            if blocks and "```" in piece and len(CODE_BLOCK.findall("".join(text))) >= blocks:
                break  # closing the connection stops the generation (Ollama, llama.cpp)
    info["gen"] = time.time() - t0
    return "".join(text), info


NO_PARALLEL = {"qwen35"}  # architectures Ollama runs one request at a time ("does not support parallel requests")


def model_runs_in_parallel(model: str) -> bool:
    if args.backend == "openai":
        return True  # llama.cpp server --parallel N / vLLM: real parallel slots (continuous batching)
    try:
        req = urllib.request.Request(OLLAMA + "/api/show", json.dumps({"model": model}).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            arch = json.loads(r.read()).get("model_info", {}).get("general.architecture", "")
        return arch not in NO_PARALLEL
    except Exception:
        return True


def unstatic(code, name):
    """The original symbol is global: `static` would compile to the same bytes but break the link (local symbol)."""
    return re.sub(rf"(?<!\w)static\s+(?=[^;{{}}]*(?<!\w){re.escape(name)}\s*\()", "", code)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompt_tools as pt  # noqa: E402

_PROTOS = None
_EXAMPLES = None
_shared_lock = threading.Lock()


def protos_text() -> str:
    """include/m2c_protos.h + engine.h: real prototypes of matched functions, guessed ones (M2C_UNK) for the rest."""
    global _PROTOS
    with _shared_lock:
        if _PROTOS is None:
            _PROTOS = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                                for p in (ROOT / "include" / "m2c_protos.h", ROOT / "include" / "engine.h") if p.exists())
    return _PROTOS


def similar_examples(fn, n: int) -> str:
    """The n matched functions (all our games, workers/examples.py index) whose instructions are closest."""
    global _EXAMPLES
    if n <= 0:
        return ""
    with _shared_lock:
        if _EXAMPLES is None:
            try:
                import examples
                _EXAMPLES = examples.Examples() if examples.DB.exists() else False
                if not _EXAMPLES:
                    log("(pas d'exemples : lancer `python workers/examples.py build`)")
            except Exception as e:
                log(f"(exemples indisponibles : {e})")
                _EXAMPLES = False
    if not _EXAMPLES:
        return ""
    found = _EXAMPLES.similar(pt.mnemonic_list(fn.target_lines()), fn.size, ROOT.name, fn.name, n)
    out = []
    for k, (s, (game, name, size, _mn, asm, c)) in enumerate(found, 1):
        same = " -- SAME instructions as the target: only names/constants may differ" if s >= 0.999 else ""
        out.append(f"Example {k}: {name} from {game} ({size} bytes, similarity {s:.2f}{same})\n```\n{asm}\n```\n"
                   f"```c\n{c.strip()}\n```")
    return "\n\n".join(out)


CODEMAP = None
_codemap_lock = threading.Lock()


def code_context(name: str) -> str:
    """Which part of the game the function is in (NitroSDK module, C library, game engine...) and the real names of
    what it calls (tools/codemap.py of the project). Empty if the project has no codemap.py yet."""
    with _codemap_lock:
        if CODEMAP is None:
            _load_codemap()
    if not CODEMAP:
        return ""
    try:
        return CODEMAP.context(name)
    except Exception:
        return ""


def _load_codemap():
    global CODEMAP
    if CODEMAP is None:
        try:
            import codemap
            engine = ""
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from dsstudio import games
                studio = games.STUDIOS.get(ROOT.name)
                engine = f"engine of {studio} (the developer of {games.TITLES.get(ROOT.name, ROOT.name)})" if studio else ""
            except Exception:
                pass
            CODEMAP = codemap.CodeMap(engine=engine)
            CODEMAP.callers("")  # reads the disassembly now, under the lock (agents are threads)
        except Exception as e:
            log(f"(pas de contexte de code : {e})")
            CODEMAP = False


class Fn:
    """One function being worked on: its best C so far and what the compiler made of it."""

    def __init__(self, name, size, addr, src):
        self.name, self.size, self.addr = name, size, addr
        self.best, self.out, self.score, self.profile = src, "", (10**6, 10**6), None
        self.draft = src  # the starting file: what fake_match compares candidates with
        self.lines = []  # disassembly of what the best file compiles to
        self.pop: list[tuple[tuple[int, int], str]] = []  # the best different candidates (genetic crossover)
        self.stale = 0  # rounds without progress (plateau)
        self.tried: set[str] = set()  # hashes of every file compiled for it (this run and earlier ones: memory)
        self.permuting = False
        self.sessions, self.diff, self.easy, self.no_think = 0, 0.0, False, False
        self.notes, self.context, self.source = [], "", None  # source: the matching C, once found
        self._target, self._target_lines, self._asm, self._fixed = None, None, None, None

    @property
    def patch_mode(self) -> bool:
        """Big function: ask for edits instead of the whole file."""
        return self.size >= args.patch_size or self.best.count("\n") >= args.patch_lines

    @property
    def target(self) -> bytes:
        if self._target is None:
            import probe_compiler as pc
            self._target = pc.target_bytes(self.addr, self.size)
        return self._target

    def target_lines(self) -> list[str]:
        if self._target_lines is None:
            import probe_compiler as pc
            self._target_lines = pc.disasm(self.target, self.addr)
        return self._target_lines

    def fixed(self, examples: int | None = None) -> str:
        """The part of the prompt that never changes for this function (first, so the server reuses its cache):
        context, exact prototypes of what it calls, matched functions with the closest code, target assembly."""
        if self._fixed is not None:
            return self._fixed
        if self._asm is None:
            import auto_match as am
            self._asm = am.function_asm(self.name) or "\n".join(self.target_lines())
        parts = [f"Context (where this code comes from):\n{self.context}"] if self.context else []
        protos = pt.prototypes(self._asm, protos_text(), self.name)
        if protos:
            parts.append("Prototypes of the functions it calls (use them as they are: the return type and the argument "
                         "types change the code):\n" + "\n".join(protos))
        ex = similar_examples(self, args.examples if examples is None else examples)
        if ex:
            parts.append("Matched functions whose code is close (their assembly, then the C that compiles to it "
                         "EXACTLY with this compiler): reuse their style, types and loop forms.\n" + ex)
        gh = ghidra_reading(self.name)
        if gh and gh.strip() != (self.best or "").strip():
            parts.append("Another decompiler (Ghidra) reads the function like this (its structure and the names of what "
                         "it points at help; its types and its arguments are often wrong, the target assembly "
                         f"decides):\n```c\n{gh}\n```")
        parts.append(f"Target assembly of {self.name} (the original function):\n```\n{self._asm.strip()}\n```")
        self._fixed = "\n\n".join(parts)
        return self._fixed

    def varying(self, room: int) -> str:
        """What changes at each try (last): the best file so far, the part of its assembly that differs, hints read
        from the difference, the failed tries."""
        extra = ("\n\nAlready tried from this file, all worse or equal (do something different):\n" +
                 "\n".join(self.notes[-6:])) if self.notes else ""
        last = self.out.strip().splitlines()[-1] if self.out.strip() else ""
        if self.lines:
            diff = pt.compact_diff(self.target_lines(), self.lines)[:room]
            hint = pt.hints(self.target_lines(), self.lines)
            result = (f"{last} ; edit distance {self.score[1]} (instructions to add/remove/change: lower is closer)\n"
                      f"Where it differs (TARGET | CANDIDATE, * = differs, ... = identical lines):\n{diff}")
            if hint:
                result += "\nHints:\n" + "\n".join(f"- {t}" for _k, t in hint[:4])
        else:  # compile error, or the function is not in the object: the compiler's message
            result = self.out[-room:]
        return f"Current best file for {self.name}:\n```c\n{self.best}```\n\nCompiler result of this file: {result}{extra}"

    def strategy_keys(self) -> list[tuple[str, str]]:
        return pt.hints(self.target_lines(), self.lines) if self.lines else []


COMPILE_POOL = ThreadPoolExecutor(max_workers=max(1, args.compile_jobs))
GEN = threading.Semaphore(1)  # turns on the model server (main() sets the number of requests it serves at once)


def compile_versions(fn: Fn, codes: list[str], profile: str) -> list[tuple[bool, str, list[str]]]:
    """Compiles every version of one function in ONE compiler call (the compiler takes about a second to start,
    almost nothing per file), in this process (no probe_compiler.py subprocess per try). Same output as
    `probe_compiler.py --show`: side-by-side disassembly, then `<version> | -O4,p: N/M diff`."""
    import auto_match as am
    import probe_compiler as pc
    version, _, extra = profile.partition(" ")
    mwcc = am.MWCC_ROOT / version / "mwccarm.exe"
    opt = FLAGS
    if re.search(r"(^|\s)-O\d", extra):  # a profile with its own optimization level (found by sweep_profiles)
        opt, extra = "", extra
    out: dict[int, tuple[bool, str, list[str]]] = {}
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        t = Path(tmp)
        (t / "objs").mkdir()
        for i, code in enumerate(codes):
            (t / f"v{i}.c").write_text(code, encoding="utf-8", newline="\n")
        pending = list(range(len(codes)))
        while pending:
            files = " ".join(f"v{i}.c" for i in pending)
            cmd = f'"{mwcc}" {opt} {pc.BASE_FLAGS} {extra} -i "{ROOT / "include"}" -c {files} -o objs'
            r = am.run_limited(cmd, cwd=t, shell=True, timeout=30 + len(pending))
            if r.stderr == "timeout":
                for i in pending:
                    out[i] = (False, f"{version:14} | {FLAGS}: compile error (timeout)", [])
                break
            missing = [i for i in pending if not (t / "objs" / f"v{i}.o").exists()]
            for i in pending:
                if i in missing:
                    continue
                cand = pc.compiled_function(t / "objs" / f"v{i}.o", fn.name)
                if cand is None:
                    out[i] = (False, f"{version:14} | {FLAGS}: function not found", [])
                    continue
                bad, n = pc.compare(fn.target, cand)
                tag = "MATCH" if bad == 0 else f"{bad}/{n} diff" + ("" if len(cand) == fn.size else f" (size 0x{len(cand):x})")
                out[i] = (bad == 0, f"{version:14} | {FLAGS}: {tag}", [] if bad == 0 else pc.disasm(cand, fn.addr))
                if bad:  # every miss goes to the miss database (replayed on all unmatched functions after the job)
                    missdb.record(fn.name, codes[i], profile, "near" if len(cand) == fn.size else "size", diffs=bad,
                                  total=n, source="qwen", obj=t / "objs" / f"v{i}.o", addr=fn.addr, size=fn.size)
            if not missing:
                break
            # the compiler stops at the first file with an error: that one failed, the next ones were not compiled
            err = "\n".join((r.stdout + r.stderr).strip().splitlines()[:12])
            out[missing[0]] = (False, f"{err}\n{version:14} | {FLAGS}: compile error", [])
            missdb.record(fn.name, codes[missing[0]], profile, "compile", error=err, source="qwen", addr=fn.addr,
                          size=fn.size)
            pending = missing[1:]
    return [out.get(i, (False, f"{version:14} | {FLAGS}: compile error", [])) for i in range(len(codes))]


PROFILE_FLAGS = ["-O4,s", "-O3", "-O2", "-O4,p -inline auto", "-O4,p -inline on,noauto"]


def sweep_profiles(fn: Fn) -> tuple[str, str, list[str], tuple[int, int]] | None:
    """A function stuck at a few differences may be built with another compiler or other flags, not need other C:
    the best file is compiled with every mwccarm version of tools/mwccarm and a few flag sets. Returns
    (profile, output, lines, rank) of the best result if it is better than the current one, else None."""
    import auto_match as am
    versions = sorted(p.parent.relative_to(am.MWCC_ROOT).as_posix() for p in am.MWCC_ROOT.glob("[12]*/*/mwccarm.exe"))
    profiles = [v for v in versions if v != fn.profile.split(" ")[0]]
    profiles += [f"{v} {fl}" for v in versions for fl in PROFILE_FLAGS]
    if "1.2/sp2p3" in versions:
        profiles.append("1.2/sp2p3 -proc arm7tdmi")
    res = probe_many([(fn, fn.best, p) for p in profiles])
    best = None
    for p, (ok, out, lines) in zip(profiles, res):
        r = rank(fn, out, lines) if not ok else (0, 0)
        if r < fn.score and (best is None or r < best[3]):
            best = (p, out, lines, r)
    return best


_ZONES = None


def zone_profile(addr: int) -> str | None:
    """The compiler of the matched files around this address (compilers.txt): a library is built with one compiler
    and linked in one piece, so its neighbours tell which one to try first."""
    global _ZONES
    import auto_match as am
    with _shared_lock:
        if _ZONES is None:
            prof = {}
            if am.COMPILERS_TXT.exists():
                for line in am.COMPILERS_TXT.read_text(encoding="utf-8").splitlines():
                    if line.strip() and not line.startswith("#"):
                        p, _, v = line.partition(" ")
                        prof[p] = v.strip()
            text = am.DELINKS.read_text(encoding="utf-8").split("\n\n", 1)[-1]
            _ZONES = sorted((int(a, 16), prof.get(f, "")) for f, a in
                            re.findall(r"^(src/\S+):\n\s+complete\n\s+\.text\s+start:0x([0-9a-f]+)", text, re.M))
    import bisect
    i = bisect.bisect_left(_ZONES, (addr, ""))
    near = [_ZONES[j][1] for j in (i - 1, i) if 0 <= j < len(_ZONES)]
    if near and all(n and n == near[0] for n in near):
        return near[0]
    return None


FLOAT_CALL = re.compile(r"\bbl\s+_{1,2}(?:f|d)(?:add|sub|mul|div|cmp|eq|ne|lt|le|ge|gt|fix|flt|ltod|dtof|2d|2f|sqrt)\w*")


def difficulty(fn: Fn) -> float:
    """Expected effort, lower first: size, starting differences, switch tables, float runtime calls, calls."""
    asm = fn._asm or ""
    lines = fn.target_lines()
    d = len(lines) + 3 * min(fn.score[0], 300)
    if re.search(r"(addls|ldrls)\s+pc", "\n".join(lines)):
        d += 40  # switch: jump tables are hard to reproduce
    d += 25 * len(FLOAT_CALL.findall(asm))
    d += 3 * len(re.findall(r"^\s+blx?\s", asm, re.M))
    return d


TYPE_FLIP = {"s8": "u8", "u8": "s8", "s16": "u16", "u16": "s16", "s32": "u32", "u32": "s32"}
DECL = re.compile(r"^(\s+)(s8|u8|s16|u16|s32|u32)(\s+\**\s*\w+)", re.M)


def rule_variants(fn: Fn) -> list[str]:
    """Fixes tried without the model on the best file: the m2c corrections of auto_match (returned value, loops,
    struct copies...), then the transformations the difference points at: signedness of each local variable
    (types hint), swapping two neighbouring declarations (only registers differ)."""
    import auto_match as am
    out = []
    try:
        out += am.variants(fn.best, fn.name)
    except Exception:
        pass
    keys = {k for k, _t in fn.strategy_keys()}
    decls = list(DECL.finditer(fn.best))
    if "types" in keys or not keys:
        for m in decls[:8]:
            out.append(fn.best[:m.start(2)] + TYPE_FLIP[m.group(2)] + fn.best[m.end(2):])
    if "order" in keys:
        lines = fn.best.split("\n")
        idx = [fn.best[:m.start()].count("\n") for m in decls]
        for a, b in zip(idx, idx[1:]):
            if b == a + 1:
                swapped = list(lines)
                swapped[a], swapped[b] = swapped[b], swapped[a]
                out.append("\n".join(swapped))
    return out[:24]


def crossover(fn: Fn, limit: int = 8) -> list[str]:
    """Children of the best candidates: the best file with one differing part taken from another good candidate
    (each part of a diff hunk by hunk). Keeps ideas that were right in a candidate that was worse overall."""
    if len(fn.pop) < 2:
        return []
    base = fn.pop[0][1].split("\n")
    out = []
    for _r, other in fn.pop[1:4]:
        o = other.split("\n")
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, o, autojunk=False).get_opcodes():
            if op != "equal":
                out.append("\n".join(base[:i1] + o[j1:j2] + base[i2:]))
                if len(out) >= limit:
                    return out
    return out


def remember(fn: Fn, code: str, r: tuple[int, int]) -> None:
    """Keeps the 6 best different candidates (population for crossover)."""
    if any(c == code for _r, c in fn.pop):
        return
    fn.pop.append((r, code))
    fn.pop.sort(key=lambda x: x[0])
    del fn.pop[6:]


def code_hash(code: str) -> str:
    import hashlib
    return hashlib.sha1(re.sub(r"\s+", " ", code).strip().encode()).hexdigest()[:16]


MEMORY = WORK / "memory"


def load_memory(fn: Fn) -> None:
    """What earlier runs learned about this function: their best file (when better than the draft), their failed
    tries (told to the model, and never compiled again)."""
    p = MEMORY / f"{fn.name}.json"
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return
    fn.tried |= set(m.get("tried", []))
    fn.notes = m.get("notes", [])[-6:]
    fn.sessions = m.get("sessions", 0)
    if m.get("best") and tuple(m.get("score", (10**6, 10**6))) < fn.score and not pt.fake_match(m["best"], fn.draft):
        fn.best, fn.profile = m["best"], m.get("profile") or fn.profile


def save_memory(fn: Fn) -> None:
    MEMORY.mkdir(parents=True, exist_ok=True)
    p = MEMORY / f"{fn.name}.json"
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        old = {}
    keep_old = old.get("best") and tuple(old.get("score", (10**6, 10**6))) <= fn.score
    data = {"best": old["best"] if keep_old else fn.best, "score": old["score"] if keep_old else list(fn.score),
            "profile": old.get("profile") if keep_old else fn.profile, "notes": (old.get("notes", []) + fn.notes)[-12:],
            "tried": sorted(fn.tried)[-2000:], "sessions": old.get("sessions", 0) + 1, "t": time.time()}
    p.write_text(json.dumps(data), encoding="utf-8")


PERMUTE_POOL = ThreadPoolExecutor(max_workers=1)  # the permuter uses many cores: one function at a time


def permute(fn: Fn, on_match) -> None:
    """The permuter finishes what the model started: it is better at register allocation and statement order.
    Runs on the CPU in the background while the model works on other functions. Only for the default compiler
    (tools/permute.py builds with it)."""
    if fn.permuting or args.permute_minutes <= 0 or fn.profile.split(" ")[0] != "2.0/sp1p5" or \
            not (TOOLS / "permute.py").exists():
        return
    fn.permuting = True
    src = WORK / "permute" / f"{fn.name}.c"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(fn.best, encoding="utf-8", newline="\n")
    best_score = fn.score[0]

    def job():
        out_dir = ROOT / "build" / "permuter" / fn.name
        shutil.rmtree(out_dir, ignore_errors=True)
        log(f"{fn.name}: permuter {args.permute_minutes:g} min sur le meilleur fichier ({best_score} diffs)")
        run([sys.executable, str(TOOLS / "permute.py"), fn.name, "--source", str(src), "--minutes", str(args.permute_minutes),
             "-j", str(max(1, (os.cpu_count() or 4) // 2))])
        found = sorted(out_dir.glob("output-0-*"))
        if found:
            log(f"{fn.name}: MATCH par le permuter -> file d'integration")
            on_match(fn, (found[0] / "source.c").read_text(encoding="utf-8"))
        else:
            log(f"{fn.name}: le permuter n'a pas fini ({best_score} diffs)")
    PERMUTE_POOL.submit(job)


def make_drafts(names: list[str]) -> None:
    """Functions without a starting point get an m2c draft (tools/draft.py -> build/drafts/), instead of being
    skipped."""
    if not names or not (TOOLS / "draft.py").exists():
        return
    for k in range(0, len(names), 40):
        run([sys.executable, str(TOOLS / "draft.py"), *names[k:k + 40]])


def rank(fn: Fn, out: str, lines: list[str]) -> tuple[int, int]:
    """(differing instructions, edit distance): the second part sees progress the first one misses."""
    return score(out), (pt.edit_distance(fn.target_lines(), lines) if lines else 10**6)


def probe_many(cands: list[tuple["Fn", str, str]]) -> list[tuple[bool, str, list[str]]]:
    """Compiles [(fn, code, profile)]: one compiler call per (function, compiler), those calls in parallel.
    Returns [(match, probe output)] in the same order."""
    groups: dict[tuple[int, str], list[int]] = {}
    for k, (fn, _code, profile) in enumerate(cands):
        groups.setdefault((id(fn), profile), []).append(k)
    def one(idx):
        fn, _c, profile = cands[idx[0]]
        return idx, compile_versions(fn, [cands[k][1] for k in idx], profile)
    res: list = [None] * len(cands)
    for idx, outs in COMPILE_POOL.map(one, list(groups.values())):
        for k, o in zip(idx, outs):
            res[k] = o
    return res


def clean(code: str, name: str) -> str:
    return unstatic("".join(c for c in code if ord(c) < 128), name)


def code_blocks(text: str) -> list[str]:
    """```c blocks, plus a last block left open (answer cut by the token cap) when its braces are balanced."""
    out = re.findall(r"```[a-zA-Z]*[ \t]*\n(.*?)```", text, re.S)
    if text.count("```") % 2:
        tail = text[text.rindex("```"):].split("\n", 1)
        if len(tail) == 2 and tail[1].count("{") and tail[1].count("{") == tail[1].count("}"):
            out.append(tail[1])
    return out


EDIT = re.compile(r"<{5,}\s*SEARCH[ \t]*\n(.*?)\n?={5,}[ \t]*\n(.*?)\n?>{5,}\s*REPLACE", re.S)


def apply_edits(text: str, edits: list[tuple[str, str]]) -> str | None:
    """Applies SEARCH/REPLACE edits; a SEARCH that is not found exactly is looked for line by line ignoring
    indentation. None if one edit cannot be placed."""
    for search, replace in edits:
        if not search.strip():
            return None
        if search in text:
            text = text.replace(search, replace, 1)
            continue
        lines, want = text.split("\n"), [l.strip() for l in search.strip("\n").split("\n")]
        for i in range(len(lines) - len(want) + 1):
            if [l.strip() for l in lines[i:i + len(want)]] == want:
                lines[i:i + len(want)] = replace.split("\n")
                break
        else:
            return None
        text = "\n".join(lines)
    return text


def parse_patches(reply: str, fn: Fn) -> list[str]:
    """Each `### Version k` of a patch answer applied to the best file."""
    parts = re.split(r"^#+\s*Version\b.*$", reply, flags=re.M)
    out = []
    for part in parts:
        edits = EDIT.findall(part.replace("```c", "").replace("```", ""))
        if edits:
            new = apply_edits(fn.best, edits)
            if new is not None:
                out.append(new)
    return out


def parse_group(reply: str, fns: list[Fn]) -> dict[str, list[str]]:
    """{function: [versions]} from an answer for several functions: by `### name` headers, and for blocks outside
    them by the function each block defines."""
    by_name = {f.name: f for f in fns}
    out = {f.name: [] for f in fns}
    pieces = re.split(r"^#+\s*`?(\w+)`?\s*$", reply, flags=re.M)
    loose = pieces[0]
    for k in range(1, len(pieces) - 1, 2):
        if pieces[k] in by_name:
            out[pieces[k]] += code_blocks(pieces[k + 1])
        else:
            loose += pieces[k + 1]
    for block in code_blocks(loose):
        owner = next((n for n in by_name if re.search(rf"\b{re.escape(n)}\s*\([^;{{}}]*\)\s*\{{", block)), None)
        if owner:
            out[owner].append(block)
    return out


def plan(fns: list[Fn], rnd: int, n: int) -> str:
    """One angle per version (the hints' angles first, then a rotation that moves at each round): the versions of
    one answer try different things instead of the same idea at a higher temperature."""
    hints = [h for f in fns for h in f.strategy_keys()]
    steps = pt.pick_strategies(hints, rnd, n)
    who = "every function" if len(fns) > 1 else "the file"
    return (f"\n\nWhat each version must do (version 1 = first line, ...; apply it to {who}):\n"
            + "\n".join(f"{k}. {s}" for k, s in enumerate(steps, 1)))


def request(fns: list[Fn], temp: float, deadline: float, rnd: int = 0, model: str | None = None,
            think: bool = False) -> tuple[dict[str, list[str]], dict]:
    """One request to the model for these functions: ({function: [candidate C files]}, timings).
    The prompt starts with what never changes (rules, examples, prototypes, target assembly, context) and ends with
    what changes at each try (best file, the differing part, hints, failed tries, the angle of each version): the
    server keeps the start in its cache and only reads the end."""
    v = max(1, args.variants)
    if len(fns) > 1:
        n = max(1, args.group_variants)
        system = RULES + FMT_GROUP.format(n=n)
        user = ("\n\n".join(f"### {f.name}\n{f.fixed(min(args.examples, 1))}" for f in fns)
                + "\n\n----- current state -----\n\n" + "\n\n".join(f"### {f.name}\n{f.varying(2500)}" for f in fns)
                + plan(fns, rnd, n))
        blocks, predict = n * len(fns), sum(n * (len(f.best) // 3 + 150) for f in fns)
    elif fns[0].patch_mode:
        # room for the edits, or for one whole file when the model writes that instead
        f = fns[0]
        system, user, blocks = RULES + FMT_PATCH.format(n=v), f"{f.fixed()}\n\n{f.varying(6000)}{plan(fns, rnd, v)}", 0
        predict = max(700 * v, len(f.best) // 3 + 400)
    else:
        f = fns[0]
        system, user = RULES + FMT_FULL.format(n=v), f"{f.fixed()}\n\n{f.varying(6000)}{plan(fns, rnd, v)}"
        blocks, predict = v, v * (len(f.best) // 3 + 150)
    predict = max(1024, min(args.max_tokens, predict)) + (args.think_tokens if think else 0)
    reply, info = ask([{"role": "system", "content": system}, {"role": "user", "content": user}], temp, deadline,
                      blocks=blocks, num_predict=predict, model=model, think=think)
    try:  # the last raw answer, to see what the model writes when versions go missing
        (WORK / "last_reply.txt").write_text(reply, encoding="utf-8")
    except OSError:
        pass
    if len(fns) > 1:
        found = parse_group(reply, fns)
    elif fns[0].patch_mode:
        found = {fns[0].name: parse_patches(reply, fns[0])}
        if not found[fns[0].name]:  # the model wrote whole files anyway
            found[fns[0].name] = code_blocks(reply)
    else:
        found = {fns[0].name: code_blocks(reply)}
    out = {f.name: list(dict.fromkeys(c for c in (clean(x, f.name) for x in found.get(f.name, []))
                                      if c.strip() and c.strip() != f.best.strip()))[:max(v, args.group_variants)]
           for f in fns}
    raw = sum(len(x) for x in found.values())
    if raw and not any(out.values()):
        log(f"  ({raw} version(s) recue(s), toutes identiques au fichier donne)")
    elif not raw:
        log(f"  (reponse de {len(reply)} caracteres sans bloc de code reconnu : build/qwen_auto/last_reply.txt)")
    return out, info


def solve(unit: list[Fn], minutes: float, plateau: int, final: bool = False) -> None:
    """Works on one function or a batch of small ones until each matches, stops progressing (plateau: `plateau`
    rounds in a row without a better score) or its time is out (`minutes` per function).
    Each round: one request for several versions (each with its own angle), then, without the model, the rule
    fixes and crossovers of the best candidates; everything is compiled, the best file is the next base. Files
    already compiled for this function (this run or earlier ones: memory) are never compiled again.
    The time limit counts only the model's work for this unit: with a server that answers one request at a time,
    agents take turns on it (GEN); waiting for the turn costs nothing. A wall clock limit (3x) still applies.
    final=True (second pass, functions a few instructions away): thinking mode for the closest ones."""
    budget = minutes * 60 * len(unit)
    used, wall_end = 0.0, time.time() + 3 * budget + 120
    pending, empty, rnd = list(unit), 0, 0
    while pending and used < budget and time.time() < wall_end and not STOP.exists():
        rnd += 1
        # the angle of each version brings the variety now; the temperature only rises a little when stuck
        temp = min(0.9, 0.6 + 0.03 * max(len(f.notes) for f in pending))
        think = final and args.think_at > 0 and all(f.score[0] <= args.think_at and not f.no_think for f in pending)
        model = args.model
        if args.small_model and not final and all(f.easy for f in pending):
            model = args.small_model
        try:
            with GEN:
                t0 = time.time()
                try:
                    cands, info = request(pending, temp, t0 + budget - used, rnd, model=model, think=think)
                finally:
                    used += time.time() - t0
        except Exception as e:
            if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError) \
                    or "timed out" in str(e) or "10060" in str(e):  # 10060: Windows timeout, message translated
                log(f"  {', '.join(f.name for f in pending)}: limite de temps atteinte pendant une reponse du modele")
            else:
                log(f"  le serveur du modele ne repond pas ({e})")
            return
        model_gave = any(cands.get(f.name) for f in pending)
        # without the model: rule fixes and crossovers of the best candidates
        for f in pending:
            cands.setdefault(f.name, [])
            cands[f.name] += rule_variants(f) + crossover(f)
        todo = []
        for f in pending:
            refused = {}
            for c in dict.fromkeys(cands.get(f.name, [])):
                h = code_hash(c)
                if h not in f.tried:
                    f.tried.add(h)
                    why = pt.fake_match(c, f.draft)
                    if why:
                        refused[why] = refused.get(why, 0) + 1
                    else:
                        todo.append((f, c, f.profile))
            for why, k in refused.items():
                log(f"  {f.name}: {k} version(s) refusee(s) sans compiler (faux match : {why})")
                note = f"- a version used {why}: REFUSED without compiling (fake match). Write plain C only."
                if note not in f.notes:
                    f.notes.append(note)
        if think and not model_gave:
            for f in pending:  # the reasoning used every token: no more thinking for these
                f.no_think = True
            log("  reflexion trop longue (aucun code dans la reponse) : la suite sans reflexion")
        if not todo:
            empty += 1
            log(f"  reponse sans code nouveau ({empty}/3)")
            if empty >= 3:
                return
            continue
        empty = 0
        tc = time.time()
        results = probe_many(todo)
        cached = f", {info['cached']} en cache" if info.get("cached") else ""
        log(f"  tour {rnd}{' (reflexion)' if think else ''}{' [' + model + ']' if model != args.model else ''}: "
            f"1er token {info.get('ttft', 0):.1f}s{cached}, reponse {info.get('gen', 0):.1f}s, "
            f"{len(todo)} versions compilees en {time.time() - tc:.1f}s")
        for f in list(pending):
            mine = [(rank(f, out, lines), ok, code, out, lines)
                    for (g, code, _p), (ok, out, lines) in zip(todo, results) if g is f]
            if not mine:
                continue
            s, ok, code, out, lines = min(mine, key=lambda r: r[0])
            last = out.strip().splitlines()[-1][-50:] if out.strip() else "?"
            log(f"  {f.name} tour {rnd}: {len(mine)} versions, meilleure {last}, distance "
                f"{s[1] if s[1] < 10**6 else '-'} (avant {f.score[0]}/{f.score[1] if f.score[1] < 10**6 else '-'})")
            if ok:
                f.source = code
                pending.remove(f)
                continue
            for s2, _ok, c2, _o, l2 in mine:
                if s2[0] < 10000:
                    remember(f, c2, s2)
                if s2 >= f.score:
                    changed = [l[1:] for l in difflib.unified_diff(f.best.splitlines(), c2.splitlines(), lineterm="", n=0)
                               if l[:1] in "+-" and l[:3] not in ("+++", "---")][:6]
                    what = "does not compile" if s2[0] >= 10000 else f"{s2[0]} differing, distance {s2[1]}"
                    f.notes.append(f"- change {changed} -> {what}"[:400])
            if s < f.score:
                f.best, f.out, f.score, f.lines, f.notes, f.stale = code, out, s, lines, [], 0
            else:
                f.stale += 1
                if f.stale >= plateau:
                    log(f"  {f.name}: plus de progres depuis {f.stale} tours ({f.score[0]} diffs) : arret, le temps "
                        "va aux autres")
                    pending.remove(f)


def integrate_and_verify(found):
    """found = [(name, size, addr, source)]. True if the build still matches with all of them."""
    import auto_match as am
    saved = (am.DELINKS.read_bytes(), am.COMPILERS_TXT.read_bytes() if am.COMPILERS_TXT.exists() else b"")
    created = am.integrate(found)
    # Same style as the CI (clang-format), so the commit never breaks the lint check; verify runs after it
    pc = shutil.which("pre-commit")
    if pc:
        run([pc, "run", "clang-format", "--files", *[str(p.relative_to(ROOT)) for p in created]])
    run([sys.executable, "tools/configure.py", VERSION])
    v = run([sys.executable, "tools/match.py", "verify"])
    if v.returncode == 0 and "VERIFY PASSED" in v.stdout:
        return True
    am.DELINKS.write_bytes(saved[0])
    am.COMPILERS_TXT.write_bytes(saved[1])
    for p in created:
        p.unlink(missing_ok=True)
    run([sys.executable, "tools/configure.py", VERSION])
    return False


def commit(found):
    commit_names([f[0] for f in found], "qwen")


def commit_names(names, how):
    run(["git", "add", "src/auto", f"config/{VERSION}"])
    msg = f"Match {len(names)} function(s) ({how}, {', '.join(BLOCKS)})\n\n" + "\n".join(names) + \
        ("\n\nCo-Authored-By: Qwen <noreply@qwen.ai>\n" if how == "qwen" else "\n")
    run(["git", "commit", "-q", "-m", msg, "--", "src/auto", f"config/{VERSION}"])
    if not args.no_push and run(["git", "remote"]).stdout.strip():
        ok = run(["git", "push", "-q", "origin", "HEAD"]).returncode == 0
        log(f"push {'ok' if ok else 'rate (sera refait au prochain commit)'}")


def touch_claims():
    for b in BLOCKS:
        p = ROOT / ".studio" / "claims" / f"{b}.json"
        if p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            c["touched"] = time.time()
            p.write_text(json.dumps(c, indent=1) + "\n", encoding="utf-8", newline="\n")


def release_blocks():
    """Qwen is done with its blocks: give them back to the queue (what is left can be taken by someone else)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from dsstudio import blocks as studio_blocks, games as studio_games
        g = studio_games.Game(ROOT)
        for b in BLOCKS:
            r = studio_blocks.release(g, b)
            log(f"bloc {b} rendu a la queue" + (f" ({r.get('error') or r.get('warning')})" if r.get("error") or r.get("warning") else ""))
    except Exception as e:  # never lose the matches because of the queue
        log(f"impossible de rendre les blocs ({e}) : les rendre depuis l'app")


def multiply(names: list[str]) -> list[str]:
    """One AI match is worth more: its clones (same code, or same code with other constants, in this game) are
    matched without the AI (tools/clone_match.py), then the callers and callees of every new match are retried by
    auto_match with the real signatures they now have (tools/auto_match.py --neighbours). Each tool verifies the ROM
    itself. Returns the names they added (committed by the caller)."""
    added = []
    if (TOOLS / "clone_match.py").exists():
        emit = WORK / "clones.json"
        emit.unlink(missing_ok=True)
        r = run([sys.executable, str(TOOLS / "clone_match.py"), "--sources", ",".join(names), "--emit", str(emit)])
        clones = [tuple(c) for c in json.loads(emit.read_text(encoding="utf-8"))] if emit.exists() else []
        if clones and integrate_and_verify(clones):  # one verify for all the clones of the batch
            added += [c[0] for c in clones]
            log(f"CLONES ({len(clones)}, sans IA) : {', '.join(added)}")
        elif clones:
            log(f"{len(clones)} clones compilent mais VERIFY echoue une fois integres (annules)")
        elif r.returncode:
            log(f"clone_match a echoue : {(r.stdout + r.stderr).strip().splitlines()[-1:]}")
    if not args.no_neighbours:
        before = set(p.stem for p in (ROOT / "src" / "auto").glob("*.c"))
        r = run([sys.executable, str(TOOLS / "auto_match.py"), "--neighbours", ",".join(names + added)])
        new = sorted(set(p.stem for p in (ROOT / "src" / "auto").glob("*.c")) - before)
        if new:
            log(f"VOISINS rematches par auto_match ({len(new)}) : {', '.join(new)}")
            added += new
    return added


def preclone(names: list[str]) -> None:
    """Before any AI: the block's functions whose code is already matched elsewhere (in this game, or in another of
    our projects) are copied by tools/clone_match.py, in seconds. A model can spend an hour on a function that is
    an exact twin of one matched in another game (e.g. scalbn, MIi_CpuCopy16)."""
    if not names or not (TOOLS / "clone_match.py").exists():
        return
    emit = WORK / "preclone.json"
    emit.unlink(missing_ok=True)
    run([sys.executable, str(TOOLS / "clone_match.py"), "--other-games", "--names", ",".join(names), "--emit", str(emit)])
    clones = [tuple(c) for c in json.loads(emit.read_text(encoding="utf-8"))] if emit.exists() else []
    if not clones:
        return
    log(f"{len(clones)} fonction(s) des blocs ont une jumelle deja matchee : copiees sans IA, verification...")
    if integrate_and_verify(clones):
        commit_names([c[0] for c in clones], "clone_match")
        log(f"CLONES INTEGRES + VERIFY PASSED : {', '.join(c[0] for c in clones)}")
    else:
        log("les clones compilent mais VERIFY echoue une fois integres (annules) : Qwen les essaiera")


class Integrator(threading.Thread):
    """Single writer of the project: batches of matches -> verify -> commit. Failing batches are split."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q, self.won, self.lost, self.extra = queue.Queue(), [], [], []

    def flush(self, batch):
        import auto_match as am
        covered = am.covered_ranges()
        batch = [f for f in batch if not any(a <= f[2] < e for a, e in covered)]  # cloned meanwhile: already in
        if not batch:
            return
        if integrate_and_verify(batch):
            commit(batch)
            self.won += batch
            log(f"INTEGRE + VERIFY PASSED : {', '.join(f[0] for f in batch)}")
            more = multiply([f[0] for f in batch])
            if more:
                commit_names(more, "clones + neighbours")
                self.extra += more
        elif len(batch) > 1:
            log(f"verify echoue sur un lot de {len(batch)} : reessai une par une")
            for f in batch:
                self.flush([f])
        else:
            self.lost.append(batch[0][0])
            log(f"{batch[0][0]}: match seul mais VERIFY echoue une fois integre (annule)")
        touch_claims()

    def run(self):
        pending = []
        while True:
            try:
                item = self.q.get(timeout=30)
            except queue.Empty:
                item = "tick"
            if item is None:  # end: flush what is left
                if pending:
                    self.flush(pending)
                return
            if item != "tick":
                pending.append(item)
            if pending and (len(pending) >= args.batch or item == "tick"):
                self.flush(pending)
                pending = []


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3):
            return True
    except Exception:
        return False


def openai_up() -> bool:
    try:
        with urllib.request.urlopen(args.server.rstrip("/") + "/v1/models", timeout=3):
            return True
    except Exception:
        return False


def ensure_openai_server(wait: float = 240) -> bool:
    """The OpenAI-compatible server answers, or llama.cpp server is started on this model (workers/llm_server.py:
    the model file Ollama already downloaded, one slot per agent)."""
    if openai_up():
        return True
    launcher = Path(__file__).resolve().parent / "llm_server.py"
    log(f"serveur {args.server} injoignable : demarrage de llama.cpp server ({args.model}, {args.agents} slots)...")
    r = run([sys.executable, str(launcher), "start", "--model", args.model, "--parallel", str(max(1, args.agents)),
             "--url", args.server])
    if r.returncode:
        log((r.stdout + r.stderr).strip()[-600:])
        return False
    end = time.time() + wait
    while time.time() < end:
        if openai_up():
            log("llama.cpp server pret")
            return True
        time.sleep(2)
    log(f"le serveur ne repond toujours pas : voir {launcher.parent.parent / 'data' / 'logs' / 'llm_server.log'}")
    return False


def ensure_ollama(wait: float = 90) -> bool:
    """Starts Ollama when it is not running (the Windows app, else `ollama serve`) and waits until it answers."""
    if ollama_up():
        return True
    import os
    app = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama app.exe")
    exe = shutil.which("ollama") or os.path.join(os.path.dirname(app), "ollama.exe")
    cmd = [app] if os.path.exists(app) else [exe, "serve"] if os.path.exists(exe) else None
    if cmd is None:
        log("Ollama n'est pas installe (https://ollama.com) : impossible de lancer Qwen")
        return False
    log("Ollama ne tourne pas : demarrage...")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200 if os.name == "nt" else 0)  # detached: outlives this run
    end = time.time() + wait
    while time.time() < end:
        if ollama_up():
            log("Ollama pret")
            return True
        time.sleep(1)
    log("Ollama ne repond toujours pas : lancez-le a la main (application Ollama)")
    return False


HARD = WORK / "hard.json"


def prepare(fns: list[Fn], profiles: list[str]) -> None:
    """Starting point of each function: memory of earlier runs, the compiler of its address zone first, both
    default compilers, all compiled at once; then its context and expected difficulty."""
    for f in fns:
        load_memory(f)
    tries = {f.name: list(dict.fromkeys([p for p in [f.profile, zone_profile(f.addr)] if p] + profiles)) for f in fns}
    cands = [(f, f.best, p) for f in fns for p in tries[f.name]]
    res = probe_many(cands)
    for f in fns:
        mine = [(rank(f, out, lines), p, out, lines) for (g, _c, p), (_ok, out, lines) in zip(cands, res) if g is f]
        f.score, f.profile, f.out, f.lines = min(mine, key=lambda r: r[0])
        f.tried.add(code_hash(f.best))
        if f.score[0] < 10000:
            remember(f, f.best, f.score)
        f.context = code_context(f.name)
        f.fixed()  # target assembly, used by difficulty()
        f.diff = difficulty(f)
        f.easy = f.size <= args.group_size and f.score[0] <= 6
        if f.score[0] == 0:
            f.source = f.best


def main():
    if not args.hard and not BLOCKS:
        sys.exit("donner --blocks (ou --hard pour la file des fonctions presque matchees)")
    blocks = {b["id"]: b for b in json.loads((ROOT / ".studio" / "blocks.json").read_text(encoding="utf-8"))["blocks"]} \
        if BLOCKS else {}
    missing = [b for b in BLOCKS if b not in blocks]
    if missing:
        sys.exit(f"blocs introuvables dans .studio/blocks.json : {missing}")
    if not (ensure_openai_server() if args.backend == "openai" else ensure_ollama()):
        sys.exit(1)
    import auto_match as am
    syms = {}
    for line in am.SYMBOLS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+)\s+kind:function\((arm|thumb),size=0x([0-9a-f]+)\).*addr:0x([0-9a-f]+)", line)
        if m:
            syms[m.group(1)] = (int(m.group(4), 16), int(m.group(3), 16), m.group(2))
    hard = json.loads(HARD.read_text(encoding="utf-8")) if HARD.exists() else {}
    if args.hard:
        names = [n for n in hard if n in syms]
    else:
        names = [n for b in BLOCKS for n in blocks[b]["functions"] if n in syms]
        preclone(names)
    covered = am.covered_ranges()
    names = [n for n in names if syms[n][2] == "arm" and not any(a <= syms[n][0] < e for a, e in covered)]
    no_draft = [n for n in names if not starting_draft(n) and n not in hard]
    if no_draft:
        log(f"{len(no_draft)} fonction(s) sans brouillon : brouillon m2c (tools/draft.py)")
        make_drafts(no_draft)
    todo = []
    for n in names:
        src = hard[n]["best"] if args.hard and n in hard else starting_draft(n)
        if src:
            todo.append((n, syms[n][1], syms[n][0], src))
    # Worth the most matches first (same code in other games + clones here). One function per family of clones:
    # once it matches, clone_match makes the others; the rest of the family comes after.
    weight, first = {}, {}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from dsstudio import games as studio_games
        g = studio_games.Game(ROOT)
        weight = {r["name"]: studio_games.weight(r) for r in g.functions()}
        first = {n: row.get("first", n) for n, row in studio_games.clone_families(g).items()}
    except Exception as e:
        log(f"(ordre par jumelles indisponible : {e})")
    if args.max:
        todo = sorted(todo, key=lambda t: (-weight.get(t[0], 0), t[1]))[:args.max]
    global GEN
    if args.agents > 1 and not model_runs_in_parallel(args.model):
        # One request at a time on the GPU: 2 agents take turns, one compiles while the other generates (the time
        # limit only counts generation, see solve). More agents would only wait longer for their turn.
        if args.agents > 2:
            log(f"le modele {args.model} ne repond qu'a une requete a la fois dans Ollama : 2 agents (au lieu de "
                f"{args.agents}) qui alternent generation et compilation")
            args.agents = 2
        GEN = threading.Semaphore(1)
    else:
        GEN = threading.Semaphore(max(1, args.agents))
    profiles = [c[0] for c in am.COMPILERS[:2]]
    default = profiles[0]
    STOP.unlink(missing_ok=True)
    integ = Integrator()
    integ.start()
    fns = [Fn(*t) for t in todo]
    log(f"{len(fns)} fonctions : preparation (memoire des essais, compilateur de la zone, difficulte)...")
    prepare(fns, profiles)
    done_names = set()

    def matched(f: Fn, source: str) -> None:
        if f.name in done_names:
            return
        why = pt.fake_match(source, f.draft)
        if why:  # last gate: a match from memory or the permuter is checked too
            log(f"{f.name}: match refuse, pas integre (faux match : {why})")
            return
        done_names.add(f.name)
        if f.profile != default and not source.startswith(am.MARKER):
            source = f"{am.MARKER}{f.profile} */\n" + source
        integ.q.put((f.name, f.size, f.addr, source))

    for f in fns:
        if f.source:
            log(f"{f.name}: deja MATCH au depart ({f.profile}) -> file d'integration")
            matched(f, f.source)
    seen = set()

    def order(f):
        rep = first.get(f.name, f.name)
        later = rep in seen  # another function of the same family comes first
        seen.add(rep)
        return (later, -weight.get(f.name, 0), f.diff)
    fns.sort(key=lambda f: f.diff)
    fns.sort(key=order)

    def run_pass(group: list[Fn], minutes: float, plateau: int, final: bool) -> None:
        # Small functions go by batches of neighbours of similar size: one request for several of them
        units, used = [], set()
        small = [f for f in group if f.size <= args.group_size] if args.group > 1 else []
        for f in group:
            if f.name in used:
                continue
            unit = [f]
            if f in small:
                near = sorted((u for u in small if u.name not in used and u is not f),
                              key=lambda u: (abs(u.addr - f.addr) // 0x400, abs(u.size - f.size), abs(u.addr - f.addr)))
                unit += near[:args.group - 1]
            used.update(u.name for u in unit)
            units.append(unit)

        def agent(unit):
            if STOP.exists():
                return
            covered = am.covered_ranges()
            unit = [f for f in unit if f.source is None and not any(a <= f.addr < e for a, e in covered)]
            if not unit:
                return
            for f in unit:
                dist = f.score[1] if f.score[1] < 10**6 else "-"
                log(f"{f.name} ({f.size} octets, {f.profile}) : {f.score[0]} diffs, distance {dist}"
                    + (" [edits]" if f.patch_mode and len(unit) == 1 else ""))
            if len(unit) > 1:
                log(f"lot de {len(unit)} petites fonctions : {', '.join(f.name for f in unit)}")
            t0 = time.time()
            solve(unit, minutes, plateau, final)
            for f in unit:
                if f.source is not None:
                    log(f"{f.name}: MATCH en {time.time() - t0:.0f}s -> file d'integration")
                    matched(f, f.source)
                else:
                    log(f"{f.name}: pas de match ({f.score[0]} diffs, {time.time() - t0:.0f}s)")
                    if 0 < f.score[0] <= args.permute_at:
                        permute(f, matched)
                save_memory(f)
        with ThreadPoolExecutor(max_workers=max(1, args.agents)) as ex:
            list(ex.map(agent, units))

    pass1 = [f for f in fns if f.source is None]
    log(f"passe 1 (rapide, {args.pass1_minutes:g} min max par fonction, arret apres {args.plateau} tours sans progres) : "
        f"{len(pass1)} fonctions, {args.agents} agent(s), modele {args.model}"
        + (f" (+ {args.small_model} pour les faciles)" if args.small_model else "")
        + f", {args.variants} versions par reponse" + (f", blocs {', '.join(BLOCKS)}" if BLOCKS else ", file difficile"))
    run_pass(pass1, args.pass1_minutes, args.plateau, final=False)
    close = [f for f in fns if f.source is None and f.name not in done_names and 0 < f.score[0] <= args.pass2_diffs]
    if close and not STOP.exists():
        # The C may be right and the compiler or the flags wrong: try all of them on the close ones (CPU only)
        log(f"{len(close)} fonction(s) a {args.pass2_diffs} diffs ou moins : essai des autres compilateurs et options")
        for f, found in zip(close, COMPILE_POOL.map(sweep_profiles, close)):
            if not found:
                continue
            p, out, lines, r = found
            log(f"  {f.name}: {p} -> {out.strip().splitlines()[-1] if out.strip() else '?'}")
            f.profile, f.out, f.lines, f.score = p, out, lines, r
            if r[0] == 0:
                f.source = f.best
                matched(f, f.best)
        close = [f for f in close if f.source is None]
    if close and not STOP.exists():
        log(f"passe 2 (longue, {args.minutes:g} min max) sur les {len(close)} fonction(s) les plus proches"
            + (f", reflexion a {args.think_at} diffs ou moins" if args.think_at else ""))
        for f in close:
            f.stale = 0
        run_pass(close, args.minutes, args.plateau * 2, final=True)
    if STOP.exists():
        log("fichier STOP trouve : arret apres les fonctions en cours.")
    PERMUTE_POOL.shutdown(wait=True)  # permuter matches still go through the integrator
    # Functions left a few instructions away: the queue for a bigger model (--hard)
    for f in fns:
        if f.name in done_names:
            hard.pop(f.name, None)
        elif 0 < f.score[0] <= args.pass2_diffs:
            hard[f.name] = {"score": list(f.score), "best": f.best, "profile": f.profile, "t": time.time(),
                            "model": args.model}
    HARD.write_text(json.dumps(hard, indent=1), encoding="utf-8")
    left = [n for n in hard if n not in done_names]
    if left:
        log(f"{len(left)} fonction(s) a {args.pass2_diffs} diffs ou moins dans la file difficile "
            f"({HARD.relative_to(ROOT)}) : `--hard --model <plus gros modele>`")
    integ.q.put(None)
    integ.join()
    if not args.hard:
        release_blocks()
    log(f"fini : {len(integ.won)} nouvelles fonctions sur {len(fns)}"
        + (f", + {len(integ.extra)} sans IA (clones, voisins)" if integ.extra else "")
        + (f" ; rejetees au verify : {', '.join(integ.lost)}" if integ.lost else ""))


if __name__ == "__main__":
    lock_mod = ROOT / "tools" / "pipeline_lock.py"
    if lock_mod.exists():  # same lock as the moulinette / auto_match of this game: never two pipelines at once
        from pipeline_lock import pipeline_lock
        with pipeline_lock("qwen_block", ROOT):
            main()
    else:
        main()
    # the job is over: every miss kept (this job and all earlier ones, all games) is tried on every unmatched
    # function of this game; matches are verified, committed (and pushed)
    if not STOP.exists():
        log("missdb : les essais rates sont rejoues sur toutes les fonctions non matchees du jeu...")
        subprocess.run([sys.executable, str(TOOLS / "missdb.py"), "replay", "--all-games", "--commit"]
                       + ([] if args.no_push else ["--push"]), cwd=ROOT)
