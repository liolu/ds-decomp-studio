"""loops.py - c2asm part 2: find the loop and switch idioms of patterns.c in a game's functions.

The plain search of c2asm.py never finds loops: in real code the loop entry differs (test before the loop,
register copies, other scheduling). Here only the loop BODY is compared: from the target of a backward branch to
the branch itself, register copies (`mov R,R`) dropped, constants kept loose (c2asm.shape).
  same order : the body instructions in the same order
  same set   : the same instructions in any order (scheduling)
Switches: a jump table (`cmp R,#N` + `addls pc,pc,R,lsl #2`) is found with its case count; a switch whose every
case is `mov R,#c` then a return/branch is a lookup table (C: switch returning constants, or a const array).

    cd projets/<game>
    python <studio>/gametools/prototypes/c2asm/loops.py [--all] [--sweep] [--cc auto]
Writes build/c2asm/loops.md (+ loops_all.md with --all) and loops.json.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import c2asm  # noqa: E402

POOLWORD = re.compile(r'^(\.L_\w+):\s*\.word\s+(\S+)', re.M)
POOLLDR = re.compile(r'(ldr\w*\s+\w+),\s*(\.L_\w+)$')
NUM = re.compile(r'0x[0-9a-fA-F]+|\d+')
BR = re.compile(r'^b(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?$')


def body_key(instrs, exact=False):
    out = []
    for x in instrs:
        n = c2asm.norm(x)
        if not n or n == 'mov R,R':
            continue
        out.append(n if exact else c2asm.shape(n))
    return tuple(out)


def loose(k):
    # bound in a register or a constant, either compare: same loop shape
    return tuple(sorted(re.sub(r'^cmp .*', 'cmp', x) for x in k))


def pattern_streams(funcs):
    """pattern name -> list of (addr, raw text); branch operand is a hex address."""
    return {name[2:] if name.startswith('p_') else name: list(zip(c2asm.ADDRS.get(name, []), raw))
            for name, raw in funcs.items()}


def loops_of(stream, target_of):
    """stream: list of raw instructions; target_of(i) -> index the branch at i goes to, or None."""
    out = []
    for i, x in enumerate(stream):
        mn = x.split()[0] if x.split() else ''
        if not BR.match(mn):
            continue
        t = target_of(i)
        if t is not None and t <= i:
            out.append(stream[t:i + 1])
    return out


def pattern_loops(stream):
    addrs = [a for a, _ in stream]
    raw = [x for _, x in stream]

    def target_of(i):
        m = re.search(r'\s([0-9a-f]+)\s*<', raw[i])
        if not m:
            return None
        a = int(m.group(1), 16)
        return addrs.index(a) if a in addrs else None
    return loops_of(raw, target_of)


def switches_of(raw, target_of):
    """jump tables: (case count, [first instruction of each case])."""
    out = []
    for i, x in enumerate(raw):
        if not re.match(r'\s*addls\s+pc,\s*pc', x):
            continue
        m = re.search(r'#(0x[0-9a-f]+|\d+)', raw[i - 1]) if i else None
        if not m:
            continue
        n = int(m.group(1), 0) + 1
        firsts = []
        for k in range(i + 2, min(len(raw), i + 2 + n)):
            t = target_of(k)
            firsts.append(raw[t].strip() if t is not None and t < len(raw) else '?')
        out.append((n, firsts))
    return out


def target_streams(game, every):
    ver = next(p for p in (game / 'build').iterdir() if (p / 'report.json').exists() and (p / 'asm').is_dir())
    rep = json.loads((ver / 'report.json').read_text())
    todo = {f['name'] for u in rep['units'] for f in u.get('functions', [])
            if every or f.get('fuzzy_match_percent', 0) < 100}
    out = {}
    for s in (ver / 'asm').rglob('*.s'):
        cur, raw, labels = None, [], {}
        text = s.read_text(encoding='utf-8', errors='replace')
        pools = {m.group(1): m.group(2) for m in POOLWORD.finditer(text)}
        for line in text.splitlines():
            m = re.match(r'\s*(arm|thumb)_func_start\s+(\w+)', line)
            if m:
                cur, raw, labels = (m.group(2) if m.group(2) in todo else None), [], {}
                continue
            if re.match(r'\s*(arm|thumb)_func_end', line):
                if cur:
                    out[cur] = (raw, labels)
                cur = None
                continue
            if not cur:
                continue
            m = re.match(r'^(\.L_\w+|\w+):', line)
            if m:
                labels[m.group(1)] = len(raw)
                continue
            if line.startswith('    ') and not line.strip().startswith('.'):
                x = line.split(';')[0].strip()
                q = POOLLDR.match(x)
                if q and NUM.fullmatch(pools.get(q.group(2), '')):
                    x = f'{q.group(1)}, ={pools[q.group(2)]}'  # pool constant, as c2asm does
                raw.append(x)
    return todo, out


def label_target(raw, labels):
    def target_of(i):
        parts = raw[i].split()
        return labels.get(parts[-1]) if len(parts) > 1 else None
    return target_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cc', default='auto')
    ap.add_argument('--out', default='build/c2asm')
    ap.add_argument('--sweep', action='store_true', help='also the common flags of other games (c2asm.SWEEP)')
    ap.add_argument('--min-files', type=int, default=3)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--min', type=int, default=3, help='shortest loop body kept (instructions)')
    a = ap.parse_args()
    game = Path.cwd()
    outdir = game / a.out
    outdir.mkdir(parents=True, exist_ok=True)
    byprof, addrs = c2asm.all_profiles(game, a.cc, outdir, a.sweep, a.min_files)
    descs = c2asm.descriptions()

    # pattern loops and switches
    ploops, pswitch, kprof, pexact = {}, {}, {}, collections.defaultdict(dict)
    for prof, funcs in byprof.items():
      c2asm.ADDRS.clear()
      c2asm.ADDRS.update(addrs[prof])
      for name, st in pattern_streams(funcs).items():
        if name not in descs:
            continue
        for body in pattern_loops(st):
            k = body_key(body)
            ek = body_key(body, exact=True)
            if len(ek) >= a.min:
                pexact[name].setdefault(ek, prof)
            if len(k) >= a.min and k not in ploops.get(name, []):
                ploops.setdefault(name, []).append(k)
                kprof[(name, k)] = prof
        raw = [x for _, x in st]
        paddr = [ad for ad, _ in st]

        def tgt(i, raw=raw, addrs=paddr):
            m = re.search(r'\s([0-9a-f]+)\s*<', raw[i])
            return addrs.index(int(m.group(1), 16)) if m and int(m.group(1), 16) in addrs else None
        sw = switches_of(raw, tgt)
        if sw:
            pswitch[name] = sw

    todo, targets = target_streams(game, a.all)
    exactm = collections.defaultdict(list)
    order = collections.defaultdict(list)
    anyorder = collections.defaultdict(list)
    loosem = collections.defaultdict(list)
    hitprof = collections.defaultdict(collections.Counter)
    tswitch = []
    for fn, (raw, labels) in targets.items():
        tof = label_target(raw, labels)
        tbodies = loops_of(raw, tof)
        tloops = [body_key(b) for b in tbodies]
        texact = [body_key(b, exact=True) for b in tbodies]
        for name, eks in pexact.items():
            for ek, prof in eks.items():
                if ek in texact and fn not in exactm[name]:
                    exactm[name].append(fn)
                    hitprof[name][prof] += 1
        tsets = [tuple(sorted(k)) for k in tloops]
        tloose = [loose(k) for k in tloops]
        for name, keys in ploops.items():
            for k in keys:
                if fn in order[name] or fn in anyorder[name] or fn in loosem[name]:
                    continue
                if k in tloops:
                    order[name].append(fn)
                    if fn not in exactm[name]:
                        hitprof[name][kprof[(name, k)]] += 1
                elif tuple(sorted(k)) in tsets:
                    anyorder[name].append(fn)
                    hitprof[name][kprof[(name, k)]] += 1
                elif loose(k) in tloose:
                    loosem[name].append(fn)
        for n, firsts in switches_of(raw, tof):
            consts = [re.match(r'mov r\d+, #(0x[0-9a-f]+|\d+)$', f) for f in firsts]
            tswitch.append((fn, n, all(consts), [int(c.group(1), 0) if c else None for c in consts]))

    lines = [f'# c2asm loops ({game.name}, {len(targets)}/{len(todo)} functions read'
             + (', matched ones too' if a.all else ', unmatched only') + ')\n',
             '| idiom | loop body | exact (constants too) | same order | same set | loose | settings | '
             'example functions (exact!, order, ~set, ?loose) |',
             '|---|---|---|---|---|---|---|---|']
    for name in [n for n in descs if n in ploops]:
        keys = ploops[name]
        ex = ', '.join([f + '!' for f in exactm[name][:3]] + [f for f in order[name] if f not in exactm[name]][:3]
                       + [f + '~' for f in anyorder[name][:3]] + [f + '?' for f in loosem[name][:3]])
        lines.append(f'| {name} | `{" ; ".join(keys[0])}` | {len(exactm[name])} | {len(order[name])} '
                     f'| {len(anyorder[name])} '
                     f'| {len(loosem[name])} | '
                     + ', '.join(f'{p}:{c}' for p, c in hitprof[name].most_common()) + f' | {ex} |')
    lines.append('\n## switches (jump tables)\n')
    byn = collections.Counter(n for _, n, _, _ in tswitch)
    lut = [t for t in tswitch if t[2]]
    lines.append(f'{len(tswitch)} jump tables in {len({t[0] for t in tswitch})} functions; case counts: '
                 + ', '.join(f'{n}:{c}' for n, c in sorted(byn.items())))
    lines.append(f'\n{len(lut)} are lookup tables (every case `mov R,#c`): C = switch returning constants\n')
    for fn, n, _, vals in lut[:40]:
        lines.append(f'- {fn}: {n} cases -> {vals}')
    for name, sws in pswitch.items():
        for n, firsts in sws:
            same = [t[0] for t in tswitch if t[1] == n]
            lines.append(f'\npattern {name}: {n} cases; same case count in: {", ".join(same[:10]) or "none"}')
    suffix = '_all' if a.all else ''
    (outdir / f'loops{suffix}.md').write_text('\n'.join(lines), encoding='utf-8')
    (outdir / f'loops{suffix}.json').write_text(json.dumps(
        {'loops': {n: {'exact': exactm[n], 'order': order[n], 'set': anyorder[n], 'loose': loosem[n]} for n in ploops},
         'switches': [{'function': f, 'cases': n, 'lookup': l, 'values': v} for f, n, l, v in tswitch]},
        indent=1), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
