"""shapediff.py NAME FILE.c [-p PROFILE]: register-blind side by side of the regions that differ (difflib opcodes on
normalized instructions). Run it FIRST on a near miss: a few lines = a real source error (constant, field, missing
move), many register-only diffs = allocation (then climb with varmerge/cmutate/declperm). Technique id: shape-first.
Origin: TnJ s36 (func_02006178: swapped bitfield names)."""
import sys, os, re, difflib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ['WB_FULL'] = '1'
import hunt
a = sys.argv[1:]
prof = '2.0/sp1p5'
if '-p' in a:
    i = a.index('-p'); prof = a[i + 1]; del a[i:i + 2]
name, f = a[0], a[1]
hunt._init()
def norm(l):
    l = l.split('@')[0]
    l = re.sub(r'\b(r\d+|sl|fp|ip|lr|sp|pc)\b', 'R', l)
    l = re.sub(r'0x[0-9a-f]+', 'A', l)
    return l.strip()
r = hunt._judge((name, open(f, encoding='utf-8', errors='replace').read(), prof))
full = r['full']; T, C = full['t'], full['c']
sm = difflib.SequenceMatcher(None, [norm(x) for x in T], [norm(x) for x in C], autojunk=False)
for op, a0, a1, b0, b1 in sm.get_opcodes():
    if op == 'equal': continue
    print(f'--- {op} T{a0}-{a1} C{b0}-{b1}')
    for k in range(max(a1 - a0, b1 - b0)):
        x = T[a0 + k] if a0 + k < a1 else ''
        y = C[b0 + k] if b0 + k < b1 else ''
        print(f'   {x.split("@")[0].strip():38} | {y.split("@")[0].strip()}')
sys.stdout.flush(); os._exit(0)
