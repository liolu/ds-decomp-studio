"""libdonor.py - free libraries as donors: compile a public library (git repository, chosen revisions) with the
game's own mwccarm settings, compare every compiled function with every unmatched function of the same size (the
judge's comparison: calls and literal-pool words masked), confirm each identical pair with workbench.judge.

    cd <game>
    python <studio>/gametools/prototypes/c2asm/libdonor.py REPO REV [REV...] [--files GLOB] [--settings N]
    e.g. libdonor.py "D:/.../_downloads/tremor" 64350e0 57c1a82      (Tremor 2007-09 / 2008-12, BSD-3)

Writes build/libdonor/<lib>/matches.jsonl (target, donor function, donor source = the preprocessed file, profile),
in the format submit scripts read (donor_file, donor, profile). Nothing is submitted.
Only public, freely licensed code (check the repository's licence first): AGENTS.md rule 2 allows public projects,
never leaked or SDK source. First use 2026-11-28: Tremor (Xiph, BSD) found in Penguins of Madagascar, Shrek
Forever After and Wheel of Fortune through its constant tables.
"""
import argparse
import collections
import fnmatch
import io
import json
import re
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import c2asm  # noqa: E402
import workbench as wb  # noqa: E402

pc = wb.pc
# minimal C library headers: only what the libraries include (prototypes, types, macros); mwccarm has no libc here
SYSINC = {
    'stddef.h': '#ifndef _STDDEF_H\n#define _STDDEF_H\ntypedef unsigned long size_t;\ntypedef int ptrdiff_t;\n'
                '#ifndef NULL\n#define NULL 0\n#endif\n#endif\n',
    'sys/types.h': '#include <stddef.h>\n#ifndef LITTLE_ENDIAN\n#define LITTLE_ENDIAN 1234\n#define BIG_ENDIAN 4321\n'
                   '#define BYTE_ORDER LITTLE_ENDIAN\n#endif\n',
    'stdlib.h': '#ifndef _STDLIB_H\n#define _STDLIB_H\n#include <stddef.h>\nvoid *malloc(size_t);\n'
                'void *calloc(size_t, size_t);\nvoid *realloc(void *, size_t);\nvoid free(void *);\nint abs(int);\n'
                'long labs(long);\nvoid qsort(void *, size_t, size_t, int (*)(const void *, const void *));\n'
                'int atoi(const char *);\nvoid exit(int);\n#endif\n',
    'string.h': '#ifndef _STRING_H\n#define _STRING_H\n#include <stddef.h>\nvoid *memset(void *, int, size_t);\n'
                'void *memcpy(void *, const void *, size_t);\nvoid *memmove(void *, const void *, size_t);\n'
                'int memcmp(const void *, const void *, size_t);\nsize_t strlen(const char *);\n'
                'int strcmp(const char *, const char *);\nint strncmp(const char *, const char *, size_t);\n'
                'char *strcpy(char *, const char *);\nchar *strcat(char *, const char *);\n#endif\n',
    'stdio.h': '#ifndef _STDIO_H\n#define _STDIO_H\n#include <stddef.h>\ntypedef struct _FILE FILE;\n'
               'extern FILE *stderr;\nint fprintf(FILE *, const char *, ...);\nint printf(const char *, ...);\n'
               'size_t fread(void *, size_t, size_t, FILE *);\nint fseek(FILE *, long, int);\nlong ftell(FILE *);\n'
               'int fclose(FILE *);\n#define SEEK_SET 0\n#define SEEK_CUR 1\n#define SEEK_END 2\n#define EOF (-1)\n#endif\n',
    'math.h': '#ifndef _MATH_H\n#define _MATH_H\ndouble floor(double);\ndouble ceil(double);\ndouble exp(double);\n'
              'double log(double);\ndouble pow(double, double);\ndouble sqrt(double);\ndouble cos(double);\n'
              'double sin(double);\ndouble atan(double);\ndouble fabs(double);\ndouble ldexp(double, int);\n'
              'double frexp(double, int *);\n#endif\n',
    'ctype.h': '#ifndef _CTYPE_H\n#define _CTYPE_H\nint toupper(int);\nint tolower(int);\n#endif\n',
    'errno.h': '#ifndef _ERRNO_H\n#define _ERRNO_H\nextern int errno;\n#endif\n',
    'alloca.h': '#ifndef _ALLOCA_H\n#define _ALLOCA_H\n#define alloca(x) __alloca(x)\n#endif\n',
    'limits.h': '#ifndef _LIMITS_H\n#define _LIMITS_H\n#define INT_MAX 2147483647\n#define INT_MIN (-INT_MAX-1)\n#endif\n',
}


