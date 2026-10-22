# Instructions for AI agents

DS Decomp Studio coordinates people and AIs working on Nintendo DS matching decompilations. Work is split into
**blocks of 50 functions** of similar difficulty. Always take a block before working, so nobody duplicates effort.

## Workflow

```shell
python studio/studio.py games                                  # projects and progress
python studio/studio.py blocks <game> --free                   # free blocks, easiest first
python studio/studio.py claim <game> next --who <agent-name> --kind claude [--level N]
python studio/studio.py brief <game> <block>                   # your work sheet: functions, commands, rules
# ... match functions in projets/<game>/ ...
python studio/studio.py touch <game> <block> --note "..."      # still working / what blocks you
python studio/studio.py done <game> <block>                    # or `release` to give it back unfinished
```

### With MCP (Claude Code, Codex...)

`python studio/studio.py mcp-config` prints the command that gives an agent the studio's tools
(`workers/mcp_server.py`): claim_block, get_function (asm, draft, Ghidra's reading, calls, look-alikes from all
games), compile_and_diff, submit_match, commit_matches, read_data / check_data, edit_header, split_function. They
all run `studio/gametools/workbench.py` in the game's folder, which can also be used by hand (from `projets/<game>/`):

```shell
python ../../studio/gametools/workbench.py info <function>          # everything about one function (JSON)
python ../../studio/gametools/workbench.py judge <function> f.c     # compile + compare with the game's compilers
python ../../studio/gametools/workbench.py submit <function> f.c    # into src/auto, ROM rebuilt, kept only if byte-identical
python ../../studio/gametools/workbench.py commit [--push]          # one full verify for all submitted matches, then commit
python ../../studio/gametools/workbench.py data <symbol>            # decoded data + a C declaration; datacheck f.c compares it
python ../../studio/gametools/workbench.py header include/engine.h new.h   # shared header, kept only if the ROM still matches
python ../../studio/gametools/ghidra_draft.py --names a,b            # Ghidra drafts in build/ghidra/ (2nd reading after m2c)
```

## Rules

1. Work only inside `projets/<game>/`. Run `source env.sh` (Git Bash) first.
2. Never commit unless `python tools/match.py verify` prints `VERIFY PASSED`. Commit only the files you changed
   (`src/`, `include/`, `config/`), never `git add -A`.
3. ASCII-only sources, comments in English. `asm` functions only for instructions the compiler never emits.
   Fake matches are refused by the tools (`gametools/fakematch.py`): asm, new `#define`/`#pragma`/`#include` lines,
   `##`, `_Pragma`, `__declspec`/`__attribute__`, machine code written as numbers.
4. Never use leaked source code. Never commit ROMs, extracted assets or build outputs.
5. `.studio/` is written by the studio only (through the commands above).
6. Level "Portable" functions have an identical twin already matched in another game: the brief names the source
   file to copy.

## Layout

- `dsstudio/games.py`: project discovery, functions, matched state (`delinks.txt`), cross-game twins (`fpdb.sqlite`).
- `dsstudio/difficulty.py`: levels. `dsstudio/blocks.py`: blocks and claims. `dsstudio/jobs.py`: machine task queue.
- `dsstudio/server.py` + `web/`: the web app. `workers/qwen_block.py`: local Qwen agents on blocks (Ollama, or an
  OpenAI-compatible server: `workers/llm_server.py` runs llama.cpp server on the GGUF file Ollama downloaded).
- `gametools/`: the ONLY source of the matching tools. They run from here with cwd = the game (`project.py`
  finds it: `DSD_PROJECT`, else the current folder). Only the build tools (`toolsync.BUILD_TOOLS`: configure,
  ROM rebuild, `match.py`, `probe_compiler.py`) are copied into a game's `tools/` (`studio.py sync-tools`;
  `--slim` removes a game's old copies of the others). Change tools here, never in a game's copy.
  `gametools/find_culprits.py` finds the files that break the ROM from one build (byte comparison).
  `gametools/clone_match.py` multiplies matches without AI: same code (or same code with other constants) as a
  matched function, in this game or another of our projects; `--list` writes build/clone/families.json, which
  the studio reads for level 0 and to put the functions worth several matches first in the queue.
