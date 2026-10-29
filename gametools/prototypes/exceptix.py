"""exceptix.py TABLE_START TABLE_END [HEADER_SIZE] : (from projets/<game>) for every source file owning an entry of the
C++ exception index table (the linker's EXCEPTION output), compile it with
-Cpp_exceptions on and compare its .exceptix entries (size word, action word) and .exception records with the target,
and its .text with the -Cpp_exceptions off build. All OK -> add -Cpp_exceptions on to compilers.txt, the
.exception/.exceptix sections to the delinks header and per-file ranges (12 B/entry, 8 B/record). Technique id:
exceptix. Origin: TnJ s36 (data_02063a48, 55 files)."""
import os, re, struct, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import probe_compiler as pc

TBL, TBL_END = int(sys.argv[1], 16), int(sys.argv[2], 16)
HDR = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x20
b = pc.target_bytes(TBL, TBL_END - TBL)
ex_hdr = b[:HDR]
ents = [struct.unpack_from('<III', b, o) for o in range(HDR, len(b) - 11, 12)]
files, cur = [], None
for l in open('config/eu/arm9/delinks.txt'):
    m = re.match(r'^(\S+\.(?:c|cpp|s)):', l)
    if m: cur = m.group(1); continue
    m = re.match(r'^\s+\.text\s+start:0x(\w+) end:0x(\w+)', l)
    if m and cur: files.append((int(m.group(1), 16), int(m.group(2), 16), cur))
comp = {}
for l in open('config/eu/compilers.txt'):
    p = l.split('#')[0].split()
    if p: comp[p[0]] = (p[1], ' '.join(p[2:]))
BASE = ('-O4,p -enum int -char signed -str noreuse -proc arm946e -gccext,on -fp soft -inline noauto -RTTI off '
        '-interworking -w off -sym on -gccinc -nolink -msgstyle gcc -i include -lang=c').split()


def build(f, exc):
    v, x = comp.get(f, ('2.0/sp1p5', ''))
    o = f'build/hunt/s36/exo/{os.path.basename(f)}.{exc}.o'
    os.makedirs('build/hunt/s36/exo', exist_ok=True)
    r = subprocess.run(['./sjiswrap.exe', f'../../tools/mwccarm/{v}/mwccarm.exe'] + BASE + ['-Cpp_exceptions', exc] + x.split()
                       + ['-c', f, '-o', o], capture_output=True, text=True)
    if r.returncode: return None
    subprocess.run(['arm-none-eabi-ld', '-r', '-o', o + '.m', o], check=True)
    return o + '.m'


def sect(o, name):
    p = o + name.replace('.', '_') + '.bin'
    subprocess.run(['arm-none-eabi-objcopy', '-O', 'binary', '-j', name, o, p], capture_output=True)
    return open(p, 'rb').read() if os.path.exists(p) else b''


owner = {}
for a, ln, act in ents:
    f = next((f for s, e, f in files if s <= a < e), None)
    owner.setdefault(f, []).append((a, ln, act))
ok = 0
order = []
for f, es in owner.items():
    on, off = build(f, 'on'), build(f, 'off')
    if not on or not off:
        print('COMPILE', f); continue
    tx_on, tx_off = sect(on, '.text'), sect(off, '.text')
    exx = sect(on, '.exceptix'); exn = sect(on, '.exception')
    got = [struct.unpack_from('<III', exx, o)[1:] for o in range(0, len(exx), 12)]
    want = [(ln, act) for a, ln, act in es]
    acts = [act for a, ln, act in es if TBL <= act < TBL + HDR]
    want_cmp = [(ln, 0 if TBL <= act < TBL + HDR else act) for ln, act in want]
    got_cmp = [(ln, 0 if exn and act < 0x100 else act) for ln, act in got]
    exn_ok = all(ex_hdr[a - TBL:a - TBL + 8] == exn[:8] for a in acts) if acts else not exn
    good = tx_on == tx_off and want_cmp == got_cmp and exn_ok
    ok += good
    print(('OK  ' if good else 'BAD ') + f, 'text' if tx_on == tx_off else 'TEXT-DIFF', want, got, exn.hex() if exn else '')
print(ok, '/', len(owner))
