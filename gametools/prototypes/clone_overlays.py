"""clone_overlays.py OUT [--from GAME[,GAME]] [-j N] : clone_match for OVERLAYS and ITCM (clone_match.py itself only
searches the ARM9 main module). For every module of this game (itcm, ov000, ov001...), the unmatched functions are
compared with the matched functions of every module of the donor games (default: every project next to this one),
renamed, compiled and checked byte for byte by clone_match.search. Matches are written to OUT/a1/NAME.c +
OUT/a1/results.json (ready for agentround.py OUT, which judges again and submits). Nothing is integrated.

Origin: Nintendogs 2026-11-11 - dachshund (usa) got ~2000 overlay matches, its three jp siblings share the code but
clone_match --other-games found 0 (main only). Run from the game dir."""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clone_match as cm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('--from', dest='frm', default='')
ap.add_argument('-j', type=int, default=8)
a = ap.parse_args()


def modules(root: Path) -> list[str]:
    vers = sorted(p.name for p in (root / 'config').iterdir() if (p / 'arm9' / 'symbols.txt').exists())
    arm9 = root / 'config' / vers[0] / 'arm9'
    mods = ['main'] + (['itcm'] if (arm9 / 'itcm' / 'symbols.txt').exists() else [])
    return mods + sorted(p.parent.name for p in (arm9 / 'overlays').glob('ov*/symbols.txt'))


donors = [cm.ROOT.parent / g for g in a.frm.split(',') if g] or \
    [d for d in sorted(cm.ROOT.parent.iterdir()) if d != cm.ROOT and (d / 'config').is_dir() and not d.name.startswith(('_', '.'))]
others = []
for d in donors:
    for m in modules(d):
        try:
            im = cm.Image(d, m)
        except Exception as e:  # noqa: BLE001
            print('skip', d.name, m, e); continue
        if im.files:
            others.append(im)
print(len(others), 'donor modules')

out = Path(a.out) / 'a1'; out.mkdir(parents=True, exist_ok=True)
res = {}
for m in modules(cm.ROOT):
    if m == 'main':
        continue  # clone_match.py --other-games covers it
    img = cm.Image(cm.ROOT, m)
    found = cm.search(img, others, None, a.j, log=lambda s, m=m: print(m, s, flush=True))
    for n, _s, _a, src, kind, frm in found:
        prof = ''
        if src.startswith(cm.am.MARKER):
            prof = src.split('\n', 1)[0][len(cm.am.MARKER):].replace('*/', '').strip()
        (out / f'{n}.c').write_text(src, encoding='utf-8')
        res[n] = {'status': 'match', 'match': True, 'profile': prof or img.default_cc, 'from': frm}
    (out / 'results.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
    print(m, 'found', len(found), 'total', len(res), flush=True)
print('total', len(res))
