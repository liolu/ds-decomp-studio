"""asmconv.py NAME... : for functions using assembly-only instructions (swp/swpb, mrs/msr, swi, coprocessor, clz),
write build/hunt/proto/NAME/asmconv.c with a whole-function `asm` version (auto_match.asm_function_general + pre-UAL
suffix order `swpeqb`/`ldrneh` + `blx sym` -> `bl sym`) and judge it. AGENTS.md allows whole asm functions only for
instructions mwcc never emits. `blx` must stay `bl` even for a Thumb callee (objdiff drops the file otherwise).
Technique id: asm-function. Origin: TnJ r4 (build/hunt/w/asmconv.py, ~75 swpb/BIOS matches)."""
import os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402

CONDS = 'eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le'


def pre_ual(line):
    m = re.match(r'^(\s*)(ldr|str|swp)(sb|sh|b|h|d)(' + CONDS + r')(\s.*)$', line)
    if m:
        return f'{m.group(1)}{m.group(2)}{m.group(4)}{m.group(3)}{m.group(5)}'
    m = re.match(r'^(\s*)blx(\s+)(?!r\d|lr|ip)(\w+)$', line)
    if m:
        return f'{m.group(1)}bl{m.group(2)}{m.group(3)}'
    return line


def convert(name):
    hunt._module(name)
    am = hunt.WB.am
    asm = am.function_asm(name) or ''
    if not am.ASM_ONLY.search(asm): return None
    src = am.asm_function_general(name, asm) or am.asm_function(name, asm)
    if src is None: return ''
    return '#include "m2c.h"\n' + '\n'.join(pre_ual(l) for l in src.split('\n'))


def proto_run(ctx):
    src = convert(ctx['name'])
    if src is None: return {'result': 'skip', 'note': 'no asm-only instruction'}
    if not src: return {'result': 'fail', 'note': 'not convertible'}
    r = ctx['judge'](src, None)
    if r.get('match'): return {'result': 'ok', 'diffs': 0, 'profile': r.get('profile'), 'src': src, 'note': 'asm function'}
    return {'result': 'fail', 'diffs': r.get('diffs'), 'profile': r.get('profile'), 'src': src,
            'note': (r.get('status') or '') + ' ' + str(r.get('errors') or r.get('why') or '')[:120]}


if __name__ == '__main__':
    hunt._init()
    for n in sys.argv[1:]:
        s = convert(n)
        if not s: print(n, 'skip' if s is None else 'not convertible'); continue
        out = hunt.HUNT / 'proto' / n; out.mkdir(parents=True, exist_ok=True); (out / 'asmconv.c').write_text(s, encoding='utf-8')
        r = hunt._judge((n, s, None))
        print(f"{n:40} {r.get('status')} {r.get('diffs')} {r.get('size')}/{r.get('target_size')} {r.get('profile')}")
    sys.stdout.flush(); os._exit(0)
