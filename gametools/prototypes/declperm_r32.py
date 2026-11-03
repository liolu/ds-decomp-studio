"""declperm.py NAME FILE.c PROFILE [OUTPREFIX]: try every order of the leading block of plain local declarations
(consecutive lines `    type name;` at 4-space indent, no '=' and no struct) and judge each; prints the best and writes
OUTPREFIX_pN.c for each order that gives 0 diffs (or the best one)."""
import sys, re, itertools, subprocess, json, os

name, f, prof = sys.argv[1], sys.argv[2], sys.argv[3]
outp = sys.argv[4] if len(sys.argv) > 4 else os.path.splitext(f)[0] + '_dp'
here = os.path.dirname(os.path.abspath(__file__))
judge = os.path.join(here, '..', '..', '..', '..', '..', '..', 'studio', 'gametools', 'workbench.py')
text = open(f, encoding='utf8').read().replace('\r\n', '\n')
lines = text.split('\n')
decl_re = re.compile(r'^    [A-Za-z_][\w \*]*?\s\*?[A-Za-z_]\w*(\[[^\]]*\])?;$')
start = None
for i, l in enumerate(lines):
    if decl_re.match(l) and (i == 0 or not decl_re.match(lines[i - 1])):
        if start is None:
            start = i
        # first block only: collect consecutive declarations
block = []
i = start
while start is not None and i < len(lines) and decl_re.match(lines[i]):
    block.append(lines[i]); i += 1
if not block or len(block) > 6:
    print('no block or too big', len(block)); sys.exit(0)
results = []
for k, perm in enumerate(itertools.permutations(range(len(block)))):
    L = list(lines)
    L[start:start + len(block)] = [block[p] for p in perm]
    p = '%s_p%d.c' % (outp, k)
    open(p, 'w', encoding='utf8', newline='\n').write('\n'.join(L))
    r = subprocess.run(['python', judge, 'judge', name, p, '--profile', prof], capture_output=True, text=True)
    try:
        d = json.loads([x for x in r.stdout.splitlines() if x.startswith('{')][-1])
    except Exception:
        continue
    st = d.get('status'); df = d.get('diffs', 9999)
    results.append((0 if st == 'match' else df if st == 'near' else 9999, perm, p, st))
    if st == 'match':
        print('MATCH', perm, p); break
results.sort()
print('best', results[:3])



