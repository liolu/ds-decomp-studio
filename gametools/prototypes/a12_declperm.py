"""declperm.py NAME FILE.c [-p PROFILE] [-o OUTDIR] : try every order of the plain local declarations
(`type name;` lines at the top of the function body, up to 6) and judge each with workbench.
Writes the variants to OUTDIR (default: the file's folder, as perm_NN.c) and prints diff counts, best first.
Run from the project dir."""
import sys, os, re, itertools, subprocess
a = sys.argv[1:]
if len(a) < 2:
    sys.exit(__doc__)
name, path = a[0], a[1]
prof = '1.2/sp2p3'
out = os.path.dirname(os.path.abspath(path))
if '-p' in a:
    prof = a[a.index('-p') + 1]
if '-o' in a:
    out = a[a.index('-o') + 1]
os.makedirs(out, exist_ok=True)
src = open(path).read().split('\n')
head = None
for i, ln in enumerate(src):
    if re.match(r'^[A-Za-z_].*\(.*\)\s*\{\s*$', ln) and not ln.startswith('#'):
        head = i
        break
if head is None:
    sys.exit('no function header found')
decl_re = re.compile(r'^\s+[A-Za-z_][\w\s\*]*?\s\**[A-Za-z_]\w*(\[\d+\])?;\s*$')
j = head + 1
decls = []
while j < len(src) and decl_re.match(src[j]) and not src[j].strip().startswith('return'):
    decls.append(j)
    j += 1
if not decls or len(decls) > 6:
    sys.exit(f'{len(decls)} plain declarations: nothing to permute (1..6 needed)')
lines = [src[k] for k in decls]
results = []
n = 0
for perm in itertools.permutations(range(len(decls))):
    if list(perm) == list(range(len(decls))):
        continue
    new = list(src)
    for slot, k in zip(decls, perm):
        new[slot] = lines[k]
    p = os.path.join(out, f'perm_{n:02d}.c')
    n += 1
    open(p, 'w').write('\n'.join(new))
    o = subprocess.run([sys.executable, '-m', 'x'] if False else ['python', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'workbench.py'), 'judge', name, p, '--profile', prof], capture_output=True, text=True).stdout
    m = re.search(r'"status": "(\w+)".*?"diffs": (\w+)', o)
    st, df = (m.group(1), m.group(2)) if m else ('?', '?')
    results.append((0 if st == 'match' else (int(df) if df.isdigit() else 999), st, df, p))
    if st == 'match':
        print('MATCH', p)
        break
results.sort()
for r in results[:5]:
    print(r[1], r[2], r[3])
