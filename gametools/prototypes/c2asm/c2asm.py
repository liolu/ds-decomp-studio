"""c2asm.py - "phrasebook" C idiom -> asm, then look the idioms up in a game's unmatched functions.

    cd projets/<game>            (or All-nds-decomp-games/games/<L>/<game>)
    python <studio>/gametools/prototypes/c2asm/c2asm.py [--all] [--sweep] [--cc auto] [--min-files 3]

1. expands the patterns (patterns.c, patterns_cpp.cpp; `// @p NAME: description` above each `p_NAME`) and
   compiles them with every setting of the game (see below);
2. disassembles them and keeps each function's body (no push/pop/bx lr) as a normalised signature
   (registers -> R, branches -> L, calls -> CALL, pool loads -> POOL, immediates as numbers);
3. scans every function below 100 % in build/<ver>/report.json (--all: every function, to check the idioms on
   matched C) and lists where each signature appears: exact, same shape (constants loose), spread (other
   instructions in between). Each hit names the setting that produced it: a hint for the function's profile.
Writes <out>/phrasebook.md (C -> asm per idiom and setting), <out>/hits.md and hits.json.

Settings (what the patterns are compiled with), one label each, e.g. `1.2/sp2p3 -O4,s`:
  * --cc auto (default): every (compiler, cc_extra) pair build.ninja gives to at least --min-files files;
  * --sweep: plus SWEEP (common flags of the other DS games) on top of each compiler of the game;
  * --cc 2.0/sp1p5 or --cc "1.2/sp2p3 -O4,s": just that one.
Parameters in the patterns: lines `// @vary T: s32 u16 s8` (one or more, any names) right below
`// @p NAME: ...`; the function uses `@T`; every combination becomes its own idiom NAME_<values>
(expanded sources in <out>/gen).
Prototype 2026-11-27 (Sims 2, Pokemon Dash).
"""
import argparse
import collections
import itertools
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OBJDUMP = 'arm-none-eabi-objdump'
REG = r'(?:r1[0-5]|r\d|fp|ip|sl|sb)'
CC_BASES = {'b', 'bl', 'bx', 'mov', 'mvn', 'add', 'sub', 'rsb', 'and', 'orr', 'eor', 'bic', 'cmp', 'cmn', 'tst',
            'ldr', 'str', 'ldrb', 'strb', 'ldrh', 'strh', 'ldrsb', 'ldrsh', 'pop', 'push', 'ldm', 'stm'}
SKIP = re.compile(r'^(push|pop|stmdb\s+sp!|ldmia\s+sp!|bx\s+lr|stmfd|ldmfd)\b')
ADDRS = {}  # pattern name -> address of each kept instruction (loops.py needs branch targets)
SOURCES = [('patterns.c', 'c'), ('patterns_cpp.cpp', 'c++')]
GEN = None  # folder of the expanded sources, set by generate()
# flags seen in the compilers.txt of the other DS games (2026-11-27 census), tried by --sweep
SWEEP = ['-O4,s', '-O2,p', '-O1,p', '-thumb', '-profile', '-nointerworking', '-proc arm7tdmi',
         '-O4,p -lang c99 -ipa file -inline on,noauto', '-O4,p -lang c99 -inline on,noauto',
         '-flag no-opt_rebuildconditionals', '-flag no-opt_common_subs']


# ---------------------------------------------------------------- game build settings

def game_flags(game):
    text = (game / 'build.ninja').read_text(encoding='utf-8', errors='replace').replace('$\n', ' ')
    m = re.search(r'rule mwcc\s+command\s*=\s*(.*)', text)
    flags = m.group(1).split('"$cc"', 1)[1]
    flags = re.split(r'\$cc_flags', flags)[0]
    out, skip = [], False
    for t in flags.split():
        if skip:
            skip = False
            continue
        if t in ('-i', '-d'):
            skip = True
            continue
        if t in ('-MD', '-c', '-nolink') or t.startswith('-msgstyle') or t == 'gcc':
            continue
        out.append(t)
    return out


def ninja_settings(game):
    """Counter {(compiler, cc_extra): files} read from build.ninja."""
    text = (game / 'build.ninja').read_text(encoding='utf-8', errors='replace').replace('$\n', ' ')
    count = collections.Counter()
    for blk in re.split(r'\n(?=build )', text):
        if not re.match(r'build [^:]+: mwcc ', blk):
            continue
        cc = re.search(r'\n\s+cc = (\S+)', blk)
        ex = re.search(r'\n\s+cc_extra = ([^\n]*)', blk)
        m = re.search(r'mwccarm[\\/](\d\.\d)[\\/](\w+)[\\/]mwccarm', cc.group(1)) if cc else None
        if m:
            count[(f'{m.group(1)}/{m.group(2)}', ' '.join((ex.group(1) if ex else '').split()))] += 1
    return count


