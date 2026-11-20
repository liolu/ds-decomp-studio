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
3. ASCII-only sources, comments in English. `asm` functions only for instructions the compiler never emits, or for
   functions the user listed in the game's `config/asm_allowed.txt` (hand-written code proven not to be C).
   Fake matches are refused by the tools (`gametools/fakematch.py`): asm, new `#define`/`#pragma`/`#include` lines,
   `##`, `_Pragma`, `__declspec`/`__attribute__`, machine code written as numbers. Only exception: a `__sinit_*`
   function (C++ static initializer, which the compiler puts in `.init`, with a pointer to it in `.ctor`) may declare
   `#pragma define_section INIT ".init" ".init"` / `#pragma define_section CTOR ".ctor" ".ctor"` and use
   `__declspec(INIT)` / `__declspec(CTOR)` for that function and its `.ctor` entry. Same for `BuildInfo` (NitroSDK
   crt0 module params + `[SDK+...]` version string, data the original build places in `.text`):
   `#pragma define_section NAME ".text" ".text"` and `__declspec(NAME)`.
4. Never use leaked source code. Never commit ROMs, extracted assets or build outputs.
5. `.studio/` is written by the studio only (through the commands above).
6. Level "Portable" functions have an identical twin already matched in another game: the brief names the source
   file to copy.
7. Judge every try with `workbench.py judge` (or the MCP compile_and_diff), never with your own compiler call:
   each C that compiles but misses is recorded in the miss database (`gametools/missdb.py`, one
   `decomp ds/missdb.sqlite` for all games) and replayed on every unmatched function of every game. A miss of
   function A is often the exact C of a sibling B, here or in another game.
8. Put your misses in the right place. The game a miss belongs to is the name of the folder you run from, so run
   `workbench.py` from `projets/<game>/` itself (or set `DSD_PROJECT` to it), never from a worktree, a copy or a
   scratch folder. Never set `MISSDB` and never make another copy of `missdb.sqlite`: the only database is
   `decomp ds/missdb.sqlite`. A try you could not judge (compiler error in your own harness, session cut short)
   goes to `projets/<game>/build/hunt/best/<function>.c`, the file named exactly after the function, where
   `missdb.py import` picks it up. Never leave misses in /tmp, a scratchpad, notes or the game repository.

9. Identical bytes alone are not a match: follow [CODE-RULES.md](CODE-RULES.md). `workbench.py judge` (MCP
   compile_and_diff) answers `rules: MATCH-PENDING` with the [match] rules that fire. Offset casts, local type
   copies, `extern` lines in the .c file and steering code are scaffolding: remove them before you report a match.
   When a spelling matches only through a trick (a `volatile`, a dummy local, a reused variable, `(u8 *)p + K`), it
   is a clue: look for the helper, the type or the second variable it hides. If you cannot find it, submit the
   function and report it as `MATCH-PENDING` with the rules and your guess. Never invent a confident name: keep
   `func_02001234` / `arg0` / `unk_58` until evidence names it.

## Code rules profile

The project profile [CODE-RULES.md](CODE-RULES.md) asks for. A game's own `AGENTS.md` overrides it (its original
studio's naming style, its dialect, a rule it tightens or relaxes, each with the reason).

- **Compiler and dialect.** Metrowerks `mwccarm` (CodeWarrior for NDS 1.2 and 2.0 builds), `-O4,p`, base flags
  `-enum int -char signed -gccext,on -inline noauto -lang=c -interworking` (`probe_compiler.BASE_FLAGS`). Each file's
  real profile is its first line `/* compiler: <version> <flags> */` and `config/<version>/compilers.txt`. C is
  C89 with the extensions the drafts already use (`//` comments, `static inline`, `long long`); write declarations
  at the top of a block unless the file's profile says `-lang c99`. C++ files (`.cpp`, `-lang=c++`) are pre-C++11:
  no `nullptr`, `auto`, `enum class`. `enum` is `int`-sized and `char` is signed. `judge` is the referee: a dialect
  error is a compile error.
- **Annotations.** Line 1 `/* compiler: ... */` when the profile is not the game's default; the attribution comment
  of a reused file stays above its function; `// ASM: <public decompilation>` on a function proven to be original
  assembly; `// volatile: <evidence>`, `// reserved: <SDK or format name>`, `// R36: <what the bytes show>` and
  `// RULE-EXCEPTION: <rule>, <reason>` where the checker or a reader needs the evidence. There is no parking
  mechanism in `src/`: unfinished attempts live in `build/hunt/` and the miss database, never behind an `#if`.
