"""nearsweep.py - judge the stored auto_match near misses (build/auto/near/NAME.c) with every profile that matched in ANY game.

    python ../../studio/gametools/prototypes/nearsweep.py                 # report only (build/hunt/nearsweep/)
    python ../../studio/gametools/prototypes/nearsweep.py --commit        # integrate the matches (auto_match.commit_found)
    python ../../studio/gametools/prototypes/nearsweep.py --min 20 --profiles "1.2/sp2p3 -O4,s;1.2/b56"

Run from the project dir (projets/<game>). One compiler call per profile for all the drafts (auto_match.compile_many
style), so ~40 profiles x 400 drafts take minutes, not hours.

Why (2026-11-16): a profile found in one game never reached the others unless someone typed it into
AUTO_EXTRA_PROFILES or agentround PROFILES. Global census of compilers.txt over all games: `1.2/sp2p3 -O4,s` 727 files
(675 of them Resident Evil), `1.2/b56` 657, `-O4,p -lang c99 -inline on,noauto` 5.8k, `-flag no-opt_*` 70... Near misses
(same size, a few instructions differ) are the drafts most likely to be a profile away from a match.

Writes build/hunt/nearsweep/results.json {name: {best_profile, diffs, base_diffs}} and the matches as
build/hunt/nearsweep/match/NAME.c (first line = auto_match compiler marker). --commit integrates them like auto_match
does (verify, culprits dropped, compilers.txt written); the caller commits.
"""
import argparse
import collections
import json
import sys
import tempfile
from pathlib import Path

GT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GT))
_argv, sys.argv = sys.argv, sys.argv[:1]
import auto_match as am  # noqa: E402
sys.argv = _argv
pc = am.pc


def global_census(projets: Path, min_count: int):
    c = collections.Counter()
    seen = set()
    for f in projets.glob('*/config/*/compilers.txt'):
        try:
            lines = f.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip() or line.startswith('#'):
                continue
            src, _, p = line.partition(' ')
            p = ' '.join(p.split())
            if not p:
                continue
            key = (f.parts[-4], src)  # copies of a game (native/zones/hunt) count once per file name
            if (key, p) in seen:
                continue
            seen.add((key, p))
            c[p] += 1
    out = []
    for p, n in c.most_common():
        v, _, e = p.partition(' ')
        if n < min_count or '-thumb' in e or not (am.MWCC_ROOT / v / 'mwccarm.exe').exists():
            continue
        out.append(((v, e.strip()), n))
    return out


def compile_diffs(items, mwcc, extra):
    """[(name, size, addr, source)] -> [diffs or None] in one compiler call (retried without the failing files)."""
    res = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp); (work / 'objs').mkdir()
        for i, it in enumerate(items):
            (work / f'v{i}.c').write_text(it[3])
        pending, nofail = list(range(len(items))), '-nofail'
        while pending:
            files = ' '.join(f'v{i}.c' for i in pending)
            cmd = f'"{mwcc}" -O4,p {pc.BASE_FLAGS} {extra} {nofail} -i "{am.ROOT / "include"}" -c {files} -o objs'
            r = am.run_limited(cmd, cwd=work, shell=True, timeout=60 + 2 * len(pending))
            if r.stderr == 'timeout':
                break
            missing = []
            for i in pending:
                name, size, addr, _ = items[i]
                obj = work / 'objs' / f'v{i}.o'
                if not obj.exists():
                    missing.append(i); continue
                cand = pc.compiled_function(obj, name)
                if cand is None:
                    continue
                bad, _ = pc.compare(pc.target_bytes(addr, size), cand)
                res[i] = bad if len(cand) == size else 1000 + abs(len(cand) - size)
            st = {}
            pending, nofail = am.missing_after_call(missing, pending, nofail, st)
    return [res.get(i) for i in range(len(items))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min', type=int, default=20, help='global census: profiles used by at least this many files')
    ap.add_argument('--profiles', help='";"-separated profiles instead of the census')
    ap.add_argument('--src', default='build/auto/near')
    ap.add_argument('--commit', action='store_true')
    ap.add_argument('--chunk', type=int, default=150)
    a = ap.parse_args()
    root = am.ROOT
    open_names = {f[0]: f for f in am.candidates()}
    items = []
    for p in sorted((root / a.src).glob('*.c')):
        f = open_names.get(p.stem)
        if f:
            items.append((f[0], f[1], f[2], p.read_text(encoding='utf-8', errors='replace')))
    if a.profiles:
        profs = [(tuple((x.strip().partition(' ')[0], x.strip().partition(' ')[2].strip())), 0) for x in a.profiles.split(';') if x.strip()]
    else:
        profs = global_census(root.parent, a.min)
    base = am.COMPILERS[0]
    have = [p for p, _ in profs]
    profs = [(c, 0) for c in am.BASE_COMPILERS if c not in have] + profs
    print(f'{len(items)} near drafts still unmatched, {len(profs)} profiles', flush=True)
    out = root / 'build' / 'hunt' / 'nearsweep'; (out / 'match').mkdir(parents=True, exist_ok=True)
    best = {}
    won = {}
    per_prof = collections.Counter()
    for prof, n in profs:
        todo = [it for it in items if it[0] not in won]
        mwcc = am.MWCC_ROOT / prof[0] / 'mwccarm.exe'
        for k in range(0, len(todo), a.chunk):
            part = todo[k:k + a.chunk]
            for it, d in zip(part, compile_diffs(part, mwcc, prof[1])):
                if d is None:
                    continue
                b = best.setdefault(it[0], {'diffs': 10 ** 6})
                if prof in am.BASE_COMPILERS:  # what auto_match always tried: the 'closer' count compares with that
                    b['base_diffs'] = min(d, b.get('base_diffs', 10 ** 6))
                if d < b['diffs']:
                    b.update(diffs=d, best_profile=am.prof_str(prof))
                if d == 0 and it[0] not in won:
                    won[it[0]] = (it, prof); per_prof[am.prof_str(prof)] += 1
        print(f'  {am.prof_str(prof):60} census {n:6}  matches {per_prof[am.prof_str(prof)]}', flush=True)
    (out / 'results.json').write_text(json.dumps(best, indent=0), encoding='utf-8')
    found = []
    for name, (it, prof) in won.items():
        src = it[3] if prof == base else f'{am.MARKER}{prof[0]} {prof[1]} */\n' + it[3]
        (out / 'match' / f'{name}.c').write_text(src, encoding='utf-8')
        found.append((it[0], it[1], it[2], src))
    better = sum(1 for b in best.values() if 0 < b['diffs'] < b.get('base_diffs', 10 ** 6))
    print(f'{len(won)} matches, {better} near misses closer with another profile: {dict(per_prof)}')
    if a.commit and found:
        from pipeline_lock import pipeline_lock
        with pipeline_lock('nearsweep'):
            print('kept', am.commit_found(found))


if __name__ == '__main__':
    main()
