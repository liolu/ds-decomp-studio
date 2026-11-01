"""mscore.py NAME FILE.c... [-p PROFILE] : rank variants by mnemonic+shape mismatches with registers, addresses and
offsets masked (in-process judge). Use it on big functions where the diff count is drowned by register swaps: it
shows whether the STRUCTURE is right. Technique id: shape-score. Origin: TnJ build/hunt/w/mscore.py (r26-r28)."""
import difflib, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['WB_FULL'] = '1'
import hunt  # noqa: E402


def norm(l):
    l = l.split('@')[0]
    l = re.sub(r'\b(r\d+|sl|fp|ip|lr|sp|pc)\b', 'R', l)
    l = re.sub(r'0x[0-9a-f]+', 'A', l)
    l = re.sub(r'\[R, #\d+\]', '[R,#N]', l)
    return l.strip()


def shape_diffs(r):
    full = r.get('full')
    if not full: return 0 if r.get('match') else 99999
    T = [norm(x) for x in full['t']]; C = [norm(x) for x in full['c']]
    sm = difflib.SequenceMatcher(None, T, C, autojunk=False)
    return sum(max(a1 - a0, b1 - b0) for op, a0, a1, b0, b1 in sm.get_opcodes() if op != 'equal')


if __name__ == '__main__':
    a = sys.argv[1:]
    prof = '2.0/sp1p5'
    if '-p' in a:
        i = a.index('-p'); prof = a[i + 1]; del a[i:i + 2]
    name, files = a[0], a[1:]
    hunt._init()
    res = []
    for f in files:
        r = hunt._judge((name, open(f, encoding='utf-8', errors='replace').read(), prof))
        res.append((shape_diffs(r), f, r.get('diffs'), r.get('size')))
    for x in sorted(res)[:15]:
        print(x[0], os.path.basename(x[1]), 'diffs', x[2], 'size', x[3])
    sys.stdout.flush(); os._exit(0)
