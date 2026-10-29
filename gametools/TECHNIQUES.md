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
- **typed-struct** `structxfer.py list|sweep [--min 0.6]`: techtag `try:typed-struct` targets get the C file of a matched member of their shape/skeleton family (any game, written with typed structs), calls/pool symbols renamed by position, 2nd variant with differing immediates remapped (offsets, pad sizes); proto_run too
- **siblings** `hunt.py sibs NAME`, `sibmatch.py`, `clone_match.py`: transplant a match to same-shape functions
- **donor** `donor_match.py`: reuse C from external decomps (donors.py index)
- **missdb-replay** `missdb.py replay`: every recorded miss replayed by fingerprint on all games
- **tech-tags** `techtag.py build|show|find|todo|stats` (Studio tab "Tags", job techtag): every function of every game tagged with its families (same shape / same skeleton across games), asm needs (feat:), techniques seen in matched C (tech:) and techniques to try (try:) from its matched relatives; `techtag.py todo GAME` = best hint first
- **variant-batch** `judgemany.py NAME files...` (was TnJ jm.py): judge many hand variants in one process, ~1 s each
- **pool-check** `relcheck.py NAME FILE.c [P]`: literal-pool order/addends vs target (judge masks them) - run on every match
- **side-by-side** `sbs.py NAME FILE.c [A B]`: full target | candidate listing
- **struct-diff** `mdiff.py NAME FILE.c P`: structural diff
- **asm-differ** `asmdiff.py`: live asm-differ view
- **stmt-perm** `stmtperm.py` (tag statements `/*P*/`), **rand-perm** `permrand.py`, **near-perm** `nearperm.py ROUND` (decl orders, no LLM), **permuter** `permute.py` (decomp-permuter; scores unreliable on TnJ)
- **asm-only** `auto_match.ASM_ONLY` + whole `asm` function (allowed only for swp/swi/mrs/mcr/clz..., or, in TnJ, for SDK/MSL functions a public decomp proves were `asm`: cite it in `// ASM:`); write `bl` even to Thumb callees
- **profile-pad** `profpad.py` (HoM `-profile` padding), **ld-align** `ld_align.py` (Thumb BIOS stubs at addr%4==2), **lcf-const** `config/<v>/arm9/lcf_symbols.txt` (SDK_IRQ_STACKSIZE...)
- **scene-fix** `scenefix.py` (HoM per-overlay scene state machines), **vcall** `vcall.py`, **ptr-scale** `ptrscale.py`, **hw-volatile** `hwvol.py`, **bitflag** `bitflag.py`/`bittail.py`, **fnptr** `fnptr.py`, **struct-copy** `structcopy.py`, **sw-default** `swdefault.py`, **call-arg** `callarg.py`, **near-fix** `nearfix.py`

