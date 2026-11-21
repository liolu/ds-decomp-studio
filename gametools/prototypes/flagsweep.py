"""flagsweep.py - every compiler option, one at a time (then in pairs), on top of each near miss's own profile.

    python ../../studio/gametools/prototypes/flagsweep.py                    # report (build/hunt/flagsweep/)
    python ../../studio/gametools/prototypes/flagsweep.py --pairs            # + pairs of the options that helped
    python ../../studio/gametools/prototypes/flagsweep.py --commit           # integrate the matches (commit_found)
    python ../../studio/gametools/prototypes/flagsweep.py --list             # the option deltas, nothing compiled
    python ../../studio/gametools/prototypes/flagsweep.py --effective        # only deltas that changed code in a game

Run from the project dir (projets/<game>). Drafts: build/auto/near (--src to change).

How: the base profile of each draft is the profile of its matched neighbours (profprior.predict, one TU = one set of
flags), else the game's most used profile. The deltas are every codegen option of `mwccarm -help all` (-inline,
-ipa, -opt no<pass>, -enum, -char, -str, -rostr, -constpool, -proc, -lang, -profile, -g, -O levels...) and every
`opt_*` / scheduling pragma read out of the compiler binary (`-flag X` / `-flag no-X`). One compiler call per
(base, delta, chunk) for all the drafts, like nearsweep. A delta that the compiler refuses (unknown in that version)
is skipped after a one-file probe.

Pass 2 (--pairs): for each draft, the deltas that brought it closer are combined two by two (and the best 3 together).

Why (2026-11-16): nearsweep only tries profiles somebody already wrote into a compilers.txt. Options never written
anywhere (`-opt nostrength`, `-inline deferred`, `-ipa file` on 1.2, `-flag no-opt_loop_invariants`...) were never
tried at all. Every delta's effect is written to ../../studio/gametools/prototypes/flagsweep_stats.json (per game):
deltas that match functions in several games belong in auto_match GLOBAL_PROFILES.

Outputs: build/hunt/flagsweep/results.json {name: {base, base_diffs, best, diffs}}, matches as
build/hunt/flagsweep/match/NAME.c (first line = auto_match compiler marker).
"""
import argparse
import collections
import itertools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GT))
sys.path.insert(0, str(GT / 'prototypes'))
_argv, sys.argv = sys.argv, sys.argv[:1]
import auto_match as am  # noqa: E402  (reads sys.argv at import)
sys.argv = _argv
import nearsweep  # noqa: E402
import profprior  # noqa: E402

STATS = GT / 'prototypes' / 'flagsweep_stats.json'
PROMOTED = GT / 'prototypes' / 'promoted_profiles.txt'  # read by auto_match (GLOBAL_PROFILES)
PROMOTE_GAMES, PROMOTE_MATCHES = 2, 5

# Command-line deltas (later flags override pc.BASE_FLAGS: -enum int -char signed -str noreuse -proc arm946e
# -inline noauto -lang=c -interworking)
CLI = [
    '-O0', '-O1,p', '-O2,p', '-O3,p', '-O4,s', '-O3,s', '-O2,s', '-O1,s',
    '-inline auto', '-inline off', '-inline on', '-inline deferred', '-inline all', '-inline auto,deferred',
    '-inline on,noauto', '-inline level=1', '-inline level=2', '-inline nobottomup', '-inline bottomup',
    '-ipa file', '-ipa function', '-ipa program',
    '-enum min', '-char unsigned', '-str reuse', '-str pool', '-str reuse,pool', '-rostr', '-constpool',
    '-noconstpool', '-nointerworking', '-proc arm7tdmi', '-proc v4t', '-proc v5te', '-proc v5t', '-proc arm9tdmi',
    '-proc generic', '-proc arm926ej', '-lang c99', '-lang c++', '-profile', '-g', '-sym on', '-for_scoping on',
    '-relax_pointers', '-gccext off', '-ansi strict', '-msext on', '-pic', '-pid',
]
# Measured on SimCity Creator (470 drafts): `-opt no<pass>` after -O4 changes nothing (use -flag no-opt_*), -schedule is
# refused by 2.0, `-flag thumb/profile/interworking` duplicate -thumb/-profile/-nointerworking.
SKIP_PRAGMA = {'-flag thumb', '-flag no-thumb', '-flag profile', '-flag no-profile', '-flag interworking',
               '-flag no-interworking'}
