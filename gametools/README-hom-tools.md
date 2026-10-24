Reusable matching helpers (run from a project dir, e.g. projets/heroes-of-mana):
- batch_try.py OUT [--ov|--main --min --max -j N --limit N --submit] : judge drafts of unmatched small ARM functions (main or overlays), resumable; then `workbench.py submit-many OUT` submits all exact matches with one build
- j.py NAME FILE.c [profiles] [--submit]   : compact judge (only mismatching lines), optional submit
- asm.py NAME                              : asm + calls/protos/data of a function
- permdecl.py NAME FILE.c [--submit]       : permute local declaration order, judge each
- variants.py NAME BASE.c 'old=>new@@old2=>new2' ... : try textual variants (\n = newline), prints diff count
- permrand.py NAME FILE.c [--n 300 -j 6 --profile P]  : RANDOM permutations of the local declaration lines (7+ locals; permdecl only tries the first 800 in lexicographic order), scores diffs + 1000*size gap -> FILE.best.c
- mdiff.py NAME FILE.c [profile]            : STRUCTURAL diff (difflib on mnemonics of the full listings, via WB_FULL=1) - shows real insertions/deletions even when the sizes differ (the index-aligned `diff` of judge is useless then)
- stmtperm.py NAME FILE.c [--profile P -j N]   : permute the statement lines tagged with a trailing `/*P*/` (<= 7 lines), judge every order -> FILE.best.c (fixes store/load scheduling, e.g. MBi_CheckWmErrcode 5 -> 3 diffs)
- optsweep.py NAME FILE.c [versions...]       : judge FILE.c at every -O0..-O4,p/s of 2.0/sp1p5 and 1.2/sp2p3 (profile string "2.0/sp1p5 -O2,p" works in judge/submit). Loops with `b cond` entry + mul/mla (no strength reduction) are -O2 files (SND_CommandInit 53 -> 1 diff).
- donor_match.py: DONOR_DUMP=dir python tools/donor_match.py --dry-run --names a,b  writes the donor C that compiled but did not match (status near/size/...) to dir/NAME.STATUS.c (ntrtwl dumps are skipped on purpose: leaked) = ready-made starting point (needs `__attribute__` removed for the fake-match gate, types/offsets fixed by hand)
- swdefault.py SRC OUT : moves m2c's leading `default:` to the end of the switch (jump-table layout) - fixed 22 near overlay funcs at once (families of per-overlay init funcs); then fixrun.py + submit-many
- spsize.py SRC OUT : `M2C_UNK spN;` address-taken stack buffers -> `u8 spN[SIZE]` (tries 8..128), judges, keeps matches (frame size fixes)
- bitflag.py SRC OUT / bittail.py SRC OUT : family rewrites with bitfield structs (display-init POWCNT block; scene-exit tail `bit test, clear, call(&sym, word, bit)`), 22 matches at once. Pattern: m2c `(u32)(M2C_FIELD(&sym, s32 *, OFF) << S) >> 0x1F` = bitfield read; write operand order `(bit << 15) | (reg & ~0x8000)`
- modfix.py SRC OUT : m2c's signed `y % K` expansion -> `y % K` (+ s32 vars): 19 matches. hwvol.py SRC OUT : volatile on 0x04xxxxxx register accesses (stops merged/dropped RMW).
- PROFILE 1.2/sp3 (AUTO_EXTRA_PROFILES=1.2/sp3 for workbench/fixrun/submit-many/commit): produces `stmfd {lr}; sub sp,#4` instead of `push {r3,lr}`: re-judging all near/size drafts with it gave +106 at once. ALWAYS include it in sweeps.
- **fj.py DIR [-j 12] [--ov|--main] [--min A --max B] [names]** = FAST judge, REPLACES batch_try.py + fixrun.py (same results.json, so `workbench.py submit-many DIR` works). In-process workers, no `workbench info` (that call alone cost ~40 s per overlay function in batch_try: 24 funcs 860 s -> 4 s), a looping compiler (15 s timeout) is not retried on the other profiles. Verified identical statuses/diffs vs batch_try on 94 drafts. Needs a DIR with .c files OR --ov/--main (then writes the m2c drafts). Run it with names or a populated DIR: an EMPTY dir without --ov/--main sweeps the whole project.
- fixall.sh SRC WORK : all mechanical fixers (nearfix swdefault vcall callarg osfree modfix spsize structcopy fnptr hwvol bitflag bittail) + one fj.py judge of the merged result.
- WAITING: never poll with `until` loops on a task .output file (written only at the end) or `tasklist|grep` (broken in Git Bash); run the long command with run_in_background and wait for its completion notification. Run long Python jobs from PowerShell when Git Bash process creation gets slow. Long `( ... &)` subshells are killed when the tool call ends.
- tryc.py NAME 'C variant 1' 'C variant 2' ... [-p PROFILE] : judge inline C variants (m2c.h auto-included), stops at first MATCH, else prints best diff. Fast way to test hand ideas.
- fam.py SRC OUT : small-family rewrites (2-word struct copy `*a=*(P*)(b+K)`, post-increment getter `v=*p++`) -> 7 at once (session 10).
- vcall.py env VX=1 : forward arg1 to the virtual call (`(*(R(**)(void*,s32))(vt+K))(this,arg1)`: r1 live => fn ptr lands in r2) +13; VY=1 : forward arg0 first, this second (fn(arg0, obj)).
- ptrscale.py SRC OUT : `M2C_UNK *p; p += 0x5C` / `(p + N)` scaled by pointee size in m2c drafts -> (u8 *) byte arithmetic (+12).

