# Agent brief: match many functions fast (Rayman Raving Rabbids)

Project dir (cwd for every command): `D:\... logiciel\decomp\decomp ds\projets\rayman-rr`, version `usa`.
Setup once per shell. Bash: `source ../../env.sh`. PowerShell: `. "..\..\env.ps1"`. G below = `../../studio/gametools`.
Your list and your own dir are given in your prompt: list `build/hunt/ROUND/listK.txt`, dir `build/hunt/ROUND/aK/`.

Breadth first: try EVERY function of the list once, about 1 minute each, cheapest first. Then, with time left, come back
to the ones at few diffs. Give up on a function after 4 judges without progress. Do not stop before your stop time unless
every function has been tried and revisited. Check the time with `date +%H:%M` after every few functions.

For each NAME:
1. `python G/techlog.py history NAME` (everything already tried; prototypes run by the orchestrator in the background,
   a better variant may be in `build/hunt/proto/NAME/`). Do NOT run protorun.py yourself: it takes 20 s per function.
2. `python G/workbench.py info NAME` (JSON: draft, target asm, profile). Rewrite from the asm when the draft does not compile.
3. Write `aK/NAME.c`, judge: `python G/workbench.py judge NAME aK/NAME.c --profile "2.0/sp1p5"`. Use the same file name:
   that file is the final answer, keep your best try in it. Ideas in bulk: `python G/tryc.py NAME 'C 1' 'C 2' -p P`.
4. After a MATCH: `python G/relcheck.py NAME aK/NAME.c PROFILE` (judge masks the literal pool). A match only counts if it passes.
5. After each technique: `python G/techlog.py add NAME TECH_ID ok|better|fail --diffs N --note "what" --file F.c --by aK`
   (ids in `G/TECHNIQUES.md`, a new trick gets a new short id; keep it to one line per real attempt).

Profiles: this game is mostly `2.0/sp1p5`; library code (epilogue `ldmfd sp!, {..., lr}` + `bx lr`, or `sub sp,sp,#4` after an
odd push) = `1.2/sp2p3` or `1.2/sp3`; try those when the size differs. `-O2,p` suffix: loops with `b cond` entry and mul.

Rayman tricks: stack-passed 2nd arg with `push {r0-r3}` prologue = parameter declared `volatile`. `tst rX,#0xff` of a bool =
`long` flag tested with `& 0xFF`, or `unsigned char x = (a != c)`. Register swaps: local declaration order, reuse a dead
variable as loop counter. `data[i].f` vs `(char *)data + off` changes the address order. Stack arrays are laid out in
reverse declaration order. Early returns: `if (a != 0 || b != 0) return 0;` first. FS_SeekFile takes 3 args (origin 0).
`-inline noauto`: only `inline`-marked functions inline.

General fixes: u8* pointer arithmetic (m2c scales `p + 0x18`), extern type u8 vs s32, `for`/`do while` instead of goto, temp
for a call result, struct assign instead of 2-word copies, `volatile` on HW regs, vcall
`(*(R (**)(void *))(*(u8 **)obj + K))(obj)`, a value set in r1-r3 before a call and otherwise unused = hidden call argument,
bitfield structs for lsl/lsr/bic/orr, `switch` with `default:` last, `void` return if r0 is only a callee's result.
Skip after 1 judge: C++ EH fragments, hand asm (`swp`, odd regs), `__sinit`, Thumb BIOS stubs, `ldr ip,=0xfffffffc` thunks.

RULES (violations make the match rejected):
- ASCII sources, English comments. `#include "m2c.h"` is fine; NO asm, `#define`, `#pragma`, other `#include`,
  `__attribute__`, `__declspec`, `##`, numbers as machine code.
- ONLY judge, always with workbench.py / tryc.py, from the project dir. NEVER run `workbench.py submit/submit-many/commit`,
  `hunt.py try/note/park/sweep`, `studio.py`, `match.py`, `ninja`, git. Never set MISSDB.
- Write only in your own dir `aK/`, in the journals of YOUR functions (through techlog.py) and NEW scripts in
  `G/prototypes/` (docstring + `proto_run(ctx)` when possible). Helper scripts never in /tmp.
- Never use leaked SDK source.

Final answer (short): `NAME: MATCH <profile>` lines, then `no: NAME (N diffs)` for the near misses, plus new technique ids.