def game_settings(game, cc='auto', sweep=False, min_files=3):
    """[(label, compiler, extra flags)], most used first."""
    if cc != 'auto':
        prof, _, extra = cc.partition(' ')
        return [(cc, prof, extra.strip())]
    count = ninja_settings(game)
    if not count:  # no per-file blocks in build.ninja: compilers.txt
        for f in (game / 'config').glob('*/compilers.txt'):
            for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
                parts = line.split()
                if len(parts) >= 2 and re.fullmatch(r'\d\.\d/\w+', parts[1]):
                    count[(parts[1], ' '.join(parts[2:]))] += 1
    out = [(f'{p} {e}'.strip(), p, e) for (p, e), n in count.most_common() if n >= min_files]
    if sweep:
        seen = {lab for lab, _, _ in out}
        for p in list(dict.fromkeys(p for _, p, _ in out)):
            for e in SWEEP:
                if '-ipa' in e and p.startswith('1.'):  # -ipa only exists on 2.0 compilers
                    continue
                if f'{p} {e}' not in seen:
                    out.append((f'{p} {e}', p, e))
                    seen.add(f'{p} {e}')
    return out or [('2.0/sp1p5', '2.0/sp1p5', '')]


def game_profiles(game, cc):
    """the compiler profiles only (older callers)."""
    return list(dict.fromkeys(p for _, p, _ in game_settings(game, cc)))


def find_mwcc(game, cc):
    # projets/<game> -> ../../tools ; All-nds-decomp-games/games/<L>/<game> -> the workspace's tools/
    for d in [game] + list(game.parents):
        exe = d / 'tools' / 'mwccarm' / cc / 'mwccarm.exe'
        if exe.exists():
            return exe
    sys.exit(f'no mwccarm {cc} above {game}')


# ---------------------------------------------------------------- patterns

OPNAMES = {'<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge', '==': 'eq', '!=': 'ne', '&': 'and', '|': 'or', '^': 'xor',
           '+': 'add', '-': 'sub', '*': 'mul', '/': 'div', '%': 'mod', '<<': 'shl', '>>': 'shr'}


def expand(text):
    """`// @vary X: a b c` lines under `// @p NAME: desc` -> one copy of the function per combination."""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r'//\s*@p\s+(\w+):\s*(.*)', lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        name, desc = m.group(1), m.group(2)
        i += 1
        vary = []
        while i < len(lines) and re.match(r'//\s*@vary\s', lines[i]):
            v = re.match(r'//\s*@vary\s+(\w+):\s*(.*)', lines[i])
            vary.append((v.group(1), v.group(2).split()))
            i += 1
        body = []
        while i < len(lines):
            body.append(lines[i])
            i += 1
            if body[-1].rstrip().endswith('}') and not body[-1].startswith((' ', '\t')):
                break
        if not vary:
            out += [f'// @p {name}: {desc}'] + body
            continue
        for combo in itertools.product(*[vals for _, vals in vary]):
            sub = dict(zip([k for k, _ in vary], combo))
            tag = '_'.join(OPNAMES.get(c) or re.sub(r'\W', '_', c.replace('-', 'm')) for c in combo)
            txt = '\n'.join(body)
            for k, v in sorted(sub.items(), key=lambda kv: -len(kv[0])):
                txt = txt.replace('@' + k, v)
            txt = re.sub(r'\bp_' + name + r'\b', f'p_{name}_{tag}', txt)
            out += [f'// @p {name}_{tag}: {desc} (' + ', '.join(f'{k}={v}' for k, v in sub.items()) + ')', txt, '']
    return '\n'.join(out) + '\n'


def generate(outdir):
    global GEN
    GEN = outdir / 'gen'
    GEN.mkdir(parents=True, exist_ok=True)
    for src_name, _ in SOURCES:
        (GEN / src_name).write_text(expand((HERE / src_name).read_text(encoding='utf-8')), encoding='utf-8')
    return GEN


def descriptions():
    out, cur, lines = {}, None, []
    for src_name, _ in SOURCES:
        lines += ((GEN or HERE) / src_name).read_text(encoding='utf-8').splitlines()
    for line in lines:
        m = re.match(r'//\s*@p\s+(\w+):\s*(.*)', line)
        if m:
            cur = m.group(1)
            out[cur] = {'desc': m.group(2), 'c': []}
        elif cur and line.strip():
            out[cur]['c'].append(line)
            if line.rstrip().endswith('}') and not line.startswith(' '):
                cur = None
    return out


