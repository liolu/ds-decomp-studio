# TECHNIQUES - every matching technique we use, and where it lives

Each technique has an **id** (bold). Use exactly that id in the per-function journal:
`python ../../studio/gametools/techlog.py add NAME ID ok|better|fail|skip --diffs N --note "..."`.
`techlog.py stats` counts ok/fail per id over all functions of a game; `techlog.py history NAME` lists, for a function,
what was already tried and which ids worked elsewhere but were never tried on it.

Three levels:
1. **Functional tools** - proven (at least one real match); scripts in `studio/gametools/`.
2. **Prototypes** - scripts in `studio/gametools/prototypes/`, not proven yet. `protorun.py NAME` runs every one that
   defines `proto_run` and logs its result. A prototype with an `ok` is promoted: `protorun.py promote TOOL`.
3. **Manual** - C-level tricks with no script yet. Rule: when you apply one more than once, write it as a prototype
   (a mutation in `prototypes/cmutate.py` or a new file) so it becomes automatic.

## Workflow per function (agents and hand sessions)
1. `techlog.py history NAME` - read everything done before (journal, ledger, best C, missdb, untried winners).
2. `protorun.py NAME` - every prototype + auto tool on the best C; results go to the journal by themselves.
3. Work by hand from `build/hunt/proto/NAME/*.c` (if one is better) or the best C.
4. After EVERY technique tried, success or failure: `techlog.py add NAME ID RESULT --diffs N --note "what exactly"`.
5. A new idea that is a script -> `prototypes/` (with `proto_run` when it can run alone), never only in scratch.

## Functional tools (studio/gametools)
- **profile-sweep** `hunt.py try` (all profiles), `vsweep.py` (250 compiler versions/flags), `optsweep.py`; header profile is often wrong: try 1.2/sp3, 1.2/sp2p3, 2.0/sp1p5 -O1/-O2/-O4,s, `-profile`
- **hunt-battery** `hunt.py try/sweep`: decl-swap, stmt-swap, if-invert, param-volatile, byteptr, call-temp, unfold, ptr-u8, extern-u8, shift-div, cmp-hoist, pad-param, loop forms, vcall-this2 (orchestrator only: writes the ledger)
- **siblings** `hunt.py sibs NAME`, `sibmatch.py`, `clone_match.py`: transplant a match to same-shape functions
- **donor** `donor_match.py`: reuse C from external decomps (donors.py index)
- **missdb-replay** `missdb.py replay`: every recorded miss replayed by fingerprint on all games
- **variant-batch** `judgemany.py NAME files...` (was TnJ jm.py): judge many hand variants in one process, ~1 s each
- **pool-check** `relcheck.py NAME FILE.c [P]`: literal-pool order/addends vs target (judge masks them) - run on every match
- **side-by-side** `sbs.py NAME FILE.c [A B]`: full target | candidate listing
- **struct-diff** `mdiff.py NAME FILE.c P`: structural diff
- **asm-differ** `asmdiff.py`: live asm-differ view
- **stmt-perm** `stmtperm.py` (tag statements `/*P*/`), **rand-perm** `permrand.py`, **near-perm** `nearperm.py ROUND` (decl orders, no LLM), **permuter** `permute.py` (decomp-permuter; scores unreliable on TnJ)
- **asm-only** `auto_match.ASM_ONLY` + whole `asm` function (allowed only for swp/swi/mrs/mcr/clz...); write `bl` even to Thumb callees
- **profile-pad** `profpad.py` (HoM `-profile` padding), **ld-align** `ld_align.py` (Thumb BIOS stubs at addr%4==2), **lcf-const** `config/<v>/arm9/lcf_symbols.txt` (SDK_IRQ_STACKSIZE...)
- **scene-fix** `scenefix.py` (HoM per-overlay scene state machines), **vcall** `vcall.py`, **ptr-scale** `ptrscale.py`, **hw-volatile** `hwvol.py`, **bitflag** `bitflag.py`/`bittail.py`, **fnptr** `fnptr.py`, **struct-copy** `structcopy.py`, **sw-default** `swdefault.py`, **call-arg** `callarg.py`, **near-fix** `nearfix.py`

## Prototypes (studio/gametools/prototypes) - see prototypes/README.md
- **proto:profextra** `profextra.py` - the extra-profile list as one auto pass (agents cannot run `hunt.py try`)
- **proto:declperm** / **decl-order** `declperm.py` - random local-declaration orders (callee-saved register order)
- **proto:cmutate** `cmutate.py` - **int-vs-long**, **neg-mul**, **chain-order**, **nested-assign**
- **proto:asmconv** / **asm-function** `asmconv.py` - whole-function asm for asm-only instructions
- **shape-score** `mscore.py` - variant ranking with registers masked (big functions)
- **region-diff** `regions.py` - mismatches per region of the target
- **sched-scan** `schedscan.py` - exact instruction window across thousands of variants (scheduling puzzles)

