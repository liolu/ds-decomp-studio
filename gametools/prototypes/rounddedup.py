"""rounddedup.py ROUND : before agentround, keep only the best NAME.c of a name written by several agents (r32).

agentround copies the FIRST NAME.c per name in dir order (a1, a10, a11...), so a near miss in a33 hides the match
in a39. For every name with copies in several ROUND/aK/ dirs, judges each copy with fj.py (all profiles agents use),
keeps the best one (match, else fewest diffs) and moves the others to aK/v/shadow/. Also moves ROUND dirs that are
not agent dirs (o2/, ...) out of the way into ROUND_aside/ (agentround reads every dir of ROUND). Run from the game dir."""
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import hunt  # noqa: E402

R = Path(sys.argv[1])
PROFILES = ('1.2/sp3,1.2/sp2p3,2.0/sp1p5 -profile,1.2/sp3 -profile,1.2/sp2p3 -profile,1.2/sp2p3 -thumb,1.2/sp3 -thumb,'
            '2.0/sp1p5 -thumb,1.2/sp3 -O2,p,2.0/sp1p5 -O2,p,1.2/sp3 -proc arm7tdmi')
unmatched = set(hunt.unmatched_sizes()) - hunt.matched_names()
for d in list(R.iterdir()):
    if d.is_dir() and not (d.name[0] == 'a' and d.name[1:].isdigit()) and d.name not in ('all', 'ovl', '_aside'):
        (R.parent / f'{R.name}_aside').mkdir(exist_ok=True)
        shutil.move(str(d), str(R.parent / f'{R.name}_aside' / d.name))
copies = defaultdict(list)
for d in sorted(p for p in R.iterdir() if p.is_dir() and p.name[0] == 'a' and p.name[1:].isdigit()):
    for f in d.glob('*.c'):
        if f.stem in unmatched:
            copies[f.stem].append(f)
dups = {n: fs for n, fs in copies.items() if len(fs) > 1}
print(len(copies), 'names,', len(dups), 'written by several agents')
J = R.parent / f'{R.name}_aside' / '_dedup'
groups = defaultdict(list)  # copy index -> names
for n, fs in dups.items():
    for i, f in enumerate(fs):
        (J / str(i)).mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, J / str(i) / f.name)
        groups[i].append(n)
env = dict(os.environ, AUTO_EXTRA_PROFILES=PROFILES)
score = {}
for i, names in groups.items():
    subprocess.run([sys.executable, str(HERE / 'fj.py'), str(J / str(i)), '-j', '6', '--fresh'] + names, env=env,
                   stdout=subprocess.DEVNULL)
    res = json.loads((J / str(i) / 'results.json').read_text(encoding='utf-8-sig'))
    for n in names:
        r = res.get(n) or {}
        k = r.get('k') or [9e9, 9e9]
        score[(n, i)] = (0 if r.get('status') == 'match' else 1, k[1])
moved = 0
for n, fs in dups.items():
    best = min(range(len(fs)), key=lambda i: score.get((n, i), (2, 9e9)))
    for i, f in enumerate(fs):
        if i != best:
            sh = f.parent / 'v' / 'shadow'; sh.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(sh / f.name)); moved += 1
    if score.get((n, best), (2,))[0] == 0:
        print('match kept', n, fs[best].parent.name)
print(moved, 'copies moved to v/shadow')
