"""varmerge.py NAME FILE.c [-p PROFILE] : brute-force two source-level facts the register allocator betrays.
  param-reuse    the original reused a variable: `idx = tab[idx];` instead of a new local, so the value lands in the
                 parameter's register (`ldr r4, [r3, r4, lsl #2]`). Mutation: every local merged into every other
                 local or parameter of the same base type (declaration dropped, all uses renamed).
  hidden-return  a `void` function whose target leaves a meaningful value in r0 on every path really returns it
                 (`return i;` where i = the search result or the new slot index). Mutation: void -> s32 and
                 `return V;` on every exit, for every local/parameter V.
Merges can change the semantics; only a byte-identical result (judge MATCH, then the ROM build) is accepted.
Technique ids: param-reuse, hidden-return. Origin: TnJ s36 (2026-10-29): func_0203cd5c, func_0203cdd0
(param-reuse), func_02032598, func_02033a2c (hidden-return)."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402

DECL = re.compile(r'^(\s+)((?:const\s+)?(?:unsigned\s+|signed\s+)?\w+)(\s*\**\s*)(\w+)\s*;\s*$')


INTS = {'s32', 'u32', 's16', 'u16', 's8', 'u8', 'short', 'char', 'unsigned char', 'unsigned short', 'BOOL'}


def _base(t):
    return {'int': 's32', 'long': 's32', 'unsigned int': 'u32'}.get(t, t)


def mutations(src, name):
    sp = hunt.body_span(src, name)
    if not sp: return []
    hs, bs, be, m = sp
    head, body, pre, post = src[hs:bs], src[bs:be], src[:hs], src[be:]
    out = []
    locs = {}
    lines = body.split('\n')
    for i, l in enumerate(lines):
        d = DECL.match(l)
        if d and d.group(2) not in ('return', 'goto'):
            locs[d.group(4)] = (i, _base(d.group(2)) + d.group(3).strip())
    params = {}
    for p in m.group(1).split(','):
        pm = re.match(r'^\s*((?:const\s+)?(?:unsigned\s+)?\w+)(\s*\**\s*)(\w+)\s*$', p)
        if pm: params[pm.group(3)] = _base(pm.group(1)) + pm.group(2).strip()
    allv = {**params, **{k: t for k, (i, t) in locs.items()}}
    # param-reuse / local merge
    for a, (ai, at) in locs.items():
        for b, bt in allv.items():
            if a == b or (at != bt and not (at in INTS and bt in INTS)): continue
            L = lines[:]; del L[ai]
            nb = re.sub(r'\b' + re.escape(a) + r'\b', b, '\n'.join(L))
            out.append(('param-reuse' if b in params else 'var-merge', pre + head + nb + post))
    # hidden-return
    if re.match(r'^\s*(static\s+)?void\s', head):
        nh = re.sub(r'\bvoid(\s+' + re.escape(name) + r')', r's32\1', head, 1)
        for v in allv:
            nb = re.sub(r'\breturn\s*;', f'return {v};', body)
            k = nb.rstrip().rfind('}')
            nb = nb[:k] + f'    return {v};\n' + nb[k:]
            out.append(('hidden-return', pre + nh + nb + post))
    return out


def score(r):
    if r.get('match'): return 0
    if r.get('status') in ('near', 'size'):
        return (r.get('diffs') or 0) + 1000 * abs((r.get('size') or 0) - (r.get('target_size') or 0)) + 1
    return 10 ** 9


def proto_run(ctx):
    ms = mutations(ctx['src'], ctx['name'])
    if not ms: return {'result': 'skip', 'note': 'no mergeable variables, not void'}
    best, bsrc, btag = score(ctx['base']), None, None
    for tag, v in ms:
        s = score(ctx['judge'](v))
        if s < best: best, bsrc, btag = s, v, tag
        if s == 0: return {'result': 'ok', 'diffs': 0, 'profile': ctx['profile'], 'src': v, 'note': tag}
    if bsrc: return {'result': 'better', 'diffs': best - 1, 'profile': ctx['profile'], 'src': bsrc, 'note': btag}
    return {'result': 'fail', 'diffs': ctx['base'].get('diffs'), 'profile': ctx['profile'],
            'note': f'{len(ms)} variants: ' + ','.join(sorted({t for t, _ in ms}))}


if __name__ == '__main__':
    a = sys.argv[1:]
    prof = a[a.index('-p') + 1] if '-p' in a else None
    name, f = a[0], a[1]
    hunt._init(); src = open(f, encoding='utf-8', errors='replace').read()
    base = score(hunt._judge((name, src, prof)))
    ms = mutations(src, name)
    res = sorted(((score(hunt._judge((name, v, prof))), t, v) for t, v in ms), key=lambda x: x[0])
    print(f'base {base - 1 if base < 10 ** 9 else "-"}, {len(ms)} variants')
    for s, t, _ in res[:8]: print(s - 1 if s else 'MATCH', t)
    if res and res[0][0] < base:
        open(f[:-2] + '.vmerge.c', 'w', encoding='utf-8').write(res[0][2]); print('wrote', f[:-2] + '.vmerge.c')
    import os; sys.stdout.flush(); os._exit(0)
