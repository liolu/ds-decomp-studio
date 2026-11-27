"""linemine.py - c2asm part 3: the phrasebook written by the compiler itself.

Every matched object of a game (build/<ver>/src/**.o, built with -sym on) carries a .debug_line table: C line
-> address of its first instruction. linemine cuts each matched function into fragments (one C line -> the
instructions until the next line starts), normalises them like c2asm (registers R, branches L, pool constants
kept), and looks them up in the unmatched functions.

    cd projets/<game>        (or All-nds-decomp-games/games/<L>/<game>)
    python <studio>/gametools/prototypes/c2asm/linemine.py mine      # -> build/linemine/fragments.json
    python <studio>/gametools/prototypes/c2asm/linemine.py scan [--from other/game ...] [--min 4]
    python <studio>/gametools/prototypes/c2asm/linemine.py check     # leave-one-out precision on matched code

scan: for each unmatched function, which C lines of other functions give exactly the same instructions (exact:
constants kept; shape: constants loose); coverage = share of the unmatched instructions explained by a known line.
check: the same search on matched functions, a function's own fragments excluded; precision = the suggested C has
the same form (identifiers and numbers abstracted) as the real line.
Only one-function objects are read (the line table of a multi-function object has no section names), and an
object older than its source is skipped (stale line numbers). Thumb objects are skipped for now.
Prototype 2026-11-27.
"""
import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import c2asm  # noqa: E402

OBJDUMP = c2asm.OBJDUMP
C_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'return', 'switch', 'case', 'break', 'continue', 'goto',
              'sizeof', 'default', 'volatile', 'const', 'unsigned', 'signed', 'struct', 'union', 'static'}
MAXLEN = 40


def version_dir(game):
    return next(p for p in (game / 'build').iterdir() if (p / 'report.json').exists() and (p / 'asm').is_dir())


def file_settings(game):
    """source path (posix, relative) -> setting label, from build.ninja."""
    text = (game / 'build.ninja').read_text(encoding='utf-8', errors='replace').replace('$\n', ' ')
    out = {}
    for blk in re.split(r'\n(?=build )', text):
        m = re.match(r'build (\S+): mwcc\s+(\S+)', blk)
        if not m:
            continue
        cc = re.search(r'\n\s+cc = (\S+)', blk)
        ex = re.search(r'\n\s+cc_extra = ([^\n]*)', blk)
        p = re.search(r'mwccarm[\\/](\d\.\d)[\\/](\w+)[\\/]mwccarm', cc.group(1)) if cc else None
        if p:
            lab = (f'{p.group(1)}/{p.group(2)} ' + ' '.join((ex.group(1) if ex else '').split())).strip()
            out[m.group(2).replace('\\', '/')] = (m.group(1).replace('\\', '/'), lab)
    return out


def c_form(line):
    """the form of a C line: identifiers -> ID, numbers -> N (keywords and operators kept)."""
    line = re.sub(r'//.*', '', line).strip()
    line = re.sub(r'0x[0-9a-fA-F]+|\b\d+\b', 'N', line)
    line = re.sub(r'\b[A-Za-z_]\w*\b', lambda m: m.group(0) if m.group(0) in C_KEYWORDS else 'ID', line)
    return re.sub(r'\s+', '', line)