def compile_patterns(game, cc, outdir, extra=''):
    """cc = compiler profile; extra = flags after the base ones, like build.ninja's cc_extra (the last wins)."""
    exe = find_mwcc(game, cc)
    funcs = {}
    for src_name, lang in SOURCES:
        src = (GEN or HERE) / src_name
        obj = outdir / (Path(src_name).stem + '.o')
        ex = extra
        if lang == 'c++':  # `-lang c99` is for C files only
            ex = ex.replace('-lang c99', '')
        cmd = [str(exe)] + game_flags(game) + ['-lang=' + lang] + shlex.split(ex) + ['-c', str(src), '-o', str(obj)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f'warning: {cc} {extra}: {src_name} does not compile, skipped\n'
                  + (r.stdout + r.stderr)[-600:], file=sys.stderr)
            continue
        mode = ['-M', 'force-thumb'] if '-thumb' in shlex.split(ex) else []
        dis = subprocess.run([OBJDUMP, '-d', '-m', 'armv5te'] + mode + ['--no-show-raw-insn', '-r', str(obj)],
                             capture_output=True, text=True).stdout
        cur, words, last_word = None, {}, None
        for line in dis.splitlines():
            r_ = re.match(r'^\s+([0-9a-f]+): R_ARM_ABS32', line)
            if r_ and last_word is not None and int(r_.group(1), 16) == last_word[1]:
                words[last_word] = 'SYM'  # the word is a symbol's address
                continue
            w_ = re.match(r'^\s+([0-9a-f]+):\s+\.word\s+(0x[0-9a-f]+)', line)
            if w_ and cur:
                last_word = (cur, int(w_.group(1), 16))
                words[last_word] = str(int(w_.group(2), 16))
                continue
            m = re.match(r'^[0-9a-f]+ <(\w+)>:', line)
            if m:
                cur = m.group(1)
                z = re.match(r'_Z(\d+)', cur)  # Itanium mangling (_Z7p_vcallP4Base) on 2.0 compilers
                if z:
                    cur = cur[z.end():z.end() + int(z.group(1))]
                elif cur.startswith('p_'):  # old mangling p_vcall__FP4Base
                    cur = cur.split('__')[0]
                if cur in funcs:  # one name, several sections: keep appending
                    continue
                funcs[cur] = []
                continue
            m = re.match(r'^\s+([0-9a-f]+):\s+(.*)$', line)
            if m and cur and not m.group(2).startswith('R_ARM'):
                txt = m.group(2)
                if re.match(r'^\.word|^[0-9a-f]{8}\s|^[0-9a-f]{4}\s', txt):
                    continue
                ADDRS.setdefault(cur, []).append(int(m.group(1), 16))
                funcs[cur].append(txt.split('\t', 1)[0] + ' ' + (txt.split('\t', 1)[1] if '\t' in txt else ''))
        # `ldr rX, [pc, #N] @ 18 <...>` -> `ldr rX, =<value>` (a number) or `=SYM` (an address)
        for name, raw in funcs.items():
            for i, x in enumerate(raw):
                q = re.match(r'(ldr\w*\s+\w+),\s*\[pc,\s*#\d+\]\s*@\s*([0-9a-f]+)', x)
                if q and (name, int(q.group(2), 16)) in words:
                    v = words[(name, int(q.group(2), 16))]
                    raw[i] = f'{q.group(1)}, =' + (v if v == 'SYM' else hex(int(v)))
    return funcs


def all_profiles(game, cc, outdir, sweep=False, min_files=3):
    """{setting label: {pattern: raw asm lines}}, {label: ADDRS copy}"""
    generate(outdir)
    out, addrs = {}, {}
    for label, prof, extra in game_settings(game, cc, sweep, min_files):
        sub = outdir / 'obj' / re.sub(r'[^\w.-]+', '_', label)
        sub.mkdir(parents=True, exist_ok=True)
        ADDRS.clear()
        out[label] = compile_patterns(game, prof, sub, extra)
        addrs[label] = dict(ADDRS)
    return out, addrs


# ---------------------------------------------------------------- asm normalisation and search

