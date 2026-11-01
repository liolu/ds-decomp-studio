"""declclimb.py NAME FILE.c [--rounds 6] [-j 12] [--profile P] : hill climbing on the order of the local declaration
lines (DECL-BEGIN / DECL-END markers, or the leading declarations of NAME, like declperm.py). Each round judges every
"move line a before line b" variant in parallel and keeps the best one; stops when a round brings nothing.
Writes FILE.best.c. Why: when only register numbers / spill slots differ, declaration order drives mwcc's allocation
(TnJ func_01ff8e94: random order 74 -> 15 diffs, slots only); random sampling (declperm) stalls, climbing walks the
remaining distance. Technique id: decl-climb. Origin: TnJ session s30 (2026-10-29)."""
import os, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hunt  # noqa: E402
from declperm import split_decls  # noqa: E402

NAME = PROF = None


def _init(name, prof):
    global NAME, PROF
    NAME, PROF = name, prof
    hunt._init()


def _score(src):
    r = hunt._judge((NAME, src, PROF))
    if r.get('match'):
        return 0
    d = r.get('diffs')
    if d is None:
        return 10 ** 9
    return d + 1000 * abs((r.get('size') or 0) - (r.get('target_size') or 0))


def main():
    a = sys.argv[1:]
    def opt(k, d):
        if k in a:
            i = a.index(k); v = a[i + 1]; del a[i:i + 2]; return v
        return d
    rounds, jobs, prof = int(opt('--rounds', 6)), int(opt('-j', 12)), opt('--profile', None)
    name, f = a[0], a[1]
    lines = Path(f).read_text(encoding='utf-8').split('\n')
    i0, i1, decl = split_decls(lines, name)
    build = lambda order: '\n'.join(lines[:i0] + order + lines[i1:])
    cur = list(decl)
    with Pool(jobs, initializer=_init, initargs=(name, prof)) as pool:
        best = pool.apply(_score, (build(cur),))
        print('start', best, flush=True)
        for rnd in range(rounds):
            cands = []
            for x in range(len(cur)):
                for y in range(len(cur)):
                    if x == y:
                        continue
                    o = cur[:x] + cur[x + 1:]
                    o.insert(y, cur[x])
                    if o != cur and o not in cands:
                        cands.append(o)
            scores = pool.map(_score, [build(o) for o in cands])
            s, o = min(zip(scores, cands), key=lambda t: t[0])
            print(f'round {rnd}: best {s} ({len(cands)} variants)', flush=True)
            if s >= best:
                break
            best, cur = s, o
            Path(f + '.best.c').write_text(build(cur), encoding='utf-8')
            if best == 0:
                print('MATCH', flush=True)
                break
    print('final', best)


if __name__ == '__main__':
    main()
