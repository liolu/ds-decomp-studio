"""cppvcall.py SRC_DIR OUT_DIR [--names-file F] : rewrite m2c vtable calls of drafts as real C++ virtual calls.

Why: mwcc C++ loads the vtable through r0 (`mov r0,rX; ldr r1,[r0]; ldr r1,[r1,#K]; blx r1`), a C function pointer call
never does (`ldr r1,[rX]`). Origin: Sims 2 func_02045e10, 1 diff in C, match in C++ (technique cpp-vcall).

Rewrites `M2C_FIELD(M2C_FIELD(X, void **, OFF), R (**)(SIG), K)(ARGS)` into `((VCn *)P)->fI(ARGS)` with one
`struct VCn { virtual ... }` per call, P = X (OFF 0) or `(u8 *)X + OFF`, I = K / 4. `this` is dropped from ARGS when m2c
kept it. Every top-level declaration and definition gets `extern "C"`, and `f()` prototypes become `f(...)` (C++ reads
`()` as no argument). A file with no such call is not written. Judge the output with fj.py: files that do not compile in
C++ (implicit void * conversions) are simply misses to finish by hand."""
import argparse, re
from pathlib import Path

HEAD = re.compile(r'M2C_FIELD\(M2C_FIELD\(')
TOP = re.compile(r'^(?!#|extern "C"|typedef|struct|union|enum|static|\s|}|/)(?=.*[\w*]\s*[\w(*])')


def balanced(s: str, i: int) -> int:
    """Index just after the `)` closing the `(` at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        depth += (s[j] == '(') - (s[j] == ')')
        if depth == 0:
            return j + 1
    return -1


def split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, ''
    for c in s:
        depth += (c == '(') - (c == ')')
        if c == ',' and depth == 0:
            out.append(cur.strip()); cur = ''
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def convert_call(src: str, start: int, n: int):
    """(replacement, struct text, end index) for a vcall at `start`, or None."""
    end = balanced(src, start + len('M2C_FIELD'))
    if end < 0 or src[end:end + 1] != '(':
        return None
    parts = split_args(src[start + len('M2C_FIELD') + 1:end - 1])
    if len(parts) != 3 or not parts[0].startswith('M2C_FIELD('):
        return None
    m = re.fullmatch(r'(.+?)\s*\(\*\*\)\((.*)\)', parts[1], re.S)
    inner = split_args(parts[0][len('M2C_FIELD('):-1])
    if not m or len(inner) != 3 or not re.fullmatch(r'void \*+', inner[1]):
        return None
    obj, off, ret, sig = inner[0], int(inner[2], 0), m.group(1), m.group(2)
    slot = int(parts[2], 0)
    if slot % 4:
        return None
    call_end = balanced(src, end)
    args = split_args(src[end + 1:call_end - 1])
    types = [t.replace('M2C_UNK', 's32') for t in split_args(sig)]
    if args and args[0] == obj:  # m2c kept `this`
        args, types = args[1:], types[1:]
    if len(types) != len(args):
        types = ['s32'] * len(args)
    this = obj if off == 0 else f'(u8 *){obj} + {inner[2]}'
    slots = ' '.join(f'virtual void f{i}();' for i in range(slot // 4))
    params = ', '.join(types)
    struct = f'struct VC{n} {{ {slots} virtual {ret} f{slot // 4}({params}); }};\n'
    return f'(({"VC" + str(n)} *)({this}))->f{slot // 4}({", ".join(args)})', struct, call_end


def convert(src: str) -> str | None:
    structs, n, i, out = '', 0, 0, ''
    while True:
        m = HEAD.search(src, i)
        if not m:
            out += src[i:]
            break
        r = convert_call(src, m.start(), n)
        if r is None:
            out += src[i:m.end()]
            i = m.end()
            continue
        out += src[i:m.start()] + r[0]
        structs += r[1]
        i = r[2]
        n += 1
    if not n:
        return None
    lines = []
    for line in out.split('\n'):
        if TOP.match(line):
            line = 'extern "C" ' + re.sub(r'^extern\s+', 'extern ', line) if not line.startswith('extern ') else 'extern "C" ' + line[7:]
            line = re.sub(r'\(\)(\s*;)', r'(...)\1', line)
        lines.append(line)
    text = '\n'.join(lines)
    if '#include "m2c.h"' in text:
        return text.replace('#include "m2c.h"\n', '#include "m2c.h"\n' + structs, 1)
    return structs + text


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out'); ap.add_argument('--names-file')
    a = ap.parse_args()
    names = set(Path(a.names_file).read_text().split()) if a.names_file else None
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(Path(a.src).glob('*.c')):
        if names is not None and f.stem not in names:
            continue
        t = convert(f.read_text(encoding='utf-8', errors='replace'))
        if t:
            (out / f.name).write_text(t, encoding='utf-8', newline='\n')
            n += 1
    print(n, 'files converted')