def parse_dump(text):
    """objdump -d -r --dwarf=decodedline of several objects -> {obj: (rows, funcs)}
    rows = [(line, addr)], funcs = {name: [(addr, raw)]} with pool constants resolved."""
    out = {}
    for part in re.split(r'\n(?=\S+\.o:\s+file format)', text):
        m = re.match(r'(\S+\.o):\s+file format', part.strip())
        if not m:
            continue
        rows, funcs, cur, words, last = [], {}, None, {}, None
        for line in part.splitlines():
            r = re.match(r'^\S+\.(?:c|cpp|cp|h)\s+(\d+)\s+(0x[0-9a-f]+|\d+)', line)
            if r:
                rows.append((int(r.group(1)), int(r.group(2), 0)))
                continue
            r = re.match(r'^\s+([0-9a-f]+): R_ARM_ABS32', line)
            if r and last is not None and int(r.group(1), 16) == last[1]:
                words[last] = 'SYM'
                continue
            w = re.match(r'^\s+([0-9a-f]+):\s+\.word\s+(0x[0-9a-f]+)', line)
            if w and cur:
                last = (cur, int(w.group(1), 16))
                words[last] = str(int(w.group(2), 16))
                continue
            f = re.match(r'^[0-9a-f]+ <(\w+)>:', line)
            if f:
                cur = f.group(1)
                funcs.setdefault(cur, [])
                continue
            i = re.match(r'^\s+([0-9a-f]+):\s+(.*)$', line)
            if i and cur and not i.group(2).startswith(('R_ARM', '.word')):
                txt = i.group(2)
                if re.match(r'^[0-9a-f]{4,8}\s', txt):
                    continue
                funcs[cur].append((int(i.group(1), 16), txt.replace('\t', ' ', 1).replace('\t', ' ')))
        for name, ins in funcs.items():
            for k, (ad, x) in enumerate(ins):
                q = re.match(r'(ldr\w*\s+\w+),\s*\[pc,\s*#\d+\]\s*@\s*([0-9a-f]+)', x)
                if q and (name, int(q.group(2), 16)) in words:
                    v = words[(name, int(q.group(2), 16))]
                    ins[k] = (ad, f'{q.group(1)}, =' + (v if v == 'SYM' else hex(int(v))))
        out[m.group(1)] = (rows, funcs)
    return out


def fragments(rows, ins, src_lines):
    """one function: [(line number, C text, [normalised asm])], consecutive rows of one line merged."""
    rows = sorted(set(rows), key=lambda r: r[1])
    out = []
    for k, (line, addr) in enumerate(rows):
        end = rows[k + 1][1] if k + 1 < len(rows) else 1 << 30
        asm = [c2asm.norm(x) for ad, x in ins if addr <= ad < end]
        asm = [a for a in asm if a and not c2asm.SKIP.match(a)]
        if not asm or not (1 <= line <= len(src_lines)):
            continue
        text = src_lines[line - 1].strip()
        if out and out[-1][0] == line:
            out[-1][2].extend(asm)
        else:
            out.append((line, text, asm))
    # the function header and lone braces carry the prologue/epilogue: not C idioms
    return [f for f in out if f[1] not in ('{', '}', '') and not re.match(r'^[\w\s\*]+\w+\s*\([^;]*\)\s*\{?$', f[1])]


def mine(game, batch=150):
    ver = version_dir(game)
    rep = json.loads((ver / 'report.json').read_text())
    matched = {f['name'] for u in rep['units'] for f in u.get('functions', [])
               if f.get('fuzzy_match_percent', 0) >= 100}
    fs = file_settings(game)
    objs = []
    for src, (obj, lab) in fs.items():
        o, s = game / obj, game / src
        if '-thumb' in lab.split() or not o.exists() or not s.exists():
            continue
        if s.stat().st_mtime > o.stat().st_mtime:
            continue  # stale object: its line numbers may not match the source any more
        objs.append((o, s, lab))
    frags, skipped = [], collections.Counter()
    for b in range(0, len(objs), batch):
        chunk = objs[b:b + batch]
        r = subprocess.run([OBJDUMP, '-d', '-r', '-m', 'armv5te', '--no-show-raw-insn', '--dwarf=decodedline']
                           + [o.relative_to(game).as_posix() for o, _, _ in chunk],  # no spaces in the names
                           capture_output=True, text=True, errors='replace', cwd=game)
        dumps = parse_dump(r.stdout)
        for o, s, lab in chunk:
            key = next((k for k in dumps if Path(k).name == o.name and Path(k).parent.name == o.parent.name), None)
            if key is None:
                skipped['no dump'] += 1
                continue
            rows, funcs = dumps[key]
            funcs = {n: v for n, v in funcs.items() if v}
            if len(funcs) != 1:
                skipped['no code (data object)' if not funcs else 'several functions'] += 1
                continue
            (name, ins), = funcs.items()
            if name not in matched:
                skipped['not matched'] += 1
                continue
            src_lines = s.read_text(encoding='utf-8', errors='replace').splitlines()
            for line, text, asm in fragments(rows, ins, src_lines):
                frags.append({'func': name, 'setting': lab, 'line': line, 'c': text, 'asm': asm})
        print(f'  {min(b + batch, len(objs))}/{len(objs)} objects, {len(frags)} fragments', file=sys.stderr)
    out = game / 'build' / 'linemine'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'fragments.json').write_text(json.dumps({'game': game.name, 'fragments': frags}), encoding='utf-8')
    print(f'{game.name}: {len(objs)} objects read, {len(frags)} fragments from '
          f'{len({f["func"] for f in frags})} matched functions; skipped {dict(skipped)}')


