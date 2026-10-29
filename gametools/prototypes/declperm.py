"""declperm.py NAME FILE.c [--n 400] [-j 10] [--profile P] : random permutations of the local declaration lines that
follow the `DECL-BEGIN` / `DECL-END` comments in FILE.c (or, without markers, the leading declarations of NAME),
judged in persistent worker processes (hunt._judge). Writes FILE.best.c when a permutation beats FILE.c.
Why: declaration order of locals = callee-saved register order in mwcc (TnJ func_0203d0d8: xx r4, yy r5, p r6, q r7),
but NOT for params, nor when temporaries dominate. Technique id: decl-order. Origin: TnJ build/hunt/w/fperm.py (r21)."""
import os, random, re, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402


def split_decls(lines, name):
    if any('DECL-BEGIN' in l for l in lines):
        i0 = next(i for i, l in enumerate(lines) if 'DECL-BEGIN' in l) + 1
        i1 = next(i for i, l in enumerate(lines) if 'DECL-END' in l)
        return i0, i1, lines[i0:i1]
    i0 = next(i for i, l in enumerate(lines) if re.match(r'^\w[^;]*\b' + re.escape(name) + r'\(', l))
    while not lines[i0].rstrip().endswith('{'):
        i0 += 1
    i0 += 1
    j = i0
    decl = []
    while j < len(lines) and re.match(r'^\s+[A-Za-z_][\w \*\[\]]*(,[\w \*\[\]]+)*;\s*$', lines[j]):
        m = re.match(r'^\s+((?:\w+ )*\w+)\s*(.*);', lines[j])
        for part in m.group(2).split(','):
            decl.append(f'    {m.group(1)} {part.strip()};')
        j += 1
    return i0, j, decl


def variants(src, name, n, seed=1):
    lines = src.split('\n')
    try: i0, i1, decl = split_decls(lines, name)
    except StopIteration: return []
    if len(decl) < 2: return []
    rnd = random.Random(seed)
    seen, out = set(), []
    for _ in range(n * 3):
        order = decl[:]; rnd.shuffle(order)
        t = tuple(order)
        if t in seen or order == decl: continue
        seen.add(t); out.append('\n'.join(lines[:i0] + order + lines[i1:]))
        if len(out) >= n: break
    return out


def score(r):
    if r.get('match'): return 0
    if r.get('status') in ('near', 'size'):
        return (r.get('diffs') or 0) + 1000 * abs((r.get('size') or 0) - (r.get('target_size') or 0)) + 1
    return 10 ** 9


def job(args):
    name, text, prof = args
    return score(hunt._judge((name, text, prof))), text


def proto_run(ctx):
    vs = variants(ctx['src'], ctx['name'], 60)
    if not vs: return {'result': 'skip', 'note': 'fewer than 2 local declarations'}
    best, bsrc = score(ctx['base']), None
    for v in vs:  # sequential: parallel agents each run protorun, no pool per agent
        r = ctx['judge'](v)
        s = score(r)
        if s < best: best, bsrc = s, v
        if s == 0: return {'result': 'ok', 'diffs': 0, 'profile': ctx['profile'], 'src': v, 'note': 'declaration order'}
    if bsrc: return {'result': 'better', 'diffs': best - 1, 'profile': ctx['profile'], 'src': bsrc, 'note': f'{len(vs)} orders'}
    return {'result': 'fail', 'diffs': ctx['base'].get('diffs'), 'profile': ctx['profile'], 'note': f'{len(vs)} orders, none better'}


def main():
    a = sys.argv[1:]
    def opt(k, d):
        return a[a.index(k) + 1] if k in a else d
    name, f = a[0], a[1]
    n, j, prof = int(opt('--n', 400)), int(opt('-j', 10)), opt('--profile', None)
    src = open(f, encoding='utf-8').read()
    texts = [src] + variants(src, name, n)
    print(len(texts) - 1, 'orders', flush=True)
    with Pool(j, initializer=hunt._init, initargs=(True,)) as pool:
        res = pool.map(job, [(name, t, prof) for t in texts], chunksize=4)
    base = res[0][0]
    best = min(res, key=lambda r: r[0])
    print(f'base {base} best {best[0]} ({len(res)} tried)', flush=True)
    if best[0] < base:
        open(f[:-2] + '.best.c', 'w', encoding='utf-8').write(best[1])
        print('wrote', f[:-2] + '.best.c', flush=True)


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
