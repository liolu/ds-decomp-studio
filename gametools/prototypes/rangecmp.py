"""rangecmp.py FILE.c START [PROFILE flags...] : compile FILE.c (2.0/sp1p5 game flags), concatenate its .text and
compare it word by word with the ROM from START (hex). Words with a relocation are compared on opcode bits only
(branches) or skipped (data). Prints each function symbol's offset and every differing word.
Run from projets/<game> after `source ../../env.sh`. Technique ids: whole-file-ipa, runtime-asm-split.
Why: the judge works on one function; a whole SDK file (statics + -ipa file) or a set of contiguous asm entry points
must be compared as one range. Origin: TnJ s36 (2026-10-29): snd_command.c (16 functions) and the runtime routines."""
import os, re, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import probe_compiler as pc  # noqa: E402

args = sys.argv[1:]
only = None  # --func NAME: compare only that function (at START), the other functions of the file are context
if '--func' in args:
    i = args.index('--func'); only = args[i + 1]; del args[i:i + 2]
quiet = '-q' in args
args = [a for a in args if a != '-q']
src, start = args[0], int(args[1], 16)
extra = args[2:]
cc = './sjiswrap.exe'
mw = './../../tools/mwccarm/2.0/sp1p5/mwccarm.exe'
flags = ('-O4,p -enum int -char signed -str noreuse -proc arm946e -gccext,on -fp soft -inline noauto -Cpp_exceptions off '
         '-RTTI off -interworking -w off -sym on -gccinc -nolink -msgstyle gcc -i include -lang=c').split()
obj = 'build/hunt/rangecmp_rc.o'
r = subprocess.run([cc, mw] + flags + extra + ['-c', src, '-o', obj], capture_output=True, text=True)
if r.returncode:
    print(r.stdout, r.stderr); sys.exit(1)
subprocess.run(['arm-none-eabi-ld', '-r', '-o', 'build/hunt/rangecmp_rcm.o', obj], check=True)
obj = 'build/hunt/rangecmp_rcm.o'
dump = subprocess.run(['arm-none-eabi-objcopy', '-O', 'binary', '-j', '.text', obj, 'build/hunt/rangecmp_rc.bin'])
data = open('build/hunt/rangecmp_rc.bin', 'rb').read()
syms = subprocess.run(['arm-none-eabi-nm', '-n', obj], capture_output=True, text=True).stdout
relo = subprocess.run(['arm-none-eabi-objdump', '-r', '-j', '.text', obj], capture_output=True, text=True).stdout
rel = {}
for line in relo.splitlines():
    m = re.match(r'^([0-9a-f]{8})\s+(\S+)\s+(\S+)', line)
    if m:
        rel[int(m.group(1), 16)] = (m.group(2), m.group(3))
funcs = []
for line in syms.splitlines():
    p = line.split()
    if len(p) == 3 and p[1] in 'Tt':
        funcs.append((int(p[0], 16), p[2]))
lo, hi = 0, len(data)
if only:
    offs = [o for o, n in funcs if n == only]
    if not offs:
        print(f'{only} not in {src}'); sys.exit(1)
    lo = offs[0]
    hi = min([o for o, n in funcs if o > lo] + [len(data)])
    start -= lo  # START is the function's own address
elif not quiet:
    for o, n in funcs:
        print(f'  {n:30} +0x{o:x} = 0x{start + o:08x}')
tgt = pc.target_bytes(start, len(data))
bad = 0
for off in range(lo, hi, 4):
    a = int.from_bytes(data[off:off + 4], 'little')
    b = int.from_bytes(tgt[off:off + 4], 'little')
    if off in rel:
        kind, sym = rel[off]
        if 'CALL' in kind or 'JUMP' in kind or 'PC24' in kind:
            if (a >> 24) != (b >> 24):
                bad += 1; print(f'  DIFF +0x{off:x} op {a:08x} vs {b:08x} ({sym})')
            elif not quiet:
                print(f'  reloc +0x{off:x} {sym} -> target word {b:08x}')
        continue
    if a != b:
        bad += 1
        if not quiet:
            print(f'  DIFF +0x{off - lo:x} {a:08x} vs {b:08x}')
print(f'{src}{" " + only if only else ""}: {hi - lo} bytes, {bad} diffs')