def norm(ins):
    ins = ins.split(';')[0].split('@')[0].strip()
    if not ins:
        return None
    ins = re.sub(r'\s+', ' ', ins)
    ins = ins.replace(', ', ',')
    mn, _, ops = ins.partition(' ')
    # condition aliases (objdump cc/cs, dsd lo/hs); only on known bases (`adcs` is adc + s)
    if mn[-2:] in ('cc', 'cs') and mn[:-2] in CC_BASES:
        mn = mn[:-2] + ('lo' if mn[-2:] == 'cc' else 'hs')
    # pool loads: dsd `ldr r0, .L_x` / objdump `ldr r0, [pc, #N]`
    k = re.search(r',=(0x[0-9a-f]+|\d+)$', ops)
    if mn.startswith('ldr') and k:  # pool constant: kept (the magic number of a division...)
        return f'{mn} R,={int(k.group(1), 0) & 0xffffffff}'
    if mn.startswith('ldr') and (re.search(r',\[pc', ops) or re.search(r',(\.L_|_0|=)', ops)):
        return f'{mn} R,POOL'
    if mn == 'blx' and re.fullmatch(REG + '|lr', ops):
        return 'blx R'
    if re.fullmatch(r'bl(x)?', mn) or (mn.startswith('bl') and re.fullmatch(r'bl(eq|ne|lt|ge|gt|le|hi|ls|cs|cc|mi|pl)?', mn)
                                       and not re.match(REG, ops)):
        return f'{mn} CALL'
    if re.fullmatch(r'b(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?', mn):
        return f'{mn} L'
    ops = re.sub(r'#(-?)(0x[0-9a-f]+|\d+)',
                 lambda m: '#' + str((-int(m.group(2), 0) if m.group(1) else int(m.group(2), 0)) & 0xffffffff), ops)
    ops = re.sub(r',#0\]', ']', ops)
    ops = re.sub(r'\b' + REG + r'\b', 'R', ops)
    return f'{mn} {ops}'.strip()


def target_funcs(game, every=False):
    ver = next(p for p in (game / 'build').iterdir() if (p / 'report.json').exists() and (p / 'asm').is_dir())
    rep = json.loads((ver / 'report.json').read_text())
    todo = {f['name'] for u in rep['units'] for f in u.get('functions', [])
            if every or f.get('fuzzy_match_percent', 0) < 100}
    body = {}
    for s in (ver / 'asm').rglob('*.s'):
        cur = None
        text = s.read_text(encoding='utf-8', errors='replace')
        pools = {m.group(1): m.group(2) for m in re.finditer(r'^(\.L_\w+):\s*\.word\s+(\S+)', text, re.M)}
        for line in text.splitlines():
            m = re.match(r'\s*(arm|thumb)_func_start\s+(\w+)', line)
            if m:
                cur = m.group(2) if m.group(2) in todo else None
                if cur:
                    body[cur] = []
                continue
            q = re.match(r'(\s+ldr\w*\s+\w+),\s*(\.L_\w+)\s*$', line.split(';')[0])
            if q and re.fullmatch(r'0x[0-9a-fA-F]+|\d+', pools.get(q.group(2), '')):
                line = f'{q.group(1)}, ={pools[q.group(2)]}'  # pool constant, as on the pattern side
            if re.match(r'\s*(arm|thumb)_func_end', line):
                cur = None
                continue
            if cur and line.startswith('    ') and not line.strip().startswith('.'):
                n = norm(line)
                if n:
                    body[cur].append(n)
    return todo, body


def shape(x):
    # constants -> N (shift amounts kept)
    return re.sub(r',=\d+$', ',=N', re.sub(r'(?<!(lsl|lsr|asr|ror) )#\d+', '#N', x))


class Index:
    """positions of each instruction in one function: a signature is only compared where its first
    instruction is, so thousands of signatures x settings stay fast."""

    def __init__(self, seq):
        self.seq = seq
        self.pos = collections.defaultdict(list)
        for i, x in enumerate(seq):
            self.pos[x].append(i)

    def find(self, sig):
        k, seq = len(sig), self.seq
        return sum(1 for i in self.pos.get(sig[0], ()) if seq[i:i + k] == sig)

    def scatter(self, sig):
        # the signature in order, other instructions allowed in between (scheduling), within 2x its length
        k, seq, n = len(sig), self.seq, 0
        for i in self.pos.get(sig[0], ()):
            j, end = 1, min(len(seq), i + 2 * k)
            for y in seq[i + 1:end]:
                if j < k and y == sig[j]:
                    j += 1
            if j == k:
                n += 1
        return n


def find(seq, sig):
    return Index(seq).find(sig)


