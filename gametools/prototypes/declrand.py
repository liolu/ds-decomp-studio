"""declrand.py NAME FILE.c [--n 1500] [-j 12] [--seed S] [--profile P] : random full permutations of the declaration lines
between DECL-BEGIN / DECL-END (or NAME's leading declarations), judged in a persistent process pool (fast, unlike
permrand.py which starts workbench per variant). Writes FILE.best.c. Technique id: decl-order (see declperm/declclimb)."""
import random, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from declclimb import _init, _score  # noqa: E402
from declperm import split_decls  # noqa: E402


def main():
    a = sys.argv[1:]
    def opt(k, d):
        if k in a:
            i = a.index(k); v = a[i + 1]; del a[i:i + 2]; return v
        return d
    n, jobs, seed, prof = int(opt('--n', 1500)), int(opt('-j', 12)), int(opt('--seed', 1)), opt('--profile', None)
    name, f = a[0], a[1]
    lines = Path(f).read_text(encoding='utf-8').split('\n')
    i0, i1, decl = split_decls(lines, name)
    rnd = random.Random(seed)
    seen, srcs = set(), []
    while len(srcs) < n:
        o = decl[:]; rnd.shuffle(o); k = tuple(o)
        if k in seen:
            continue
        seen.add(k); srcs.append('\n'.join(lines[:i0] + o + lines[i1:]))
    with Pool(jobs, initializer=_init, initargs=(name, prof)) as pool:
        sc = pool.map(_score, srcs, chunksize=8)
    s, src = min(zip(sc, srcs), key=lambda t: t[0])
    print('best', s, '(MATCH)' if s == 0 else '')
    Path(f + '.best.c').write_text(src, encoding='utf-8')


if __name__ == '__main__':
    main()