PLAIN = re.compile(r'^(mov R,R|mov R,#\d+|bl\w* CALL|blx R|b\w* L|ldr R,\[R\]|movs R,R)$')


def informative(asm):
    """at least 2 instructions besides register copies, calls and branches: `mov;mov;mov;bl` fits any call."""
    return sum(1 for x in asm if not PLAIN.match(x)) >= 2


class Library:
    """signature tuple -> [fragment]; lookup by k-gram (every length present, up to MAXLEN)."""

    def __init__(self, frags, minlen, shaped=False):
        self.by = collections.defaultdict(list)
        self.shaped = shaped
        for f in frags:
            sig = tuple(c2asm.shape(x) for x in f['asm']) if shaped else tuple(f['asm'])
            if minlen <= len(sig) <= MAXLEN and informative(f['asm']):
                self.by[sig].append(f)
        self.lengths = sorted({len(s) for s in self.by})

    def hits(self, seq):
        """[(start, sig, fragments)] for every known fragment found in seq."""
        seq = tuple(c2asm.shape(x) for x in seq) if self.shaped else tuple(seq)
        out = []
        for i in range(len(seq)):
            for n in self.lengths:
                if i + n > len(seq):
                    break
                sig = seq[i:i + n]
                if sig in self.by:
                    out.append((i, sig, self.by[sig]))
        return out


def load_frags(game, others):
    frags = []
    for g in [game] + [Path(o).resolve() for o in others]:
        p = g / 'build' / 'linemine' / 'fragments.json'
        if not p.exists():
            sys.exit(f'{p} missing: run `linemine.py mine` in {g}')
        d = json.loads(p.read_text())
        for f in d['fragments']:
            f['game'] = d['game']
        frags += d['fragments']
    return frags


def suggest(frs):
    """most common C forms among fragments with one signature: [(form count, example C, settings)]."""
    by = collections.defaultdict(list)
    for f in frs:
        by[c_form(f['c'])].append(f)
    return sorted(((len(v), v[0]['c'], sorted({x['setting'] for x in v})) for v in by.values()), key=lambda t: -t[0])


