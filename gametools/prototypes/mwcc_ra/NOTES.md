# mwccarm 2.0/sp1p5 register allocator (reverse engineered 2026-11-10)

Ghidra project: `mwcc-re/proj` (PE loader forced: the dsd-ghidra extension crashes on .exe). Run from the `W:` subst
(`subst W: "D:\... logiciel\decomp\decomp ds"`: analyzeHeadless.bat breaks on the real path). Scripts: DumpAlloc.py
(functions referencing the source-file assert strings), DumpAddrs.py (MWCC_ADDRS=a,b,c). Decompiled C in out/.

Release build: the dump pragmas (dumpir, dumpphases, debug_listing...) exist but print nothing.

## Modules (assert strings)
- Coloring.c: FUN_00513ca0 driver, FUN_00513590 simplify, FUN_00513930 select, FUN_00513b00 (after success)
- InterferenceGraph.c: FUN_0050a4a0, FUN_0050acf0; build = FUN_0050b5e0
- Registers.c FUN_004fe320.. (FUN_004fe410 = available-register mask, FUN_004fe4c0 = next callee-saved register,
  FUN_004fe3d0 = number of colors K)
- xSpill.c: FUN_00592c50 = insert spill code; FUN_00592340 = spill costs
- Scheduler.c FUN_004ff1f0, SchedulerARM9.c FUN_004f5bd0, LiveRegisters.c FUN_004f7ff0

## Node (virtual register) = 0x36 bytes at DAT_0063ba40 + idx*0x36
+0x00 next (stack link) | +0x0c spill cost (int) | +0x28 s16 index | +0x2a s16 color (-1 = none) |
+0x2c u16 flags (2 = removed, 4 = ?, 0x80/0x400 = cost override, 0x200 = register PAIR (64-bit), 1 = spilled) |
+0x2e s16 degree | +0x32 adjacency tree (nodes: +4/+8 children, +0xc/+0xe the two endpoints)
Class 0 only (loop `local_9 < 1`). First non-precolored node DAT_0063a2bc[class], end DAT_0063d00c[class].

## Algorithm (Chaitin/Briggs, optimistic)
driver: repeat { build graph; stack = simplify(); if select(stack) ok -> done else insert spill code, retry (<= 10) }
simplify: pass over nodes in INDEX order; node with degree < K -> removed (neighbors' degree -1, or -2 for pairs),
  pushed (stack head = last pushed); repeat passes while something was removed. Blocked: among the rest pick the
  minimal cost/degree (flag 0x80/0x400 -> constants), push it optimistically, continue.
select: walk the stack from the head (= reverse removal order). available = allowed-mask minus neighbors' colors.
  Lowest register NUMBER first (bit 0 = r0...). Pairs: even register with r+1. If no color: FUN_004fe4c0 opens the next
  callee-saved register from the allocation list (r4, r5, ...) into the mask and the SAME node is retried; only when the
  list is exhausted is the node marked spilled (flag 1) -> spill code, rebuild.

## Consequences for matching
- A temp's register = lowest free number after its higher-on-stack neighbours took theirs. Index order = creation
  order of virtual registers in code generation (source order of expressions, temps, CSE results).
- Swapping two scratch registers between draft and target = different vreg creation order or one extra/missing
  interference edge (a value live a bit longer/shorter), not the local expression form.
- Callee-saved registers are opened lazily in list order -> r4 is the first value that could not fit in r0-r3/ip/lr.

## Tools (this folder)
- `radump.py FILE.c [--func F] [--map]` (needs `pip install frida`): runs the REAL mwccarm 2.0/sp1p5 under Frida,
  dumps every coloring attempt (vregs, colour, flags, cost, neighbours, select order). `--map` annotates the listing
  of F with the vregs behind each instruction (forces each vreg to a marker register in turn). Addresses are for
  2.0/sp1p5 only. Run from `decomp ds/mwcc-re` style folder: the C file's folder is the compiler's cwd.
- IR pass trace: a copy of mwccarm.exe with the byte at file offset 0xf40d8 set to 1 (`DAT_0064641c` dump flag,
  init in FUN_004f4cc0) writes `<file>.log` next to the source (pass names; full IR dumps also need DAT_0063d6fa).
- Ghidra scripts: DumpAlloc.py, DumpAddrs.py (MWCC_ADDRS), Xrefs.py, FindStr.py (MWCC_STR).

## First results (TnJ 2026-11-10)
- func_0203075c: allocation already identical to the target (v16 r3 = 0, v17 r2 = -1, bases r1/r0): the 2 diffs are
  the SCHEDULER's order of two strh -> next target = Scheduler.c FUN_004ff1f0 / SchedulerARM9.c FUN_004f5bd0.
- func_0200c138: in the last print block the pool address vreg interferes with precoloured r0 (r0 live during the
  address computation in the pre-schedule order), so it cannot get r0 -> r2/r1 instead of the target's r1/r0.
  Putting ded8()/the address in locals does not change it: needs the pre-schedule pcode order (next tool).