def export(repo, rev, dest):
    if (dest / '.done').exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(['git', 'archive', '--format=tar', rev], cwd=repo, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dest, filter='data')
    (dest / '.done').write_text(rev)


DEFINES = []  # -d NAME[=VALUE] for every compile (set from --define)


def compile_file(game, prof, extra, src, inc, out_obj, out_pp):
    exe = c2asm.find_mwcc(game, prof)
    base = [str(exe)] + c2asm.game_flags(game) + ['-lang=c'] + shlex.split(extra) + ['-i', str(inc[0])]
    for d in DEFINES:
        base += ['-d', d]
    for d in inc[1:]:
        base += ['-i', str(d)]
    r = subprocess.run(base + ['-c', str(src), '-o', str(out_obj)], capture_output=True, text=True, errors='replace')
    if r.returncode != 0:
        return (r.stdout + r.stderr)[-400:]
    p = subprocess.run(base + ['-E', str(src)], capture_output=True, text=True, errors='replace')
    out_pp.write_text('\n'.join(l for l in p.stdout.splitlines() if not l.lstrip().startswith('#')), encoding='utf-8')
    return ''


def top_level(text):
    """split preprocessed C into top-level items (text, kind): 'func' (a definition with a body), 'data' (an
    initialised object), 'other' (types, prototypes, plain declarations)."""
    items, i, n, start, depth = [], 0, len(text), 0, 0
    while i < n:
        c = text[i]
        if c in '"\'':  # skip string / char literals
            q, i = c, i + 1
            while i < n and text[i] != q:
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                j = i + 1
                while j < n and text[j] in ' \t\r\n':
                    j += 1
                chunk = text[start:i + 1]
                head = chunk[:chunk.find('{')]
                if j < n and text[j] == ';' or '=' in head.split('(')[0] or not re.search(r'\)\s*$', head):
                    end = text.find(';', i) + 1 if text.find(';', i) >= 0 else i + 1
                    chunk = text[start:end]
                    kind = 'data' if '=' in chunk.split('{')[0] else 'other'
                    items.append((chunk, kind))
                    start, i = end, end
                    continue
                items.append((chunk, 'func'))
                start = i + 1
        elif c == ';' and depth == 0:
            chunk = text[start:i + 1]
            items.append((chunk, 'data' if re.search(r'=', chunk) and '(' not in chunk.split('=')[0] else 'other'))
            start = i + 1
        i += 1
    if text[start:].strip():
        items.append((text[start:], 'other'))
    return items


def reduce_source(text, keep):
    """only the function KEEP keeps its body; the other functions become prototypes (inline ones stay: the
    compiler may inline them), initialised objects become extern declarations (the game has its own copy, which
    donorport names)."""
    out = []
    for chunk, kind in top_level(text):
        if kind == 'func':
            head = chunk[:chunk.find('{')]
            name = re.findall(r'(\w+)\s*\(', head)
            if name and name[-1 if '(*' not in head else 0] == keep or re.search(r'\binline\b|__inline', head):
                out.append(chunk)
            else:
                out.append(re.sub(r'\bstatic\s+', '', head.rstrip()) + ';')
        elif kind == 'data':
            decl = chunk.split('=')[0].rstrip()
            decl = re.sub(r'\bstatic\s+', '', decl)
            out.append('extern ' + decl.lstrip() + ';')
        else:
            out.append(chunk)
    return '\n'.join(out)


