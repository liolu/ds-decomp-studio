"""profsweep_one.py OUT_ROUND PROFILE [-j 6] : judge the latest agent file of every unmatched function with ONE profile.

Pokemon Dash r2 (2026-11-07): `1.2/b56` matched the refcount-release and field-pointer-add families that every other
profile missed, so every earlier near miss deserved a re-judge with it. Collects build/hunt/*/a*/NAME.c (newest file
per unmatched NAME), judges each with `workbench.py judge NAME FILE --profile PROFILE` in parallel, and copies the
matches to build/hunt/OUT_ROUND/a1/NAME.c (ready for agentround OUT_ROUND). Prints a summary. Run from the game dir."""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import hunt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('round'); ap.add_argument('profile'); ap.add_argument('-j', type=int, default=6)
a = ap.parse_args()
unmatched = set(hunt.unmatched_sizes()) - hunt.matched_names()
best = {}
for f in glob.glob('build/hunt/*/a*/*.c'):
    n = os.path.basename(f)[:-2]
    if n in unmatched and (n not in best or os.path.getmtime(f) > os.path.getmtime(best[n])):
        best[n] = f
out = Path('build/hunt') / a.round / 'a1'; out.mkdir(parents=True, exist_ok=True)
print(f'{len(best)} functions to judge with {a.profile}', flush=True)


def judge(item):
    n, f = item
    r = subprocess.run([sys.executable, str(HERE / 'workbench.py'), 'judge', n, f, '--profile', a.profile],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout[r.stdout.index('{'):])
    except ValueError:
        return n, 'error', None
    return n, d.get('status'), d.get('diffs')


hits = []
with ThreadPoolExecutor(a.j) as ex:
    for i, (n, st, df) in enumerate(ex.map(judge, sorted(best.items())), 1):
        if st == 'match':
            shutil.copy2(best[n], out / f'{n}.c'); hits.append(n)
            print(f'MATCH {n} [{i}/{len(best)}]', flush=True)
print(f'{len(hits)} matches with {a.profile}: {" ".join(hits)}')