PRAGMA_EXTRA = ['peephole', 'scheduling', 'global_optimizer', 'optimize_for_size', 'auto_inline', 'inline_bottom_up',
                'dont_inline', 'readonly_strings', 'pool_strings', 'cats', 'opt_classresults', 'ARM_conform',
                'interworking', 'thumb', 'profile', 'dont_reuse_strings', 'const_strings', 'force_active',
                'opt_unroll_loops', 'opt_vectorize_loops']


def pragma_deltas(exe: Path) -> list[str]:
    import re
    b = exe.read_bytes()
    s = {m.decode() for m in re.findall(rb'[A-Za-z][A-Za-z0-9_]{3,48}(?=\x00)', b)}
    names = sorted(x for x in s if x.startswith('opt_') and not x.endswith(('_limit', '_count', '_mode', '_level')))
    names += [x for x in PRAGMA_EXTRA if x in s and x not in names]
    out = []
    for n in names:
        out += [d for d in (f'-flag no-{n}', f'-flag {n}') if d not in SKIP_PRAGMA]
    return out


_probe_cache = {}


def accepted(version: str, extra: str) -> bool:
    """Does this compiler build accept the options? (a refused option would make every draft 'fail')"""
    key = (version, extra)
    if key in _probe_cache:
        return _probe_cache[key]
    mwcc = am.MWCC_ROOT / version / 'mwccarm.exe'
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'p.c').write_text('int f(int a, int b) { return a * 3 + b; }\n')
        cmd = f'"{mwcc}" -O4,p {am.pc.BASE_FLAGS} {extra} -c p.c -o p.o'
        r = am.run_limited(cmd, cwd=tmp, shell=True, timeout=30)
        ok = (Path(tmp) / 'p.o').exists()
    _probe_cache[key] = ok
    return ok


def base_of(prior, census_top: str, addr: int) -> str:
    try:
        pr = prior.predict(addr, 3)
    except Exception:  # noqa: BLE001
        pr = []
    p = pr[0][0] if pr else census_top
    v, _, e = p.partition(' ')
    if '-thumb' in e:
        return census_top
    return p


def split(p: str) -> tuple[str, str]:
    v, _, e = p.strip().partition(' ')
    return v, e.strip()


