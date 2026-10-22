"""Work sheet of a block: everything a person or an AI (Claude, Qwen Code, ...) needs to work on it alone."""
from . import blocks, config, difficulty


def brief(g, block_id: str) -> str:
    fns = blocks.functions_of(g, block_id)
    todo = [f for f in fns if not f["done"]]
    v = g.version
    lv = difficulty.LEVELS[next((b["level"] for b in blocks.load(g)["blocks"] if b["id"] == block_id), 1)]
    lines = [
        f"# {g.title} - block {block_id} ({lv['label']})",
        "",
        f"Project: `{g.path.as_posix()}` (version `{v}`). {len(todo)} of {len(fns)} functions left.",
        "",
        "## Goal",
        "Matching decompilation: write C that compiles (Metrowerks mwccarm) to exactly the same bytes as the game.",
        "",
        "## Rules",
        f"- Before starting: `python \"{(config.STUDIO / 'studio.py').as_posix()}\" claim {g.id} {block_id} --who <your name> --kind claude`.",
        "- Activate the environment first: `source \"" + config.ENV_SH.as_posix() + "\"` (Git Bash).",
        "- Never commit unless `python tools/match.py verify` prints `VERIFY PASSED`.",
        "- Only commit `src/`, `include/` and `config/` files you changed (never `git add -A`). ASCII only.",
        "- Format before verifying: `pre-commit run clang-format --files <your .c files>` (the CI checks it).",
        "- Never use leaked source code. Clean-room: from the binary and public projects only.",
        "- A function you cannot match: leave it, note why in the claim (`studio.py touch ... --note`).",
        f"- When finished: `python \"{(config.STUDIO / 'studio.py').as_posix()}\" done {g.id} {block_id}`.",
        "",
        "Functions whose note names an external decompilation (decomps-externes/) are matched automatically:",
        f"`python ../../studio/gametools/donor_match.py --names <f1,f2,...>` (or the task \"Reprendre les matchs des autres decomps\").",
        "",
        "After matching functions, multiply them without any AI before committing:",
        "`python ../../studio/gametools/clone_match.py --other-games --sources <f1,f2,...>` (functions of this game with the same code,",
        "or the same code with other constants: C copied, renamed, compiled, verified) and",
        "`python ../../studio/gametools/auto_match.py --neighbours <f1,f2,...>` (callers / callees retried with the real signatures).",
        "",
        "## How to match one function",
        f"1. Assembly: `build/{v}/asm/` (run `ninja dis` if missing). Draft: `build/auto/near/<name>.c`, "
        "`build/drafts/<name>.c`, or `python ../../studio/gametools/draft.py <name>`.",
        "2. Put the C in `src/auto/<name>.c` (or a real source file) and check one function:",
        "   `python tools/probe_compiler.py src/auto/<name>.c <name> <address> --only 2.0/sp1p5 --flags=-O4,p --show`",
        "   (`1.2/sp2p3` for library code: epilogue `ldmfd sp!, {..., lr}` + `bx lr`).",
        f"3. Declare it in `config/{v}/arm9/delinks.txt` (`complete`, `.text start/end`), "
        f"`python tools/configure.py {v}`, `ninja`, `python tools/match.py verify`.",
        "4. Commit with the list of matched functions.",
        "",
        "## Functions",
        "",
        "| Function | Address | Size | Mode | Level | auto_match | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in fns:
        if f["done"]:
            continue
        note = ""
        if f.get("port"):
            p = f["port"]
            if p["game"].startswith("donor:"):
                note = (f"same code in {p['game'][6:]} ({p['name']}, `{p['file']}`): "
                        f"`python ../../studio/gametools/donor_match.py --names {f['name']}`")
            elif p["game"].startswith("clone:"):
                note = (f"same code as {p['name']} (matched in this game): "
                        f"`python ../../studio/gametools/clone_match.py --names {f['name']}`")
            else:
                note = (f"same code matched in {p['game']}: `{p['file']}` ({p['name']}): "
                        f"`python ../../studio/gametools/clone_match.py --other-games --names {f['name']}`")
        elif f.get("shared", 0) >= 2:
            note = f"SDK, in {f['shared']} other games"
        if f.get("family"):
            note = (note + "; " if note else "") + (f"{f['family']} other function(s) of this game have the same code"
                                                   " (maybe other constants): match this one, `tools/clone_match.py`"
                                                   " makes them")
        if f.get("module", "main") != "main":
            note = (note + "; " if note else "") + (f"module {f['module']}: delinks in "
                                                   f"config/{v}/arm9/{'overlays/' if f['module'].startswith('ov') else ''}"
                                                   f"{f['module']}/delinks.txt")
        if f.get("mode") == "thumb":
            note = (note + "; " if note else "") + "Thumb: compile with `-thumb` (no automatic tool)"
        lines.append(f"| {f['name']} | 0x{f['addr']:08x} | {f['size']} | {f['mode']} | "
                     f"{difficulty.LEVELS[f.get('level', 1)]['label']} | {difficulty.AUTO_LABEL.get(f['auto'], f['auto'])} | {note} |")
    done = [f["name"] for f in fns if f["done"]]
    if done:
        lines += ["", f"Already matched in this block: {', '.join(done)}"]
    return "\n".join(lines) + "\n"
