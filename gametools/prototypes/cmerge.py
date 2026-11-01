"""cmerge.py OUT.c FILE.c... : merge matched C files into one translation unit (for -ipa file tests): #include lines
and typedefs (deduplicated) first, then a prototype of every function defined in the set (taken from its definition;
the files' own prototypes of those functions are dropped), then the files' bodies in the given order.
Clashing typedef names between files still need a hand fix.
Technique id: whole-file-ipa (game code variant: callees in the same file let mwcc's -ipa file see which registers
they clobber). Origin: TnJ s36 (2026-10-29)."""
import re, sys

DEF = re.compile(r'^((?:static\s+)?(?:asm\s+)?[A-Za-z_][\w\s\*]*?\b(\w+)\s*\([^;{)]*\))\s*\{', re.M)


def split_top(s):
    """Top-level chunks: (kind, text) with kind include / typedef / other."""
    out, cur, depth, kind = [], [], 0, None
    for line in s.split('\n'):
        if depth == 0 and not cur:
            st = line.strip()
            kind = 'include' if st.startswith('#include') else 'typedef' if st.startswith('typedef') else 'other'
        cur.append(line)
        depth += line.count('{') - line.count('}')
        if depth == 0 and (kind != 'typedef' or line.rstrip().endswith(';')):
            out.append((kind, '\n'.join(cur)))
            cur = []
    if cur:
        out.append((kind, '\n'.join(cur)))
    return out


out, files = sys.argv[1], sys.argv[2:]
srcs = [open(f, encoding='utf-8', errors='replace').read() for f in files]
defined, protos = set(), []
for s in srcs:
    for m in DEF.finditer(s):
        defined.add(m.group(2))
        protos.append(re.sub(r'\s+', ' ', m.group(1)) + ';')
head, seen, body = [], set(), []
for f, s in zip(files, srcs):
    body.append(f'/* ---- {f} ---- */')
    for kind, text in split_top(s):
        st = text.strip()
        if kind in ('include', 'typedef'):
            if st not in seen:
                seen.add(st)
                head.append(text)
            continue
        m = re.match(r'^(?:extern\s+)?[A-Za-z_][\w\s\*]*?\b(\w+)\s*\([^{]*\)\s*;$', st)
        if m and m.group(1) in defined:
            continue
        if st.startswith('extern') or re.match(r'^[\w\s\*]+\([^{]*\);$', st):
            if st in seen:
                continue
            seen.add(st)
        body.append(text)
text = '\n'.join(head) + '\n\n' + '\n'.join(protos) + '\n\n' + '\n'.join(body) + '\n'
open(out, 'w', newline='\n').write(text)
print(f'{out}: {len(files)} files, {len(defined)} functions')