def load_stats() -> dict:
    try:
        return json.loads(STATS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def promote(stats: dict) -> list[str]:
    """Profiles (base + delta) that matched in >= PROMOTE_GAMES games or >= PROMOTE_MATCHES functions in all: written
    to promoted_profiles.txt, which auto_match tries on every game."""
    games, total = collections.Counter(), collections.Counter()
    for name, g in stats.items():
        if 'won_profiles' not in g:  # runs started before won_profiles existed: the match files' marker lines
            c = collections.Counter()
            import workspace
            for f in ((workspace.find_game(name) or GT.parents[1] / 'projets' / name) / 'build/hunt/flagsweep/match').glob('*.c'):
                first = f.read_text(encoding='utf-8', errors='replace').split('\n', 1)[0]
                if first.startswith(am.MARKER):
                    c[' '.join(first[len(am.MARKER):].replace('*/', '').split())] += 1
            g['won_profiles'] = dict(c)
        for prof, n in g.get('won_profiles', {}).items():
            games[prof] += 1; total[prof] += n
    keep = sorted((p for p in total if games[p] >= PROMOTE_GAMES or total[p] >= PROMOTE_MATCHES),
                  key=lambda p: (-total[p], p))
    head = ('# written by prototypes/flagsweep.py (promote): profile, then games and matches. auto_match adds these to\n'
            '# GLOBAL_PROFILES. Edit PROMOTE_GAMES/PROMOTE_MATCHES there, not this file.\n')
    PROMOTED.write_text(head + ''.join(f'{p}  # {games[p]} games, {total[p]} matches\n' for p in keep), encoding='utf-8')
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='build/auto/near')
    ap.add_argument('--pairs', action='store_true')
    ap.add_argument('--commit', action='store_true')
    ap.add_argument('--commit-only', action='store_true', help='integrate build/hunt/flagsweep/match/*.c, no sweep')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--effective', action='store_true', help='only deltas that changed some draft in an earlier game')
    ap.add_argument('--chunk', type=int, default=200)
    ap.add_argument('-j', type=int, default=6, help='compiler calls at the same time')
    ap.add_argument('--max', type=int, default=0, help='at most this many drafts (smallest first)')
    ap.add_argument('--deltas', help='";"-separated deltas instead of the built-in list')
    ap.add_argument('--no-pragmas', action='store_true')
    ap.add_argument('--promote', action='store_true', help='only rewrite promoted_profiles.txt from the stats')
    a = ap.parse_args()
    if a.promote:
        print('\n'.join(promote(load_stats()))); return

    root = am.ROOT
    if a.commit_only:
        open_names = {f[0]: f for f in am.candidates()}
        found = []
        for p in sorted((root / 'build/hunt/flagsweep/match').glob('*.c')):
            f = open_names.get(p.stem)
            if f:
                found.append((f[0], f[1], f[2], p.read_text(encoding='utf-8')))
        print(len(found), 'matches to integrate')
        if found:
            from pipeline_lock import pipeline_lock
            with pipeline_lock('flagsweep'):
                print('kept', am.commit_found(found))
        return
    prior = profprior.prior(str(root))
    cen = prior.census()
    census_top = next((p for p, _ in cen if '-thumb' not in p), prior.default) if cen else prior.default

    open_names = {f[0]: f for f in am.candidates()}
    items = []
    for p in sorted((root / a.src).glob('*.c')):
        f = open_names.get(p.stem)
        if f:
            items.append((f[0], f[1], f[2], p.read_text(encoding='utf-8', errors='replace')))
    items.sort(key=lambda it: it[1])
    if a.max:
        items = items[:a.max]
    groups = collections.defaultdict(list)
    for it in items:
        groups[base_of(prior, census_top, it[2])].append(it)

    if a.deltas:
        deltas_all = [d.strip() for d in a.deltas.split(';') if d.strip()]
    else:
        deltas_all = list(CLI)
    stats = load_stats()
    eff = set()
    for g in stats.values():
        eff |= {d for d, s in g.get('deltas', {}).items() if s.get('changed', 0) > 0}

    print(f'{len(items)} near drafts, bases: ' + ', '.join(f'{b} ({len(v)})' for b, v in groups.items()), flush=True)
    out = root / 'build' / 'hunt' / 'flagsweep'
    (out / 'match').mkdir(parents=True, exist_ok=True)
    res = {}
    won = {}
    dstat = collections.defaultdict(lambda: {'tried': 0, 'changed': 0, 'closer': 0, 'match': 0})
    helped = collections.defaultdict(list)  # name -> [(diffs, delta)]

    def sweep(base, todo, delta):
        v, e = split(base)
        extra = f'{e} {delta}'.strip()
        if not accepted(v, extra):
            return None
        mwcc = am.MWCC_ROOT / v / 'mwccarm.exe'
        parts = [todo[k:k + a.chunk] for k in range(0, len(todo), a.chunk)]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max(1, min(a.j, len(parts)))) as ex:
            outs = list(ex.map(lambda part: nearsweep.compile_diffs(part, mwcc, extra), parts))
        return [x for part, o in zip(parts, outs) for x in zip(part, o)]

    for base, its in groups.items():
        v, _ = split(base)
        exe = am.MWCC_ROOT / v / 'mwccarm.exe'
        if not exe.exists():
            print('  no compiler', v); continue
        deltas = list(deltas_all)
        if not a.deltas and not a.no_pragmas:
            deltas += pragma_deltas(exe)
        if a.effective and eff:
            deltas = [d for d in deltas if d in eff]
        if a.list:
            print(f'{base}: {len(deltas)} deltas'); print('\n'.join('  ' + d for d in deltas)); continue
        got = sweep(base, its, '')
        for it, d in got or []:
            res[it[0]] = {'base': base, 'base_diffs': d, 'best': base, 'diffs': d if d is not None else 10 ** 6}
            if d == 0:
                won[it[0]] = (it, base)
        print(f'[{base}] {len(its)} drafts, {sum(1 for _, d in got or [] if d == 0)} already match at base', flush=True)
        for i, delta in enumerate(deltas):
            todo = [it for it in its if it[0] not in won]
            if not todo:
                break
            got = sweep(base, todo, delta)
            if got is None:
                print(f'  {delta:45} refused by {v}', flush=True)
                continue
            st = dstat[delta]; st['tried'] += len(todo)
            for it, d in got:
                r = res.get(it[0])
                if d is None or r is None:
                    continue
                bd = r['base_diffs']
                if bd is not None and d != bd:
                    st['changed'] += 1
                if bd is not None and d < bd:
                    st['closer'] += 1
                    helped[it[0]].append((d, delta))
                if d < r['diffs']:
                    r.update(diffs=d, best=f'{base} {delta}')
                if d == 0 and it[0] not in won:
                    won[it[0]] = (it, f'{base} {delta}'); st['match'] += 1
            if st['changed'] or st['match']:
                print(f'  {delta:45} changed {st["changed"]:4} closer {st["closer"]:4} match {st["match"]}', flush=True)
            if i % 10 == 9:
                print(f'  ... {i + 1}/{len(deltas)} deltas, {len(won)} matches', flush=True)

    if a.list:
        return
    if a.pairs:
        combos = collections.defaultdict(list)  # (base, combo) -> items
        byname = {it[0]: it for it in items}
        for n, hs in helped.items():
            if n in won:
                continue
            ds = [d for _, d in sorted(hs)[:4]]
            cs = [' '.join(c) for c in itertools.combinations(ds, 2)]
            if len(ds) >= 3:
                cs.append(' '.join(ds[:3]))
            for c in cs:
                combos[(res[n]['base'], c)].append(byname[n])
        print(f'pairs: {len(combos)} combinations over {sum(1 for n in helped if n not in won)} drafts', flush=True)
        for (base, c), its in sorted(combos.items(), key=lambda kv: -len(kv[1])):
            its = [it for it in its if it[0] not in won]
            if not its:
                continue
            got = sweep(base, its, c)
            for it, d in got or []:
                r = res[it[0]]
                if d is not None and d < r['diffs']:
                    r.update(diffs=d, best=f'{base} {c}')
                if d == 0 and it[0] not in won:
                    won[it[0]] = (it, f'{base} {c}'); dstat['pair: ' + c]['match'] += 1
                    print(f'  MATCH {it[0]} {base} {c}', flush=True)

    (out / 'results.json').write_text(json.dumps(res, indent=0), encoding='utf-8')
    found = []
    for name, (it, prof) in won.items():
        v, e = split(prof)
        src = f'{am.MARKER}{v} {e} */\n' + it[3] if (v, e) != am.COMPILERS[0] else it[3]
        (out / 'match' / f'{name}.c').write_text(src, encoding='utf-8')
        found.append((it[0], it[1], it[2], src))
    closer = sum(1 for r in res.values() if r['base_diffs'] is not None and 0 < r['diffs'] < r['base_diffs'])
    per = collections.Counter(split(p)[1] for _, p in won.values())
    print(f'{len(won)} matches, {closer} near misses closer: {dict(per)}')

    game = root.name
    stats = load_stats()
    stats[game] = {'drafts': len(items), 'matches': len(won), 'closer': closer,
                   'deltas': {d: s for d, s in dstat.items() if s['changed'] or s['match']},
                   'won_profiles': dict(collections.Counter(' '.join(p.split()) for _, p in won.values()))}
    try:
        STATS.write_text(json.dumps(stats, indent=1, sort_keys=True), encoding='utf-8')
        print('promoted:', len(promote(stats)))
    except OSError:
        pass
    if a.commit and found:
        from pipeline_lock import pipeline_lock
        with pipeline_lock('flagsweep'):
            print('kept', am.commit_found(found))


if __name__ == '__main__':
    main()
