"""schedscan.py NAME 'GLOB' [-p PROFILE] [-j 8] [--from K] [--len N] : judge every variant file matching GLOB in
parallel and group them by the instruction window [K, K+N) of their listing, registers KEPT, literal-pool loads
dropped; prints the variants whose window equals the TARGET's window and the 10 most common windows.
For register/scheduling puzzles where the diff count does not move (all variants "2 diffs") but the schedule does.
Generate the variants with a small script (Write tool, never a long bash heredoc: it gets truncated).
Technique id: sched-scan. Origin: TnJ func_0203075c (build/hunt/w/v075/scan.py, ~6000 variants)."""
import collections, glob, os, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['WB_FULL'] = '1'
import hunt  # noqa: E402


def window(lines, k, n):
    ins = [' '.join(l.split('@')[0].split()) for l in lines]
    ins = [i for i in ins if i and not i.startswith('ldr') and not i.startswith('.word')]
    return ' | '.join(ins[k:k + n])


def job(args):
    name, f, prof, k, n = args
    r = hunt._judge((name, open(f, encoding='utf-8', errors='replace').read(), prof))
    full = r.get('full') or {}
    return f, r.get('diffs'), window(full.get('t', []), k, n), window(full.get('c', []), k, n)


if __name__ == '__main__':
    a = sys.argv[1:]
    def opt(key, d):
        if key in a:
            i = a.index(key); v = a[i + 1]; del a[i:i + 2]; return v
        return d
    prof, j, k, n = opt('-p', None), int(opt('-j', 8)), int(opt('--from', 0)), int(opt('--len', 12))
    name, pat = a[0], a[1]
    files = sorted(glob.glob(pat))
    with Pool(j, initializer=hunt._init, initargs=(False,)) as pool:
        res = pool.map(job, [(name, f, prof, k, n) for f in files], chunksize=4)
    target = res[0][2] if res else ''
    print('TARGET', target)
    hits = [f for f, d, t, c in res if c == target]
    print('HITS', len(hits), hits[:10])
    cnt = collections.Counter(c for _, _, _, c in res); ex = {}
    for f, d, t, c in res: ex.setdefault(c, (f, d))
    for c, v in cnt.most_common(10): print(v, ex[c], c)
    sys.stdout.flush(); os._exit(0)
