"""cmutate.py NAME FILE.c [-p PROFILE] : text mutations learned in TnJ hand sessions that hunt.py's battery does not
have yet; each variant is judged, the best is printed (and written to FILE.cmut.c when it beats FILE.c).
  int-vs-long   m2c.h has `typedef long s32;`: `long` and `int` index give different code (`k[i + 1]`: CSE'd base
                pointer with long, `add r1,i,#1; ldr [k,r1,lsl #2]` with int) - each s32 local/param -> int, then all
  neg-mul       `x = -x;` <-> `x *= -1;` (keeps smulbb / changes the multiply)
  chain-order   `a = b = E;` -> `b = a = E;` (literal pool order, func_02032c40), and `a = E; b = E;` -> `b = a = E;`
  nested-assign `a = 0; ... b = -1;` -> `b = (a = 0) - 1;` (defeats constant folding, distinct regs, func_0203075c)
Technique ids: int-vs-long, neg-mul, chain-order, nested-assign. Origin: TnJ sessions r21-r28 + func_0203075c."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402

ASSIGN = re.compile(r'^(\s*)([\w.\->\[\]]+) = ([^=;][^;]*);\s*$')


def mutations(src, name):
    sp = hunt.body_span(src, name)
    if not sp: return []
    hs, bs, be, m = sp
    head, body = src[hs:bs], src[bs:be]
    pre, post = src[:hs], src[be:]
    out = []
    # int-vs-long: locals then params
    decls = [mm for mm in re.finditer(r'^(\s+)s32(\s+\**\w+)', body, re.M)]
    for d in decls:
        out.append(('int-vs-long', pre + head + body[:d.start()] + d.group(1) + 'int' + d.group(2) + body[d.end():] + post))
    if len(decls) > 1:
        out.append(('int-vs-long', pre + head + re.sub(r'^(\s+)s32(\s+\**\w+)', r'\1int\2', body, flags=re.M) + post))
    if re.search(r'\bs32\b', head):
        out.append(('int-vs-long', pre + re.sub(r'\bs32\b', 'int', head) + body + post))
    # neg-mul
    for mm in re.finditer(r'\b([\w.\->]+) = -\1;', body):
        out.append(('neg-mul', pre + head + body[:mm.start()] + f'{mm.group(1)} *= -1;' + body[mm.end():] + post))
    for mm in re.finditer(r'\b([\w.\->]+) \*= -1;', body):
        out.append(('neg-mul', pre + head + body[:mm.start()] + f'{mm.group(1)} = -{mm.group(1)};' + body[mm.end():] + post))
    lines = body.split('\n')
    for i, l in enumerate(lines):
        mm = re.match(r'^(\s*)([\w.\->\[\]]+) = ([\w.\->\[\]]+) = ([^;]+);\s*$', l)
        if mm:
            ls = lines[:]; ls[i] = f'{mm.group(1)}{mm.group(3)} = {mm.group(2)} = {mm.group(4)};'
            out.append(('chain-order', pre + head + '\n'.join(ls) + post))
        a, b = ASSIGN.match(l), ASSIGN.match(lines[i + 1]) if i + 1 < len(lines) else None
        if a and b and a.group(3) == b.group(3):
            for x, y in ((a, b), (b, a)):
                ls = lines[:]; ls[i] = f'{a.group(1)}{y.group(2)} = {x.group(2)} = {a.group(3)};'; del ls[i + 1]
                out.append(('chain-order', pre + head + '\n'.join(ls) + post))
    zeros = [(i, ASSIGN.match(l)) for i, l in enumerate(lines) if ASSIGN.match(l) and ASSIGN.match(l).group(3) == '0']
    minus = [(i, ASSIGN.match(l)) for i, l in enumerate(lines) if ASSIGN.match(l) and ASSIGN.match(l).group(3) == '-1']
    for zi, z in zeros[:4]:
        for mi, mn in minus[:4]:
            ls = lines[:]
            ls[mi] = f'{mn.group(1)}{mn.group(2)} = ({z.group(2)} = 0) - 1;'
            del ls[zi]
            out.append(('nested-assign', pre + head + '\n'.join(ls) + post))
    return out


def score(r):
    if r.get('match'): return 0
    if r.get('status') in ('near', 'size'):
        return (r.get('diffs') or 0) + 1000 * abs((r.get('size') or 0) - (r.get('target_size') or 0)) + 1
    return 10 ** 9


def proto_run(ctx):
    ms = mutations(ctx['src'], ctx['name'])
    if not ms: return {'result': 'skip', 'note': 'no s32 / negation / chained or 0,-1 assignment'}
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
    res = sorted(((score(hunt._judge((name, v, prof))), t, v) for t, v in mutations(src, name)), key=lambda x: x[0])
    for s, t, _ in res[:15]: print(s, t)
    if res and res[0][0] < base:
        open(f[:-2] + '.cmut.c', 'w', encoding='utf-8').write(res[0][2]); print('wrote', f[:-2] + '.cmut.c')
    import os; sys.stdout.flush(); os._exit(0)