def functions_of(obj):
    d = obj.read_bytes()
    secs = wb.elf_sections(d)
    return [s['name'] for s in wb.elf_symbols(d, secs) if s['type'] == 2 and s['name'] and s['size'] > 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('repo')
    ap.add_argument('revs', nargs='+')
    ap.add_argument('--files', default='*.c', help='source files to compile (glob, relative to the repository)')
    ap.add_argument('--exclude', default='*example*,*test*', help='comma-separated globs to leave out')
    ap.add_argument('--settings', type=int, default=6, help="how many of the game's settings (most used first)")
    ap.add_argument('--profiles', default='', help="';'-separated 'PROFILE [flags]' list instead of the game's "
                                                   "settings (a game with nothing matched has only its default)")
    ap.add_argument('--define', action='append', default=[],
                    help='macro for every compile, e.g. --define "STIN=static inline" (Tremor only defines it '
                         'for gcc and Windows; a DS port had to)')
    a = ap.parse_args()
    DEFINES.extend(a.define)
    game = Path.cwd()
    repo = Path(a.repo).resolve()
    lib = repo.name
    work = game / 'build' / 'libdonor' / lib
    sysinc = work / 'sysinc'
    for name, text in SYSINC.items():
        (sysinc / name).parent.mkdir(parents=True, exist_ok=True)
        (sysinc / name).write_text(text, encoding='utf-8')
    if a.profiles:
        settings = [(p.strip(), p.strip().partition(' ')[0], p.strip().partition(' ')[2]) for p in a.profiles.split(';')
                    if p.strip()]
    else:
        settings = c2asm.game_settings(game, 'auto', False, 3)[:a.settings]
    by_size = collections.defaultdict(list)  # size -> [(bytes, func, pp file, profile, rev)]
    errors = collections.Counter()
    for rev in a.revs:
        src = work / 'src' / rev
        export(repo, rev, src)
        files = [p for p in sorted(src.rglob('*.c')) if fnmatch.fnmatch(p.relative_to(src).as_posix(), a.files)
                 and not any(fnmatch.fnmatch(p.name, x) for x in a.exclude.split(','))]
        for label, prof, extra in settings:
            tag = re.sub(r'[^\w.-]+', '_', label)
            od = work / 'obj' / rev / tag
            od.mkdir(parents=True, exist_ok=True)
            for f in files:
                obj, pp = od / (f.stem + '.o'), od / (f.stem + '.pp.c')
                err = compile_file(game, prof, extra, f, [src, f.parent, sysinc], obj, pp)
                if err:
                    errors[f'{rev} {label} {f.name}: {err.strip().splitlines()[-1][:120]}'] += 1
                    continue
                for fn in functions_of(obj):
                    b = pc.compiled_function(obj, fn)
                    if b:
                        by_size[len(b)].append((b, fn, str(pp), label, rev))
    n_funcs = sum(len(v) for v in by_size.values())
    print(f'{lib}: {len(a.revs)} revisions x {len(settings)} settings -> {n_funcs} compiled functions; '
          f'{sum(errors.values())} compile errors', file=sys.stderr)
    for e in list(errors)[:6]:
        print('   ', e, file=sys.stderr)
    rep = next(p / 'report.json' for p in (game / 'build').iterdir() if (p / 'report.json').exists() and (p / 'asm').is_dir())
    r = json.loads(rep.read_text())
    todo = [f['name'] for u in r['units'] for f in u.get('functions', []) if f.get('fuzzy_match_percent', 0) < 100]
    pairs, near = [], []
    for name in todo:
        try:
            wb.select_module(name)
            f = wb.function(name)
        except (Exception, SystemExit):  # wb.function exits on a name it does not know (BuildInfo...)
            continue
        cands = by_size.get(f['size'])
        if not cands or f.get('mode') == 'thumb':
            continue
        target = pc.target_bytes(f['addr'], f['size'])
        best = None
        for b, fn, pp, label, rev in cands:
            bad, n = pc.compare(target, b)
            if bad == 0:
                pairs.append((name, fn, pp, label, rev))
                best = None
                break
            if best is None or bad < best[0]:
                best = (bad, n, fn, label, rev)
        if best and best[0] <= max(2, best[1] // 20):
            near.append({'target': name, 'donor': best[2], 'diffs': best[0], 'total': best[1], 'profile': best[3],
                         'rev': best[4]})
    print(f'{len(todo)} unmatched functions, {len(pairs)} identical after masking, {len(near)} near', file=sys.stderr)
    out = []
    hunt = game / 'build' / 'hunt' / 'libdonor'
    hunt.mkdir(parents=True, exist_ok=True)
    for name, fn, pp, label, rev in pairs:
        reduced = reduce_source(Path(pp).read_text(encoding='utf-8'), fn)
        rpath = Path(pp).with_name(f'{Path(pp).stem}.{fn}.c')  # the donor source donorport reads (one function)
        rpath.write_text(reduced, encoding='utf-8', newline='\n')
        pp = str(rpath)
        text = re.sub(r'\b' + re.escape(fn) + r'\b', name, reduced)
        path = hunt / f'{name}.c'
        path.write_text(text, encoding='utf-8', newline='\n')
        wb.select_module(name)
        j = wb.judge(name, text, label) or {}
        out.append({'target': name, 'donor': fn, 'donor_file': str(Path(pp)), 'profile': label, 'rev': rev,
                    'status': j.get('status'), 'diffs': j.get('diffs'), 'rules': (j.get('rules') or {}).get('status')})
    (work / 'matches.jsonl').write_text('\n'.join(json.dumps(x) for x in out), encoding='utf-8')
    (work / 'near.jsonl').write_text('\n'.join(json.dumps(x) for x in near), encoding='utf-8')
    st = collections.Counter(x['status'] for x in out)
    print(json.dumps({'lib': lib, 'compiled': n_funcs, 'pairs': len(pairs), 'judged': dict(st), 'near': len(near)}))


if __name__ == '__main__':
    main()
