"""profextra.py NAME FILE.c : judge FILE.c on every profile hunt knows for NAME plus the ones that matched in earlier
rounds although `hunt show` / `workbench info` printed another one (HoM r12/r27: header profile wrong for ~half of the
agent matches; TnJ: func_0200dc50 only at -O1, func_02049744 at -O2, func_020302cc at -O4,s).
Technique id: profile-sweep. Origin: HoM sessions 11-12, TnJ r1-r6."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402

EXTRA = ['2.0/sp1p5', '1.2/sp3', '1.2/sp2p3', '2.0/sp1p5 -O1', '2.0/sp1p5 -O2', '2.0/sp1p5 -O4,s', '1.2/sp3 -O2,p',
         '2.0/sp1p5 -profile', '1.2/sp3 -profile', '1.2/sp2p3 -proc arm7tdmi', '1.2/sp3 -proc arm7tdmi']


def profiles(name):
    try: base = hunt._profiles(name)
    except Exception: base = []  # noqa: BLE001
    if base and base[0].endswith('-thumb'): return base
    return list(dict.fromkeys(EXTRA + base))


def sweep(name, src, judge, log=print):
    best = None
    for p in profiles(name):
        r = judge(src, p)
        if best is None or score(r) < score(best): best = r
        if r.get('match'): break
    return best


def score(r):
    if r.get('match'): return 0
    if r.get('status') in ('near', 'size'):
        return (r.get('diffs') or 0) + 1000 * abs((r.get('size') or 0) - (r.get('target_size') or 0)) + 1
    return 10 ** 9


def proto_run(ctx):
    b = sweep(ctx['name'], ctx['src'], ctx['judge'], ctx['log'])
    if b is None: return {'result': 'skip', 'note': 'no profile'}
    if b.get('match'): return {'result': 'ok', 'diffs': 0, 'profile': b['profile'], 'src': ctx['src'], 'note': 'matches at another profile'}
    if score(b) < score(ctx['base']):
        return {'result': 'better', 'diffs': b.get('diffs'), 'profile': b['profile'], 'src': ctx['src'],
                'note': f'better profile (base {ctx["base"].get("diffs")} diffs at {ctx["base"].get("profile")})'}
    return {'result': 'fail', 'diffs': b.get('diffs'), 'profile': b.get('profile'), 'note': f'{len(profiles(ctx["name"]))} profiles'}


if __name__ == '__main__':
    name, f = sys.argv[1], sys.argv[2]
    hunt._init(); src = open(f, encoding='utf-8', errors='replace').read()
    for p in profiles(name):
        r = hunt._judge((name, src, p))
        print(f'{p:28s} {r["status"]:8s} {r.get("diffs")} {r.get("size")}/{r.get("target_size")}' + (' MATCH' if r.get('match') else ''))
    import os; sys.stdout.flush(); os._exit(0)