- **Names.** Library code (NitroSDK, NitroSystem, MSL...) keeps the recorded names that `names.py` finds in public
  decompilations, verbatim: `OS_CreateThread`, `NNS_FndAllocFromExpHeap`, `OSThread`, files like
  `src/nitro/os/os_thread.c` (`regroup.py`). Game code: the original studio's style where the binary shows it
  (assert strings, file names, RTTI), recorded in the game's `AGENTS.md`; with no evidence, `Prefix_VerbNoun`
  functions, `lowerCamel_t` struct types and `UPPER_SNAKE` constants for C, `PascalCase` methods and `lowerCamel`
  members for C++. Placeholders (open naming work, never a failed match): `func_XXXXXXXX`, `func_ovNNN_XXXXXXXX`,
  `data_XXXXXXXX`, `lbl_XXXXXXXX`, `arg0`, `temp_r4`, `var_r5`, `sp10`, `phi_`, `unk_XX`, `M2C_UNK`.
- **Layout.** The game's `.clang-format` decides (the CI checks it): LLVM base, 4 spaces, 127 columns, K&R braces,
  braces on every block. Function banner: `/*` `====` `Name` *what it does* `====` `*/`; a unit opens with
  `// file.c -- what this unit does`.
- **Evidence sources.** The game binary (strings, asserts, RTTI), public decompilations (`donors.sqlite`), the
  same code matched in another game of the workspace (`fpdb.sqlite`). Never leaked source, never SDK source.
- **Line information.** Retail ROMs carry no line tables. `__LINE__` reaches the bytes only in units that call an
  assert or panic macro (the files the binary names in its assertion strings): layout changes there are [checked].
- **Commands.** Per-function check: `workbench.py judge NAME FILE.c`. Byte gate: `python tools/match.py verify`.
  Rule checker: `python tools/coderules.py [--pending] [--advisory]` (`studio.py rules <game>`); `verify` and
  `progress` print both numbers.
- **Rule changes.**
  - R23: the line limit is 127 columns and the layout is clang-format's, because the games' CI already enforces
    that file.
  - R18: `ORIGINAL-ASM` means the function is in the game's `config/asm_allowed.txt` or carries an `// ASM:`
    citation. An `asm` function written only because it holds an instruction the compiler never emits
    (`swp`, `mrs`, `clz`...) is `MATCH-PENDING` until evidence shows whether the original was assembly or C around
    an inline helper.
  - R17/R22: the section pragmas of rule 3 (`__sinit_*` in `.init`/`.ctor`, `BuildInfo` in `.text`) are recorded
    exceptions: the original build placed those objects there.
  - R1, R2, R4 are not relaxed. `src/auto/` is raw m2c output: its functions stay `MATCH-PENDING` until their
    structs and externs move into headers.
  - R24: the progress blocks of the READMEs, `.studio/`, `build/` and the miss database are generated: run the
    tool, never edit them.

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
  `gametools/missdb.py` is the miss database: `workbench.judge` and `qwen_block` record every miss (C, profile,
  error, fingerprint of the compiled code; ARM and Thumb, any module), auto_match its near misses (`import`);
  `replay` looks each miss's fingerprint up among the unmatched functions of every module (main, ITCM,
  overlays; no compile), renames calls/symbols (other overlays through relocs.txt) and constants like
  clone_match, then checks word by word. Main-module ARM matches: clone_match.integrate_verified; overlay,
  ITCM, Thumb and -profile ones: `workbench.py submit-many` (ROM rebuilt, byte-identical or dropped).
  It runs by itself at the end of every Qwen job (`--all-games`), of the auto job and of every `hunt.py sweep`
  (`--to build/hunt/matched`); Studio jobs `misses` (one game) and `misses_all` (misses of every game on every
  game). The game page shows how many misses are kept and how many matches they gave.
  `gametools/reuse.py` gains with no AI: `scan` (dry-run of clone_match + donor_match, writes build/reuse/estimate.json: functions,
  bytes, seconds per game, the grey part of the Studio's bars), `apply` (donors then clones, verified, local commits, never a push;
  skips a game with uncommitted work). Studio jobs `reuse` (one game), `reuse_scan`, `reuse_apply` (best functions per minute first).
  DATA (`gametools/missdata.py`): `workbench.py datacheck` records every object that differs (its C alone, the
  bytes it compiled to, its pointers); `replay` also gives the unmatched .data / .rodata of every module the C of
  a data miss or of the same data matched in another of our games (`--all-games`; fingerprint = section + size
  + bytes, pointers masked then renamed), one file per object (src/data/<module>_<section>_<addr>.c), ROM rebuilt.
  CODE RULES (`gametools/coderules.py`, a build tool: copied into each game as `tools/coderules.py`): the checker of
  [CODE-RULES.md](CODE-RULES.md). `fakematch.py` refuses what can never be source before compiling (asm, sections,
  preprocessor tricks); `coderules.py` judges what did match: `ok`, `MATCH-PENDING` (R1, R2, R4, R13, R17, R18) or
  `ORIGINAL-ASM`, per function, plus advisory findings (names, banners). `workbench.judge` attaches it to every
  match, `match.py verify`/`progress` and `studio.py rules <game>` count it (build/coderules/report.json).
  `--no-data` / `--data-only`. The game page has a Donnees tab (dsstudio/data.py: every data symbol, matched or
  not, its bytes and an exact C declaration).