def scan(game, others, minlen):
    frags = load_frags(game, others)
    lib, slib = Library(frags, minlen), Library(frags, minlen, shaped=True)
    todo, body = c2asm.target_funcs(game, False)
    covered_exact = covered_shape = total = 0
    funcs_with = collections.Counter()
    report = {}
    for fn, seq in body.items():
        total += len(seq)
        ex, sh = set(), set()
        found = []
        for i, sig, frs in lib.hits(seq):
            ex.update(range(i, i + len(sig)))
            found.append((i, 'exact', sig, frs))
        for i, sig, frs in slib.hits(seq):
            sh.update(range(i, i + len(sig)))
            if not any(i == j and len(sig) == len(s) for j, _, s, _ in found):
                found.append((i, 'shape', sig, frs))
        covered_exact += len(ex)
        covered_shape += len(sh | ex)
        if ex:
            funcs_with['exact'] += 1
        if sh or ex:
            funcs_with['shape'] += 1
        if found:
            report[fn] = [{'at': i, 'kind': k, 'len': len(sig), 'asm': ' ; '.join(sig),
                           'c': [{'n': n, 'c': c, 'settings': s} for n, c, s in suggest(frs)[:3]]}
                          for i, k, sig, frs in sorted(found, key=lambda t: (t[0], -len(t[2])))]
    out = game / 'build' / 'linemine'
    (out / 'scan.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    lines = [f'# linemine scan ({game.name}; fragments from {", ".join(sorted({f["game"] for f in frags}))}; '
             f'{len(lib.by)} exact / {len(slib.by)} shape signatures of >= {minlen} instructions)\n',
             f'- unmatched functions read: {len(body)}/{len(todo)}',
             f'- with >= 1 exact fragment: {funcs_with["exact"]} ({100 * funcs_with["exact"] / max(1, len(body)):.1f} %)',
             f'- with >= 1 fragment, constants loose: {funcs_with["shape"]} '
             f'({100 * funcs_with["shape"] / max(1, len(body)):.1f} %)',
             f'- unmatched instructions explained exactly: {covered_exact}/{total} '
             f'({100 * covered_exact / max(1, total):.1f} %), constants loose: {100 * covered_shape / max(1, total):.1f} %',
             '', '## examples', '']
    best = sorted(report.items(), key=lambda kv: -max(h['len'] for h in kv[1] if h['kind'] == 'exact')
                  if any(h['kind'] == 'exact' for h in kv[1]) else 0)[:15]
    for fn, hs in best:
        h = max((h for h in hs if h['kind'] == 'exact'), key=lambda h: h['len'], default=hs[0])
        lines.append(f'- **{fn}** @{h["at"]} ({h["len"]} instr.): `{h["asm"][:120]}` -> '
                     + ' | '.join(f'`{c["c"][:70]}` x{c["n"]}' for c in h['c']))
    (out / 'scan.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


def check(game, minlen):
    """leave-one-out on matched functions: does a fragment of another function suggest the right C form?"""
    frags = load_frags(game, [])
    lib = Library(frags, minlen)
    by_func = collections.defaultdict(list)
    for f in frags:
        by_func[f['func']].append(f)
    right = wrong = top_right = 0
    examples = []
    for fn, own in by_func.items():
        for f in own:
            sig = tuple(f['asm'])
            if not (minlen <= len(sig) <= MAXLEN) or not informative(f["asm"]):
                continue
            others = [x for x in lib.by.get(sig, []) if x['func'] != fn]
            if not others:
                continue
            sug = suggest(others)
            forms = {c_form(c) for _, c, _ in sug}
            if c_form(f['c']) in forms:
                right += 1
                top_right += c_form(sug[0][1]) == c_form(f['c'])
            else:
                wrong += 1
                if len(examples) < 8:
                    examples.append((f['c'], sug[0][1], ' ; '.join(sig)))
    n = right + wrong
    print(f'{game.name}: matched fragments of >= {minlen} instr. also produced by another function: {n}')
    if n:
        print(f'  the real C form is among the suggestions: {right} ({100 * right / n:.1f} %), '
              f'the first suggestion: {top_right} ({100 * top_right / n:.1f} %)')
    for real, sug, asm in examples:
        print(f'   real `{real}`  suggested `{sug}`  asm `{asm[:90]}`')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['mine', 'scan', 'check'])
    ap.add_argument('--from', dest='others', nargs='*', default=[], help='other games whose fragments are used too')
    ap.add_argument('--min', type=int, default=4, help='shortest fragment searched (instructions)')
    a = ap.parse_args()
    game = Path.cwd()
    if a.cmd == 'mine':
        mine(game)
    elif a.cmd == 'scan':
        scan(game, a.others, a.min)
    else:
        check(game, a.min)


if __name__ == '__main__':
    main()
