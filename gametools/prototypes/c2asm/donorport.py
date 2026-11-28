"""donorport.py - turn a whole-function donor match (donortry.py) into a source for this game.

    cd <game>
    python <studio>/gametools/prototypes/c2asm/donorport.py TARGET DONOR_FILE DONOR_FUNC "PROFILE" OUT.c

The donor file (its own source, not the preprocessed blob) is renamed DONOR_FUNC -> TARGET, compiled with PROFILE,
and every symbol it calls or loads is renamed to the symbol this game has at the same place (the bytes are
identical, so the relocations sit at the same offsets: object relocations of the donor vs relocs.txt of the game).
Then judged. Prints one JSON line: renames, unresolved symbols, judge result.
Prototype 2026-11-27 (Heroes of Mana, 4 donor matches from Lego SW2 / Tom and Jerry).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import workbench as wb  # noqa: E402


def word_rename(src, names):
    if not names:
        return src
    pat = re.compile(r'\b(' + '|'.join(re.escape(k) for k in sorted(names, key=len, reverse=True)) + r')\b')
    return pat.sub(lambda m: names[m.group(1)], src)


def object_relocs(objbytes, name):
    """{offset in the function: symbol name} of NAME in a compiled object."""
    secs = wb.elf_sections(objbytes)
    syms = wb.elf_symbols(objbytes, secs)
    rel = wb.elf_relocs(objbytes, secs, syms)
    s = next((x for x in syms if x['name'] == name and x['shndx'] < len(secs)), None)
    if s is None:
        return None
    return {off - s['value']: nm for off, nm in rel.get(s['shndx'], {}).items()
            if s['value'] <= off < s['value'] + max(s['size'], 1)}


_MODSYMS = {}


def module_symbols(module):
    """symbols of a relocs.txt module (main, overlay(N), itcm, dtcm): [{name, kind, addr}]."""
    if module not in _MODSYMS:
        m = re.match(r'overlay\((\d+)\)', module or '')
        p = (wb.OVL_DIR / f'ov{int(m.group(1)):03d}' / 'symbols.txt' if m else
             wb.project.ARM9 / module / 'symbols.txt' if module in ('itcm', 'dtcm') else
             wb.project.ARM9 / 'symbols.txt')
        out = []
        if p.exists():
            for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
                s = wb.SYM.match(line)
                if s:
                    out.append({'name': s.group(1), 'kind': s.group(2), 'addr': int(s.group(4), 16)})
        _MODSYMS[module] = out
    return _MODSYMS[module]


def game_name_at(to, module=None):
    """the game's symbol at address TO (in MODULE when given), or name+0xN inside an object."""
    best = None
    for s in (module_symbols(module) if module else wb.symbols()):
        if s['addr'] == to:
            return s['name']
        if s['addr'] < to and s['kind'] in ('data', 'bss') and (best is None or s['addr'] > best['addr']):
            best = s
    if best and to - best['addr'] < 0x10000:
        return f"{best['name']}+0x{to - best['addr']:x}"
    return None


def main():
    target, donor_file, donor_func, profile, out = sys.argv[1:6]
    wb.select_module(target)
    f = wb.function(target)
    src = Path(donor_file).read_text(encoding='utf-8', errors='replace')
    # the donor's own `/* compiler: ... */` line names the DONOR's profile: submit keeps a first-line marker as it
    # is, so a stale one builds the function with the wrong compiler (USM 2026-11-28: 1.2/b56 match built with
    # 1.2/sp2p3, 4 bytes short, everything after it shifted). Drop it: submit writes the judged profile.
    src = re.sub(r'\A\s*/\* compiler:[^*]*\*/[ \t]*\n', '', src)
    # `#pragma thumb off/on` of a donor whose default is Thumb: a new pragma is refused as a fake match, and the
    # profile (with or without -thumb) already gives the mode; judge decides whether the bytes still match
    src = re.sub(r'^[ \t]*#pragma[ \t]+thumb[ \t]+(off|on|reset)[ \t]*\n', '', src, flags=re.M)
    src = word_rename(src, {donor_func: target})
    objbytes, msg, obj, tmp = wb.compile_one(src, profile)
    tmp.cleanup()
    if objbytes is None:
        print(json.dumps({'target': target, 'ok': False, 'error': 'compile', 'msg': msg[-600:]}))
        return
    ours = object_relocs(objbytes, target)
    theirs = {fr - f['addr']: (to, mod) for fr, kind, to, mod in wb.relocs_in(f['addr'], f['addr'] + f['size'])}
    renames, unresolved, implicit, cpp = {}, [], {}, set()
    for off, nm in sorted((ours or {}).items()):
        base, _, add = nm.partition('+')
        add = int(add, 16) if add and not add.startswith('0x-') else 0  # ARM calls carry -8 (pc bias)
        z = re.match(r'_Z(\d+)', base)  # C++ name in the donor: the source spells the plain identifier
        ident = base[z.end():z.end() + int(z.group(1))] if z else base
        if z:
            cpp.add(ident)
        if off not in theirs:
            unresolved.append(f'{nm}@{off:#x}: no relocation in the game')
            continue
        gname = game_name_at(theirs[off][0] - add, theirs[off][1])
        if gname is None:
            unresolved.append(f'{nm}@{off:#x}: nothing at {theirs[off][0]:#x}')
            continue
        if gname.startswith('.L_'):  # a dsd local label: integrate() globalises lbl_ADDR
            gname = 'lbl_' + gname[3:]
        if '+' in gname:
            unresolved.append(f'{nm} vs {gname}: inside an object')
            continue
        if ident == gname:
            continue
        if renames.get(ident, gname) != gname or implicit.get(ident, gname) != gname:
            unresolved.append(f'{ident}: both {renames.get(ident) or implicit.get(ident)} and {gname}')
            continue
        if re.search(r'\b' + re.escape(ident) + r'\b', src):
            renames[ident] = gname
        else:  # called by the compiler itself (_f2d, _ll_sdiv...): the game symbol must take the runtime name
            implicit[ident] = gname
    src = word_rename(src, renames)
    # a C++ donor declared its callees as C++ functions: under the game's (C) names they need extern "C"
    for ident in cpp:
        g = renames.get(ident)
        if g:
            src = re.sub(r'^(\s*)extern\s+(?!"C")([^;\n]*\b' + re.escape(g) + r'\s*\([^;\n]*;)',
                         r'\1extern "C" \2', src, flags=re.M)
    Path(out).write_text(src, encoding='utf-8', newline='\n')
    r = wb.judge(target, src, profile)
    print(json.dumps({'target': target, 'renames': renames, 'implicit_runtime': {g: i for i, g in implicit.items()},
                      'unresolved': unresolved,
                      'judge': {k: r.get(k) for k in ('status', 'match', 'profile', 'diffs', 'rules')}}))


if __name__ == '__main__':
    main()
