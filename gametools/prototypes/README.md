# prototypes/ - every technique script that is not proven yet

Rule: **every technique is a file.** A trick tried by hand, by an agent or in a session scratch dir is written here as a
script (never only in /tmp, a scratchpad or `build/hunt/w`), so the next session runs it instead of re-inventing it.

- A new technique script starts HERE, with a docstring (usage + what it changes + where it came from).
- If it can run unattended on one function, give it `proto_run(ctx)` (see `../protorun.py`): `protorun.py NAME` then
  runs it on every function before hand work, and logs the result in that function's journal (`proto:<tool>`).
- Paths: import the shared tools with `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`; run from the
  project dir (`projets/<game>`), write outputs under `build/hunt/`, never next to the script.
- When it MATCHES a function (journal entry `ok`, checked by `../techlog.py stats`), promote it:
  `python ../../studio/gametools/protorun.py promote TOOL` (moves it to `gametools/`), and move its line in
  `../TECHNIQUES.md` from "Prototypes" to "Functional tools".
- A prototype that never helps (many `fail`, no `ok`/`better`) stays here with a note in TECHNIQUES.md: it documents
  what does not work.

Current prototypes (details in each docstring and in `../TECHNIQUES.md`):

| file | runs in protorun | what |
|---|---|---|
| profextra.py | yes | judge the C on every compiler profile hunt knows + 1.2/sp2p3 and -O1/-O2/-O4,s variants |
| declperm.py | yes | random orders of the local declarations (callee-saved register order) |
| cmutate.py | yes | session-lesson mutations: `s32`->`int`, `x = -x` <-> `x *= -1`, chained assignment order, return cast |
| asmconv.py | yes (asm-only functions) | whole-function `asm` version for swp/swi/mrs/coprocessor functions |
| mscore.py | no | rank variants by mnemonic/shape mismatches, registers ignored |
| regions.py | no | count diffs per region of the target (where is the function still wrong) |
| schedscan.py | no | parallel judge of many variants, compare an exact instruction window (scheduling puzzles) |
