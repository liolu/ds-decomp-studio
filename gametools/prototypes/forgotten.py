"""forgotten.py [--out DIR] [--profiles P1,P2,...] : find matches that were never submitted.

Run from the game dir. For every function still unmatched, reads its techlog journal (build/hunt/techlog/NAME.md), takes
every file named on a line that reports `0 diffs`, and judges it under several profiles (default, -thumb, -nointerworking,
1.2/sp3, 2.0/sp1p5). A judge match that relcheck also calls SAME is copied to OUT (default build/hunt/forgotten/) and
listed in OUT/results.json with its profile, ready for `workbench.py submit-many OUT`.

Why: confirm scripts judged only the default profile, so Thumb / -nointerworking matches announced by agents were
dropped (Sims 2 2026-11-27: func_020d1040 -thumb from r38, func_02037184 from r11). Technique id: forgotten-match.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hunt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--out', default='build/hunt/forgotten')
ap.add_argument('--profiles', default='1.2/sp2p3,1.2/sp2p3 -thumb,1.2/sp2p3 -nointerworking,1.2/sp3,2.0/sp1p5')
a = ap.parse_args()
profiles = [p.strip() for p in a.profiles.split(',') if p.strip()]
un = set(hunt.unmatched_sizes()) - hunt.matched_names()
hunt._init()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
res = {}
G = Path(__file__).resolve().parents[1]
for jf in sorted(glob.glob('build/hunt/techlog/*.md')):
    name = os.path.basename(jf)[:-3]
    if name not in un:
        continue
    files = []
    for line in open(jf, encoding='utf-8', errors='replace'):
        if not re.search(r'\|\s*0 diffs\s*\|', line):
            continue
        for f in re.findall(r'(build/hunt/\S+?\.c)\b', line):
            if os.path.exists(f) and f not in files:
                files.append(f)
    done = False
    for f in files:
        src = Path(f).read_text(encoding='utf-8', errors='replace')
        for p in profiles:
            r = hunt._judge((name, src, p))
            if not r.get('match'):
                continue
            rel = subprocess.run([sys.executable, str(G / 'relcheck.py'), name, f, p], capture_output=True, text=True)
            last = (rel.stdout.strip().splitlines() or [''])[-1]
            print(f'{name} {p!r} {f} relcheck={last}', flush=True)
            if last == 'SAME':
                shutil.copy(f, out / f'{name}.c')
                res[name] = {'match': True, 'profile': p, 'status': 'match', 'diffs': 0}
                done = True
                break
        if done:
            break
(out / 'results.json').write_text(json.dumps(res, indent=1))
print(f'{len(res)} forgotten matches in {out}', flush=True)
os._exit(0)
