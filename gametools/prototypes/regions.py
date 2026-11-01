"""regions.py NAME FILE.c CUT1,CUT2,... [-p PROFILE] : where is a big function still wrong? Splits the TARGET listing
at the given instruction indexes and counts the shape mismatches (registers masked) in each region, printing every
non-equal block. Work on the worst region first. Technique id: region-diff. Origin: TnJ build/hunt/w/regions.py."""
import difflib, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['WB_FULL'] = '1'
import hunt  # noqa: E402
from mscore import norm  # noqa: E402

a = sys.argv[1:]
prof = '2.0/sp1p5'
if '-p' in a:
    i = a.index('-p'); prof = a[i + 1]; del a[i:i + 2]
name, f = a[0], a[1]
cuts = sorted({0} | {int(x) for x in a[2].split(',')}) if len(a) > 2 else [0]
hunt._init()
r = hunt._judge((name, open(f, encoding='utf-8', errors='replace').read(), prof))
T = [norm(x) for x in r['full']['t']]; C = [norm(x) for x in r['full']['c']]
sm = difflib.SequenceMatcher(None, T, C, autojunk=False)
cnt = [0] * len(cuts)
for op, a0, a1, b0, b1 in sm.get_opcodes():
    if op == 'equal': continue
    k = max(i for i, c in enumerate(cuts) if c <= a0)
    cnt[k] += max(a1 - a0, b1 - b0)
    print(op, 't[%d:%d]' % (a0, a1), 'c[%d:%d]' % (b0, b1), T[a0:a1][:4], C[b0:b1][:4])
print(dict(zip(cuts, cnt)))
sys.stdout.flush(); os._exit(0)