## -profile records (.data padding) and the verify exception
Overlay functions built with mwccarm `-profile` own a `.data` record (their name, len+1 bytes, byte-aligned) that the
original linker padded to 4 bytes. `tools/profpad.py` adds `end4` (padded end, only where the ROM padding is zero) to
`build/profnames.json`; workbench delinks the record as `[start, end4)` (this links byte-identically; an unpadded
range leaves a 1-3 byte gap object that shifts everything after it). objdiff then sees 15 bytes against 16 and reports
the `.data` section at 2n/(n+m) (96.77% for 15/16). `match.py verify` (PROFILE PADDING) accepts exactly that value for
units of a profile record and nothing else: same size, same fuzzy value => every record byte equal, only the padding
missing; code sections must still be 100% and the ROM byte-identical. Pipeline: `profpad.py` -> `profhook.py build/drafts D1`
-> `profmap.py D1 D2` -> `AUTO_EXTRA_PROFILES='1.2/sp3 -profile,2.0/sp1p5 -profile' fj.py D2 --ov --max 20000` ->
`workbench.py submit-many D2` -> `commit`.

## Data (.data / .rodata / .bss) to C

Order: `datagap.py` (what is left and why) -> `fakeptr.py --apply` (false pointers dsd found in byte tables) ->
`symmerge.py --apply` (unaligned struct-field symbols folded into their object, relocs become `to:obj add:off`) ->
`bssgen.py` / `datagen.py` -> `profrec.py` (name records of unmatched -profile functions; released to the function
by auto_match.integrate, file removed at `workbench commit`) -> `tiegen.py gen`, ninja, `tiegen.py check` (twice) for
equal-size runs -> `datagap.py --name-nosym` + `datagen.py` for unreferenced data -> `match.py verify`.
mwcc facts: one element type per run; arrays get a section each (aligned 4 by the linker) but 1-2 byte scalars are
packed in one section (so tiegen writes scalars); const all-zero data stays in .rodata, non-const goes to .bss;
thumb function pointers are written `(u32)&f` (the linker sets bit 0).
When `ninja` fails its symbol check after datagen/bssgen: `datashift.py` prints only the objects where the offset
CHANGES (root causes; the overlays start AFTER(ARM9), so a shifted main .bss moves them all). Seen on The Sims 2: an odd
3-byte symbol (neither scalar nor array = a field) -> `symmerge.py --min-size 3 --apply`; false pointers that symmerge
turned into `to:obj add:0x1` (0x0212_0001-like table entries) make objdiff report 9x% on a pointer-free table -> delete
those relocs.txt lines by hand.

## Agent rounds (N agents in a loop, then one push)

Run from the game dir (`projets/<game>/`), env.sh sourced. Agents get `AGENT-BRIEF-hom.md` + one list each.

- `agentdeal.py N PER [--status compile,size --min-size B --max-size B]` : deals the hunt queue into
  build/hunt/agentlists/agentI.txt, remembers handed-out names in build/hunt/assigned.json.
- `agentrefill.sh ROUND [PER]` : one fresh list for a new agent slot (build/hunt/ROUND/listK.txt + aK/), filled from
  the size bands 40-170, 171-300, 301-500, 501-800, 801-1200, 1201-2000 in order. Call it each time an agent ends.
- `agentnear.py ROUND [--max-diffs 9] [--per 15] [--lists N]` : hands out the near misses of every past round
  (build/hunt/*/all/results.json), with the best file copied into aK/ as the starting point.
- `agentrelease.py ROUND` : names handed out but never tried (no aK/NAME.c: rate limit, early stop) go back to the pool.
- `agentround.py ROUND` : collect aK/*.c, symfix, judge with every profile (fj.py, capped), submit-many + main submits.
- `roundpush.sh ROUND` : agentround + `workbench commit` + trailer + configure + progress report gz + git push,
  log in ROUND/push.log.

Agent prompt that works: "one pass, max 4 judges per function, answer when the list is done, stop at HH:55". Never
"keep going until HH:00": agents then grind the same functions for an hour. Yields on Heroes of Mana: compile/size
40-170 B ~75%, 170-300 ~65%, 300-500 ~55%, 500-800 ~40%, 800-1200 ~10%; near misses 1-9 diffs ~25%, 10-20 ~15%.