## Prototypes (studio/gametools/prototypes) - see prototypes/README.md
- **proto:profextra** `profextra.py` - the extra-profile list as one auto pass (agents cannot run `hunt.py try`)
- **proto:declperm** / **decl-order** `declperm.py` - random local-declaration orders (callee-saved register order)
- **proto:declclimb** / **decl-climb** `declclimb.py` - hill climb on declaration order (move one line per step), continues where random declperm stalls (TnJ func_01ff99e8 39 -> 21)
- **proto:declsubset** / **decl-subset** `declsubset.py` - every order of a few named locals (<= 7), others fixed: wrong spill slots / swapped regs (TnJ func_01ff99e8 21 -> 6)
- **proto:donorpp** / **donor-preprocess** `donorpp.py` - preprocess a real SDK/MSL donor with its headers, keep one function, rename to the game's symbols; also try every 2.0 compiler build (TnJ MSL/OS printf = 2.0/sp1p2). 7 big TnJ functions matched (s31)
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
- **use-count** a local's register depends on how many statements use it: assign the same variable in every test (`dd = dot - d - r; if (dd > 0)` x3 instead of only the last) gave TnJ func_01ff8e94 the target registers (74 -> 26)
- **swap-temps** pointer/value swaps: `t = a1; pe = e1; ...` all temps first, then all `x1 = x0`, then all `x0 = t` (distinct temp regs), and the order of the groups inside each line = instruction order (TnJ func_01ff99e8 sort of 3 axes)
- **temp-split** `w = d2 - d6; w = FX_Div(d2, w);` instead of `FX_Div(d2, d2 - d6)` keeps the value in r0 (TnJ func_01ff8ac4, last 7 diffs)
- **goto-loop** search loop `b cond` (not rotated, no pre-check): `j = 0; goto check; next: if (..) goto done; j++; check: if (j < n) goto next; done:` (TnJ func_01ff9518)
- **donor-shape** take the C shape of a public donor of a similar SDK function (MTX_Concat43 locals xa/ya/za, xb/yb/zb reused across rows) -> TnJ func_01ff87b4 matched
- **cross-branch** an asm-only function (clz...) that branches INTO another function with no relocation (TnJ _fsub -> _fadd+0xc, _dsub -> _dadd+0x10): add `NAME kind:label(arm) addr:X` to symbols.txt + `from:A kind:arm_branch to:X` to relocs.txt, declare `void NAME(void);` before the asm function and branch to it; compute X from the ROM word (the disassembly offset is NOT pc+8-relative); objdiff needs the patched dsd (dsd-dsi.exe, keeps the bmi condition of arm_branch relocs)
- **static-anchor** a duplicated pool entry for the same address, or `[base, #32]` loads of a neighbour object = mwcc addressing FILE STATICS from one anchor: define the tables as `static const` in the C file (try the declaration orders), let the file own their .rodata/.bss range, rename the symbols to the static names with `local` (TnJ __ieee754_exp)
- **whole-file-ipa** an SDK function stuck on load scheduling / pool order next to file statics: rebuild the WHOLE original file (every function in address order + its statics in definition order) at `2.0/sp1p5 -O4,p -lang c99 -ipa file -inline on,noauto`, compare it as one range with `prototypes/rangecmp.py`, then one delinks entry (.text + .bss) replaces the split files and the .bss blob; statics = `local` symbols with sizes, relocs into an array -> `to:ARRAY add:OFF`. A matched donor file (DQIV) is the fastest source. TnJ SND_RecvCommandReply (snd_command.c, 16 functions, s36)
- **runtime-asm-split** hand-written runtime (_ll_mod/_ll_udiv/_u32_div_f/_dadd/_fadd/_ddiv, proven asm: DQIV libs/Runtime/src/*.s, pokediamond RUNTIME_*.s) whose entries branch into each other: one asm function per entry point, contiguous in source order (`prototypes/split_asm.py`, AWDS ll_sdiv.c/ll_udiv.c/u32_div_f.c CC0 reusable as is); split the symbol in symbols.txt + arm_branch relocs; an inline byte table = `dcd` words (dsd-dsi.exe now marks inline tables $d so objdiff agrees). TnJ s36: +6 routines
- **param-reuse** a load landing in the register of a parameter copy (`ldr r4, [r3, r4, lsl #2]` with r4 = idx) = the original reassigned the parameter (`idx = tab[idx];`), not a new local. `prototypes/varmerge.py` merges every local into every param/local. TnJ func_0203cd5c, func_0203cdd0 (s36)
- **hidden-return** a `void` draft whose target leaves r0 = the search result on the early exit (`bl find; cmp r0,#0; popge`) and r0 = the new slot index on the other path really returns it: `i = find(); if (i < 0) {...; i = count; count = i + 1;} return i;`. TnJ func_02032598, func_02033a2c (s36)
- **local-static** an SDK `if (flag) return; flag = TRUE;` whose store is delayed / whose constant lands in a callee-saved reg: the flag is a FUNCTION-LOCAL `static` (mwcc knows nothing else sees it). The file must own the flag's .bss word: symbols.txt `NAME$N kind:bss(size=4) addr:X local` (mwcc names it NAME$N), shrink the neighbouring .bss blob. TnJ OS_InitLock (s36)
- **shape-first** `build/hunt/s36/msbs.py` (register-blind diff) before anything: a few shape lines = a real source error (TnJ func_02006178: two bitfield names swapped, then varmerge+cmutate+declperm climb 49 -> 0)
- **callee-types** declare every callee with its REAL matched signature (src/ definition), above all the return type: a `short` return kept in an s16 local turns `mla` into `smlabb` (TnJ func_02037bb8: func_02037a38 returns short, pos s16 -> match). Caller side: `prototypes/callsig.py` reads u8/u16 params and used returns from the callers' code (func_02012e28 k is u16; B-spline helpers (u8, u16, s32) -> exact size)
- **exceptix** a data blob at the end of .text = (addr, size, action) triples of MSL functions + 8-byte action records
  before them: the C++ exception index table the linker builds (EXCEPTION command). mwcc emits one `.exceptix`
  entry per (non-leaf) function and `@ET@func` records in `.exception` when the file is compiled with
  `-Cpp_exceptions on` -- even for C, code unchanged. Recipe: delinks header `.exception`/`.exceptix` sections,
  per-file `.exceptix` (12 B per entry) + `.exception` (8 B per record) ranges, `-Cpp_exceptions on` in
  compilers.txt for those files, `@ET@func kind:data(byte[5]) ... local` symbols for the records.
  `prototypes/exceptix.py START END` checks every file first (entries + text unchanged). TnJ data_02063a48 (55 files).
- **literal-owner** a donor's string literals/zero words sitting at an old data symbol: give the C file that .rodata/.data range in delinks.txt, delete the src/data file, replace the symbol by a sized local `@name kind:data(byte[N]) ... local` (dsd check matches any @ names), keep padding inside the range (TnJ __strtold, __pformatter)
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
