"""templatesweep.py TEMPLATE.c TEMPLATE_NAME OUT_ROUND PROFILE [--sizes 88,92] [-j 6] : try one matched C body on every
unmatched function of the same size(s), renamed.

Pokemon Dash r2 (2026-11-07): the list-init family (28 B, `return l;` + 1.2/b56) and the refcount-release family
(92 B, `R **f(R **p)` + 1.2/b56) are copy-paste code: one solved file matched 21 and 16+ clones once renamed. Writes
each candidate to build/hunt/OUT_ROUND/try/NAME.c, judges it with PROFILE, copies matches to OUT_ROUND/a1/NAME.c
(ready for agentround). Sizes default to the template function's size. Run from the game dir."""
import argparse
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import hunt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('template'); ap.add_argument('name'); ap.add_argument('round'); ap.add_argument('profile')
ap.add_argument('--sizes', default=''); ap.add_argument('-j', type=int, default=6)
a = ap.parse_args()
src = Path(a.template).read_text(encoding='utf-8-sig')
sizes_all = hunt.unmatched_sizes(); matched = hunt.matched_names()
sizes = {int(x) for x in a.sizes.split(',') if x} or {sizes_all[a.name]}
R = Path('build/hunt') / a.round; out = R / 'a1'; tri = R / 'try'
out.mkdir(parents=True, exist_ok=True); tri.mkdir(parents=True, exist_ok=True)
names = sorted(n for n, z in sizes_all.items() if z in sizes and n not in matched and not (out / f'{n}.c').exists())
print(f'{len(names)} candidates of size {sorted(sizes)}', flush=True)


def judge(n):
    f = tri / f'{n}.c'
    f.write_text(re.sub(rf'\b{re.escape(a.name)}\b', n, src), encoding='utf-8')
    r = subprocess.run([sys.executable, str(HERE / 'workbench.py'), 'judge', n, str(f), '--profile', a.profile],
                       capture_output=True, text=True)
    try:
        return n, json.loads(r.stdout[r.stdout.index('{'):]).get('status')
    except ValueError:
        return n, 'error'


hits = []
with ThreadPoolExecutor(a.j) as ex:
    for n, st in ex.map(judge, names):
        if st == 'match':
            shutil.copy2(tri / f'{n}.c', out / f'{n}.c'); hits.append(n); print('MATCH', n, flush=True)
print(f'{len(hits)} matches: {" ".join(hits)}')
