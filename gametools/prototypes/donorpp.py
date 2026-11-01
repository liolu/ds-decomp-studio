"""donorpp.py EXP.c KEEP OUT.c [old=new ...] : turn a donor source file, already run through the C preprocessor with
the donor's own headers (`arm-none-eabi-cpp -P -nostdinc -I<stub> -I<donor includes> -D__MWERKS__ donor.c -o EXP.c`),
into a candidate for ONE function: keep KEEP (and static inline helpers), turn every other function into a prototype
(static dropped, so the game's own matched copies are called), strip #pragma / __attribute__ / __declspec (refused by
fakematch), rename donor identifiers to the game's symbols (old=new, e.g. strlen=func_0205bfd4).
Why: donor_match only tries clean single functions; real SDK/MSL donors need their macros, enums and inline helpers.
Then: judge every 2.0 compiler build (TnJ MSL/OS printf were built with 2.0/sp1p2), point string literals / static
tables at the game's data symbols (extern), or let the file own that rodata/.data range (local sized @ symbols).
Technique id: donor-preprocess. Origin: TnJ s31 (2026-10-29): __strtold, __pformatter, __dec2num, __ieee754_pow,
MakeWaveData, longlong2str, OS_VSNPrintf matched this way."""
import re, sys
src, keep, out = sys.argv[1], sys.argv[2], sys.argv[3]
ren = [a.split('=', 1) for a in sys.argv[4:]]
s = open(src).read()
s = '\n'.join(l for l in s.split('\n') if not l.strip().startswith('#pragma'))
def strip_kw(s, kw):
    while True:
        i = s.find(kw)
        if i < 0: return s
        j = s.index('(', i); d = 0; k = j
        while True:
            if s[k] == '(': d += 1
            elif s[k] == ')':
                d -= 1
                if d == 0: break
            k += 1
        s = s[:i] + s[k + 1:]
s = strip_kw(strip_kw(s, '__attribute__'), '__declspec')
pat = re.compile(r'^[ 	]*(?:static\s+)?(?:inline\s+)?[A-Za-z_][\w\s\*]*?\b(\w+)\s*\(([^;{]*?)\)\s*\{', re.M)
o = []; pos = 0
for m in pat.finditer(s):
    if m.start() < pos: continue
    name = m.group(1)
    depth = 0; j = m.end() - 1
    while True:
        if s[j] == '{': depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0: break
        j += 1
    o.append(s[pos:m.start()])
    head = s[m.start():m.end() - 1].rstrip()
    if name == keep:
        o.append(re.sub(r'^static\s+', '', s[m.start():j + 1]))
    elif 'inline' in head and not re.search(r'\basm\b', s[m.start():j + 1]):
        o.append(s[m.start():j + 1])
    else:
        o.append(re.sub(r'^static\s+', '', head) + ';')
    pos = j + 1
o.append(s[pos:])
t = ''.join(o)
t = re.sub(r'^static(\s+[^;(]*\b%s\s*\()' % re.escape(keep), r'\1', t, flags=re.M)
# second pass: a function body that still contains inline asm (an SDK inline helper the first pass skipped) -> prototype
while True:
    am = re.search(r'\basm\b', t)
    if not am:
        break
    heads = [m for m in pat.finditer(t) if m.start() < am.start()]
    if not heads:
        break
    m = heads[-1]
    depth = 0; j = m.end() - 1
    while True:
        if t[j] == '{': depth += 1
        elif t[j] == '}':
            depth -= 1
            if depth == 0: break
        j += 1
    head = re.sub(r'^\s*static\s+', '', t[m.start():m.end() - 1].rstrip()).replace('inline ', '')
    t = t[:m.start()] + head + ';' + t[j + 1:]
for a, b in ren:
    t = re.sub(r'\b%s\b' % re.escape(a), b, t)
open(out, 'w').write(t)
