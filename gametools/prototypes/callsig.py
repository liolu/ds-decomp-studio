"""callsig.py [NAME...] : parameter / return types of unmatched functions as their callers' machine code shows them.
Before every `bl NAME` in build/<ver>/asm: `and rN, x, #0xff` = u8 argument N, `lsr rN, x, #0x10` (after lsl #16) =
u16, `asr rN, x, #0x10` = s16; right after it, a read of r0 = a return value; `lsl r0 #16`/`and r0 #0xff` there = the CALLER
truncates, so the callee returns a wider type (int) into a u16/u8 variable. Compare with the draft's signature: a wrong one changes the callee's code (TnJ s36: func_02012e28's k
is u16 (callee returns u16), the B-spline helpers take (u8 idx, u16 i, s32 t): exact size at once).
Run from projets/<game>; no NAME = every unmatched function. Technique id: caller-signature."""
import glob, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def main():
    names = sys.argv[1:]
    if not names:
        import hunt
        names = sorted(hunt.unmatched_sizes())
    texts = [open(f, errors='replace').read().split('\n') for f in glob.glob('build/*/asm/**/*.s', recursive=True)]
    for n in names:
        args, rets, calls = set(), set(), 0
        for t in texts:
            for i, l in enumerate(t):
                if not re.search(r'\bbl\s+' + re.escape(n) + r'\b', l):
                    continue
                calls += 1
                for p in (x.strip() for x in t[max(0, i - 6):i]):
                    for pat, ty in ((r'^and\s+(r[0-3]),\s*\w+,\s*#0xff$', 'u8'), (r'^lsr\s+(r[0-3]),\s*\w+,\s*#0x10$', 'u16'),
                                    (r'^asr\s+(r[0-3]),\s*\w+,\s*#0x10$', 's16')):
                        m = re.match(pat, p)
                        if m:
                            args.add(f'{m.group(1)}:{ty}')
                for p in (x.strip() for x in t[i + 1:i + 4]):
                    if p.startswith(('bl', 'b ', 'pop', 'bx')) or p.endswith(':'):
                        break
                    if re.match(r'^(lsl|and)\w*\s+\w+,\s*r0,\s*#(0x10|0xff)$', p):
                        rets.add('u16/s16' if '0x10' in p else 'u8')
                        break
                    ops = p.split(None, 1)[1] if ' ' in p else ''
                    dst, _, srcs = ops.partition(',')
                    if re.search(r'\br0\b', srcs) or (p.startswith(('cmp', 'tst', 'str')) and re.search(r'\br0\b', ops)):
                        rets.add('used')
                        break
                    if dst.strip() == 'r0':
                        break
        if calls:
            print(f'{n:28} calls={calls:3} args={",".join(sorted(args)) or "-"} return={",".join(sorted(rets)) or "-"}')
    sys.stdout.flush(); os._exit(0)


if __name__ == '__main__':
    main()
