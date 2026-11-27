"""linkfix.py NINJA.LOG [--drop] : repair the `Undefined` link errors of agent matches that judge cannot see (it masks bl and
literal names). From the game dir, on a log of a failed `ninja`.
 - `func_x(void*)`: a C++ source declares a callee without extern "C", so the name is mangled: adds extern "C" to the declaration.
 - `data_0212F9C4`: upper-case address, symbols are lower-case: lower-cases the name in the source.
 - anything else (`func_020e33ac`, a call to a label inside a function, or a symbol that does not exist): with --drop the
   referencing file goes to build/culprits/ like find_culprits does, otherwise it is only listed.
Technique id: linkfix. Rerun ninja after it: the linker reports new names once the first ones are gone."""
import re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import find_culprits  # noqa: E402
import project  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
UNDEF = re.compile(r'Undefined : "([^"]+)"')
REF = re.compile(r'Referenced from "([^"]+)" in (\S+)\.o')


def parse(text):
    out, cur = {}, None
    for line in ANSI.sub('', text).splitlines():
        m = UNDEF.search(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, set())
            continue
        m = REF.search(line)
        if m and cur:
            out[cur].add(m.group(2))
    return out


def source_of(obj):
    for sub in ('auto', 'data'):
        p = project.ROOT / 'src' / sub / f'{obj}.c'
        if p.exists():
            return p
        p = p.with_suffix('.cpp')
        if p.exists():
            return p
    return None


def add_extern_c(text, name):
    """Puts extern "C" on the file-level declaration of `name`; False when none is found."""
    pat = re.compile(r'^(?!extern "C")((?:extern\s+)?[\w \t\*]+?\b' + re.escape(name) + r'\s*\([^;{]*\)\s*;)', re.M)
    new, n = pat.subn(lambda m: 'extern "C" ' + re.sub(r'^extern\s+', '', m.group(1)), text, count=1)
    return new if n else None


def main():
    und = parse(Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace'))
    bad, fixed = set(), 0
    for sym, objs in sorted(und.items()):
        mangled = re.match(r'(\w+)\(', sym)
        for obj in sorted(objs):
            p = source_of(obj)
            if p is None:
                print('no source', sym, obj)
                continue
            t = p.read_text(encoding='utf-8')
            if mangled:
                new = add_extern_c(t, mangled.group(1))
            elif re.fullmatch(r'data_(ov\d+_)?[0-9A-Fa-f]{8}', sym) and sym != sym.lower():
                new = t.replace(sym, sym.lower())
            else:
                new = None
            if new is None or new == t:
                print('unfixable', sym, '<-', obj)
                bad.add(p.relative_to(project.ROOT).as_posix())
                continue
            p.write_text(new, encoding='utf-8', newline='\n')
            fixed += 1
    print(f'{len(und)} undefined names, {fixed} sources fixed, {len(bad)} unfixable: {sorted(bad)}')
    if bad and '--drop' in sys.argv:
        find_culprits.drop(sorted(bad), project.BUILD.parent / 'culprits' / time.strftime('%Y%m%d-%H%M%S'))
        print('dropped', len(bad))


if __name__ == '__main__':
    main()
