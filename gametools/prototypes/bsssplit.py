"""bsssplit.py GAP.json [--dry-run] : cover the .bss ranges that bssgen leaves (symbols at odd / 2-byte addresses inside a
block, e.g. data_020714f5) with ONE C file per symbol, typed by its alignment: u32[] when address and size are multiples
of 4, u16[] for 2, else `struct { u8 b[N]; }` (alignment 1; a plain u8[] becomes a common symbol and loses its place).
Why one file per object: mwcc sorts the .bss objects of one file (smallest first), so two objects in one file do not
keep the address order. GAP.json = `datagap.py --json` output; only main-module .bss ranges starting on a symbol are
handled. Appends the delinks entries; run `configure.py` + `match.py verify` after.
Technique id: bss-split. Origin: TnJ s34 (2026-10-29)."""
import json, re, sys
from pathlib import Path

VERSION = 'eu'


def main():
    a = sys.argv[1:]
    dry = '--dry-run' in a
    gaps = json.loads(Path(a[0]).read_text())
    syms = {}
    for line in open(f'config/{VERSION}/arm9/symbols.txt', encoding='utf-8'):
        m = re.match(r'(\S+) kind:bss addr:0x([0-9a-f]+)', line)
        if m:
            syms[int(m.group(2), 16)] = m.group(1)
    blocks = []
    for g in gaps:
        if g['mod'] != 'main' or g['sec'] != '.bss' or g['start'] not in syms:
            continue
        cuts = sorted(k for k in syms if g['start'] <= k < g['end']) + [g['end']]
        for s, e in zip(cuts, cuts[1:]):
            name, size = syms[s], e - s
            if s % 4 == 0 and size % 4 == 0:
                decl = f'u32 {name}[{size // 4}];\n'
            elif s % 2 == 0 and size % 2 == 0:
                decl = f'u16 {name}[{size // 2}];\n'
            else:
                decl = f'typedef struct {{\n    u8 b[{size}];\n}} {name}_t;\n{name}_t {name};\n'
            path = f'src/data/main_bss_{s:08x}.c'
            if Path(path).exists():
                print('exists, skipped:', path)
                continue
            print(f'{path}: {size} bytes')
            if not dry:
                Path(path).write_text(f'/* compiler: 2.0/sp1p5 */\n#include "m2c.h"\n\n{decl}', encoding='utf-8', newline='\n')
            blocks.append(f'{path}:\n    complete\n    .bss        start:0x{s:08x} end:0x{e:08x}\n')
    if not dry and blocks:
        p = Path(f'config/{VERSION}/arm9/delinks.txt')
        p.write_text(p.read_text(encoding='utf-8').rstrip('\n') + '\n\n' + '\n'.join(blocks), encoding='utf-8', newline='\n')
    print(len(blocks), 'files')


if __name__ == '__main__':
    main()
