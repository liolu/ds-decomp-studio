"""declsubset.py NAME FILE.c VAR1,VAR2,... [-j 12] [--profile P] : every order of the declaration lines of the
named locals (the other declaration lines keep their place), judged in parallel. Writes FILE.best.c.
Why: when only spill slots are wrong, the slots follow the order in which the spilled locals are declared, but not
monotonically: a full random search is too wide and the hill climb (declclimb.py) gets stuck. Permuting only the
spilled locals (<= 7 -> 5040 variants) is exhaustive. Technique id: decl-subset. Origin: TnJ session s30 (2026-10-29)."""
import itertools, re, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from declclimb import _init, _score  # noqa: E402


def main():
    a = sys.argv[1:]
    def opt(k, d):
        if k in a:
            i = a.index(k); v = a[i + 1]; del a[i:i + 2]; return v
        return d
    jobs, prof = int(opt('-j', 12)), opt('--profile', None)
    name, f, names = a[0], a[1], a[2].split(',')
    lines = Path(f).read_text(encoding='utf-8').split('\n')
    pos = {}
    for i, l in enumerate(lines):
        m = re.match(r'^\s+[\w ]+?[\s\*]+(\w+)(\[\w*\])?;\s*$', l)
        if m and m.group(1) in names and m.group(1) not in pos:
            pos[m.group(1)] = i
    missing = [n for n in names if n not in pos]
    if missing:
        sys.exit('declaration not found: ' + ', '.join(missing))
    slots = sorted(pos.values())
    srcs = []
    for order in itertools.permutations(names):
        out = list(lines)
        for slot, n in zip(slots, order):
            out[slot] = lines[pos[n]]
        srcs.append('\n'.join(out))
    print(len(srcs), 'variants', flush=True)
    with Pool(jobs, initializer=_init, initargs=(name, prof)) as pool:
        scores = pool.map(_score, srcs, chunksize=4)
    s, src = min(zip(scores, srcs), key=lambda t: t[0])
    print('best', s, '(MATCH)' if s == 0 else '')
    Path(f + '.best.c').write_text(src, encoding='utf-8')


if __name__ == '__main__':
    main()