def scatter(seq, sig):
    return Index(seq).scatter(sig)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cc', default='auto', help="'auto' = every setting of build.ninja, or 'PROFILE [flags]'")
    ap.add_argument('--sweep', action='store_true', help='also the common flags of other games (SWEEP)')
    ap.add_argument('--min-files', type=int, default=3, help='a build.ninja setting needs this many files')
    ap.add_argument('--out', default='build/c2asm')
    ap.add_argument('--min', type=int, default=3, help='shortest signature kept (instructions)')
    ap.add_argument('--all', action='store_true', help='scan matched functions too (to check the idioms)')
    a = ap.parse_args()
    game = Path.cwd()
    outdir = game / a.out
    outdir.mkdir(parents=True, exist_ok=True)
    byset, _ = all_profiles(game, a.cc, outdir, a.sweep, a.min_files)
    sets = list(byset)
    descs = descriptions()
    todo, body = target_funcs(game, a.all)

    # phrasebook: the asm of each idiom, one block per distinct output
    book = [f'# c2asm phrasebook ({game.name})\n', 'settings: ' + ' | '.join(sets) + '\n']
    sigs = {}  # (name, setting) -> signature
    for name, d in descs.items():
        book.append(f'## {name}: {d["desc"]}\n\n```c\n' + '\n'.join(d['c']) + '\n```\n')
        seen = {}
        for st in sets:
            raw = byset[st].get('p_' + name, [])
            sigs[(name, st)] = tuple(n for n in (norm(x) for x in raw) if n and not SKIP.match(n))
            txt = '\n'.join(x.strip() for x in raw)
            if txt in seen:
                seen[txt].append(st)
                continue
            seen[txt] = [st]
        for txt, sts in seen.items():
            book.append('`' + '`, `'.join(sts) + '`:\n\n```asm\n' + txt + '\n```\n')
    (outdir / 'phrasebook.md').write_text('\n'.join(book), encoding='utf-8')

    # one search per distinct signature, credited to every (idiom, setting) that gives it
    owners = collections.defaultdict(list)
    for key, sig in sigs.items():
        if len(sig) >= a.min:
            owners[sig].append(key)
    shaped = {sig: tuple(shape(x) for x in sig) for sig in owners}
    hits = collections.defaultdict(dict)   # name -> {function: [settings]}
    shits = collections.defaultdict(dict)
    scat = collections.defaultdict(dict)
    for fn, seq in body.items():
        ix, sx = Index(tuple(seq)), Index(tuple(shape(x) for x in seq))
        for sig, keys in owners.items():
            e = ix.find(sig)
            sh = e or sx.find(shaped[sig])
            sp = len(sig) >= 4 and (sh or sx.scatter(shaped[sig]))
            for name, st in keys:
                if e:
                    hits[name].setdefault(fn, []).append(st)
                if sh:
                    shits[name].setdefault(fn, []).append(st)
                if sp:
                    scat[name].setdefault(fn, []).append(st)

    lines = [f'# c2asm hits ({game.name}, {len(body)}/{len(todo)} functions read'
             + (', matched ones too' if a.all else ', unmatched only') + f'; {len(sets)} settings)\n',
             '| idiom | sig len | exact | same shape | spread | settings of the hits | example functions (exact, ~shape) |',
             '|---|---|---|---|---|---|---|']
    for name in descs:
        n = max(len(sigs[(name, st)]) for st in sets)
        if n < a.min:
            lines.append(f'| {name} | {n} | too short | | | | |')
            continue
        h, sh, sc = hits[name], shits[name], scat[name]
        pc = collections.Counter(s for f in sh for s in sh[f])
        ex = ', '.join(list(h)[:4] + [f + '~' for f in sh if f not in h][:3])
        lines.append(f'| {name} | {n} | {len(h)} | {len(sh)} | {len(sc) if n >= 4 else ""} | '
                     + ', '.join(f'{p}:{c}' for p, c in pc.most_common(3)) + f' | {ex} |')
    lines.append('\n## signatures\n')
    for (name, st), sig in sigs.items():
        lines.append(f'- **{name}** `{st}`: `' + ' ; '.join(sig) + '`')
    suffix = '_all' if a.all else ''
    (outdir / f'hits{suffix}.md').write_text('\n'.join(lines), encoding='utf-8')
    (outdir / f'hits{suffix}.json').write_text(json.dumps(
        {'settings': sets,
         'idioms': {name: {'exact': hits[name], 'shape': shits[name], 'spread': scat[name]} for name in descs}},
        indent=1), encoding='utf-8')
    print('\n'.join(lines[:len(descs) + 4]))


if __name__ == '__main__':
    main()