## Manual techniques (no script yet - turn into a prototype when reused)
Rewriting
- **asm-rewrite** write the function fresh from `workbench.py info NAME` asm when the m2c draft has the wrong size or does not compile (TnJ: 8/12 fresh writes matched, old drafts useless)
- **typed-struct** replace pointer+offset by a typed struct / struct array (fields, sizes from the asm)
- **sdk-inline** SDK-style `static inline` helpers (G3_Translate, G3_Scale, G3_LightVector, GX visible plane, IME enable/restore, FX_Mul, register writes); `#define` is refused
- **hidden-arg** a value set in r1-r3 before a call and otherwise unused = an extra argument m2c dropped
- **varargs** `push {r0-r3}` prologue = `(a, b, c, d, ...)`; or a `volatile` param read late (Rayman func_02028024)
- **callee-type** declare the callee with its real return type (u8 return avoids `and 0xff`; s32 callee in s16 caller gives lsl/asr)
- **symbol-names** use symbols.txt names for every call (judge masks bl targets; wrong name = link fails, dropped silently)
Order / registers
- **decl-order** local declaration order (first declared = higher register on HoM; TnJ: decl order = r4,r5,...) - not for params
- **stmt-order** reorder independent statements / stores (stores keep source order when they may alias)
- **reuse-var** reuse a dead variable / the param itself as loop counter or running pointer (`font = g + 2; *font++`)
- **chain-order** `b = a = 0` vs `a = b = 0` (pool order); **nested-assign** `b = (a = 0) - 1` (no const fold, distinct regs)
- **call-temp** one call per statement / temp for the call result (`s32 t = f(); return t + a;`); args of calls in one expression are all evaluated first
- **accumulate** `ret = A; ret += B;` keeps term order (mwcc reorders `a + b + c` with s64 divisions)
- **inline-addr** pass `L.buf` / `&L` inline instead of a pointer local (changes the prologue)
Types
- **int-vs-long** `int` instead of `s32` (= long in m2c.h) for indexes
- **u8-ptr** byte pointer arithmetic `(u8 *)p + K` (m2c scaled offsets), **extern-type** extern u8 vs s32
- **u32-local** u32 locals for ldrb values compared with bhi/bls; `return (u8)r` for the final `and 0xff`
- **enum-local** an enum-typed local is NOT constant folded (func_0203e12c)
- **neg-mul** `x *= -1` vs `-x` (smulbb), `(s16)*(s16)` product for smulbb, `(long long)a*b + 0x800 >> 12` for smull fixed point
- **double-order** `t = itod(x); t *= 1.8` puts the constant second in _dmul
- **bitfield** `u32 f:1` structs for lsl/lsr/bic/orr; bool flag `long & 0xFF` for `tst #0xff`
- **volatile** `volatile` on HW registers / one table (moves a load); non-volatile 64-bit register write = one stm
Data / addresses
- **dup-pool-prev-array** same symbol twice in the pool = address one past the PREVIOUS array (`&data_021a7224[4]`), only where the address is used whole
- **extern-split** separate extern arrays at struct+offset let mwcc hoist loads (no alias); objdiff accepts sym+off relocs
- **block-init** `V3 z = {0,0,0};` initializer (not assignments) = stores through a pointer reg; initialized locals use reverse-declaration stack order
- **stack-order** stack arrays are laid out in reverse declaration order; a 4-long array forces padding
- **runtime-names** name runtime helpers as mwcc emits them (`_ll_udiv`, `_ull_mod`, `_ll_sdiv`, `_ll_mod`, `_dneq`...) then plain `/`, `%`
Control flow
- **loop-form** `for`/`do while`/`if (i < end) do {} while` instead of goto loops; unsigned `n > 0` guard only as a for loop
- **if-invert** invert a branch / early return / `if (f()) break; continue;` vs `if (!f()) continue; break;`
- **switch-form** switch vs if/else; `default:` last; case order = body order; explicit `case 4:` before default -> jump table
- **dead-bx-merge** a 4-byte `bx lr` after a no-return function split by dsd: merge it into the previous symbol
Section / build
- **init-section** `#pragma define_section INIT ".init"` + `__declspec(INIT)` for `__sinit_*` only
- **link-time-const** relocs `kind:link_time_const(X)` -> `extern T X[];`

## Known dead ends (do not retry without a new idea)
- 5th stack-argument register order for calls to func_0203d498 (TnJ func_02016a94, 020116d8, 0200d854, 02028714)
- "param kept in r0 + copy" (TnJ func_02013198, func_02031cf0): copies/u32/const/inline all coalesce
- func_0203075c: sub hoisted above str only with a longer chain (~7500 variants + permuter)
- vsweep on TnJ: 2.0/sp1p5 is the only compiler; leftovers are source-level
- `_b` alias symbols in symbols.txt (C-defined bss): use dup-pool-prev-array instead
