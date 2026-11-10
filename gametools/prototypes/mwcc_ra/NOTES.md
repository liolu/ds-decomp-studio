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

## Pcode (session 2, 2026-11-10)
- Blocks: list at DAT_0063a828 (next at +0, index +0x1c, pcode list head +0x18 = LAST instruction, chained backwards
  through +4). Pcode: flags +0x0c (0x20002 / 0x40004 memory classes, 0x80/0x200/0x400/0x800 special deps), opcode
  u16 at +0x28 (0x76 bl, 0xb2 mov imm, 0xf3 sub imm, 0xf1 strh, 0xee str, 0x80 ldr literal), +0x2b addressing kind,
  operand count +0x2c, operands of 0xe bytes from +0x2e: [0] kind (0 = register, 1 = ?, 2.. = immediates/symbols),
  [1] class, [2] u16 flags (1 = use, 2 = def), [4] s16 vreg/register number, [6]/[10] s32 values.
- `pcdump.py FILE.c FUNC` (Frida) prints the pcode at the allocator's entry (hook FUN_00513ca0): this is ALREADY the
  pre-RA scheduled order (mwcc schedules before allocation, and again after).
- Scheduler: FUN_004ff1f0 (Scheduler.c) builds the dependency DAG per instruction (register defs/uses via
  FUN_004fefe0, memory classes by the pcode flags, special resources DAT_0061668e..9e); FUN_004f5bd0 (SchedulerARM9.c)
  = latency per opcode (ldr/str with register offset kinds 4/6/8/10 +1, mul 3-4, ldm/stm by count, reg 15 operand = 3).

## func_0203075c explained
Target: allocation of the `sel`-first draft (0 in r3, -1 in r2) + `strh [#2]` before `strh [#0]` + `mov #1` after both.
Writing `prevSel` first gives the right strh order but the PRE-RA scheduler then puts `mov v19 = 1` between the two
strh, so v19 interferes with v17 (-1) and every register shifts (0 -> r2, -1 -> r3, 1 -> r2). What source puts the
`1` after both strh with prevSel first is a scheduler-priority question: next step = dump the DAG and the ready-list
choices (hook FUN_004ff1f0 callers / the list scheduler loop) and compare both orders.

## List scheduler (session 3, 2026-11-10)
FUN_004ff750 = per block: one DAG node per pcode (FUN_004fedb0, 0x1c bytes: +0 ready-list next, +8 successor edges
{next, node, u16 latency}, +0xc pcode, +0x10 latency, +0x12 kind, +0x14 earliest cycle, +0x16 deadline,
+0x18 height, +0x1a unscheduled preds), deps by FUN_004ff1f0, deadlines FUN_004ff530, then each cycle
FUN_004ff590 picks among ready nodes (preds 0, earliest <= cycle, resource ok):
  1. urgent (deadline <= cycle) beats non-urgent; 2. more successors it unblocks (FUN_004ff560: succs with 1 pred);
  3. greater height; 4. smaller kind (FUN_004febf0: 0 move, 1 no reg def, 2 def+use, 3 flag 2, 4 def only);
  5. list order = program order.
Memory deps: loads FUN_004ff0e0 vs stores, stores FUN_004ff140 vs loads+stores, edge only if FUN_00559ba0 ->
FUN_00559a20 (Alias.c: alias objects at pcode+0x1c, kind +0x30: 0 exact (same object), 1/4 FUN_00444c10 +
FUN_00559790, 2 = set membership). Call = barrier for everything (flag 0x100108 -> FUN_004fef80).
`schedtrace.py FILE.c FUNC [--pass 1] [--dag]` prints candidates + pick per cycle and the DAG with latencies.

func_0203075c: with prevSel written first, the target order needs: the `result = 0` store NOT dependent on the
prevSel store (else it ties with `sub` and wins on kind), while the final `flag = 1` store DOES depend on the sel
store (else `mov 1` jumps between the two strh). Accessor form never changes alias objects (1024 combos = 3
classes); declared TYPES do partly (340 combos, best 2). Next: FUN_00444c10 / alias object creation rules.
