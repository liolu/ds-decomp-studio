"""o2sweep.py ROUND [--per 60] : judge the NAME.c files of a round's agents with the -O2,p profiles only (r32).

Agents rarely try -O2,p; func_ov115_020e49f4, func_ov117_020ecbe4 and func_ov123_020c45cc go from a size miss to a near
miss with it. Copies each still unmatched ROUND/a*/NAME.c into ROUND/o2/ and judges PER of them per call with fj.py -j 3
(run again for the next ones: the names done are in ROUND/o2/results.json). Short by design, no sweep of everything.
Run from the game dir. Prints the matches and the near misses."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import hunt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('round'); ap.add_argument('--per', type=int, default=60)
a = ap.parse_args()

R = Path('build/hunt') / a.round; O = R / 'o2'; O.mkdir(exist_ok=True)
unmatched = set(hunt.unmatched_sizes()) - hunt.matched_names()
RES = O / 'results.json'
seen = set(json.loads(RES.read_text(encoding='utf-8-sig'))) if RES.exists() else set()
todo = []
for f in sorted(R.glob('a*/*.c')):
    n = f.stem
    if n in unmatched and n not in seen and n not in todo:
        shutil.copy(f, O / f.name)
        todo.append(n)
print(len(todo), 'left, judging', min(len(todo), a.per))
env = dict(os.environ, AUTO_EXTRA_PROFILES='2.0/sp1p5 -O2,p,1.2/sp3 -O2,p,1.2/sp2p3 -O2,p')
subprocess.run([sys.executable, str(HERE / 'fj.py'), str(O), '-j', '3'] + todo[:a.per], env=env, timeout=110)
res = json.loads(RES.read_text(encoding='utf-8-sig'))
for n in todo[:a.per]:
    r = res.get(n) or {}
    if r.get('status') == 'match' or (r.get('status') == 'near' and '-O2' in r.get('profile', '')):
        print(n, r.get('status'), r.get('profile'), (r.get('k') or [0, 0])[1])
