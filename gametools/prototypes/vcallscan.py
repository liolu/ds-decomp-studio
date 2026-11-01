"""vcallscan.py OUT.json [--max-size B] : census of the unmatched ARM functions for the cpp-vcall and nointerworking levers.

For each function still unmatched, from the target bytes: `cpp` = count of `ldr rN,[r0]; ldr rN,[rN,#K]; blx rN` right
after an instruction that writes r0 (`mov r0,rX`, a load into r0), the order C never gives; `vc` = every vtable call
(`ldr rN,[rM]; ldr rN,[rN,#K]; blx rN`); `movpc` = returns `mov pc, lr` under any condition. Also the best earlier file
of the function among build/hunt/*/all/results.json + */results.json (`best`, `status`, `diffs`, `profile`).
Run from the game dir."""
import json, sys, struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunt  # noqa: E402
import workbench as wb  # noqa: E402

RANK = {'near': 0, 'size': 1, 'compile': 2}


def scan(raw: bytes) -> dict:
    w = [x[0] for x in struct.iter_unpack('<I', raw[:len(raw) & ~3])]
    cpp = vc = movpc = 0
    for i, x in enumerate(w):
        if x & 0x0fffffff == 0x01a0f00e:
            movpc += 1
        if x & 0xfffffff0 != 0xe12fff30 or i < 2:
            continue
        n = x & 15
        a, b = w[i - 2], w[i - 1]
        if b & 0xfff00000 != 0xe5900000 or (b >> 16) & 15 != n or (b >> 12) & 15 != n:  # ldr rN,[rN,#K]
            continue
        if a & 0xfff00fff != 0xe5900000 or (a >> 12) & 15 != n:  # ldr rN,[rM]
            continue
        vc += 1
        if (a >> 16) & 15 == 0 and i >= 3:
            p = w[i - 3]
            if p & 0x0ffff000 == 0x01a00000 or (p & 0x0c500000 == 0x04100000 and (p >> 12) & 15 == 0):
                cpp += 1
    return {'cpp': cpp, 'vc': vc, 'movpc': movpc}


def best_files() -> dict:
    best = {}
    H = Path('build/hunt')
    for res in [*H.glob('*/all/results.json'), *H.glob('*/results.json')]:
        try:
            d = json.loads(res.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for n, r in d.items():
            f = res.parent / f'{n}.c'
            st = r.get('status')
            if st not in RANK or not f.exists():
                continue
            k = r.get('k')
            diffs = k[1] if isinstance(k, list) and len(k) > 1 else 9999
            key = (RANK[st], diffs)
            if n not in best or key < best[n][0]:
                best[n] = (key, str(f), st, diffs, r.get('profile'))
    return best


if __name__ == '__main__':
    best = best_files()
    out = {}
    for n, size in sorted(hunt.unmatched_sizes().items()):
        try:
            wb.select_module(n)
            f = wb.find(n)
            if f is None or f['kind'] != 'function' or f['mode'] == 'thumb' or wb.covered(f['addr']):
                continue
            r = scan(wb.pc.target_bytes(f['addr'], f['size']))
        except (SystemExit, Exception) as e:
            print('skip', n, e, flush=True)
            continue
        r['size'] = f['size']
        if n in best:
            _, r['best'], r['status'], r['diffs'], r['profile'] = best[n]
        out[n] = r
    Path(sys.argv[1]).write_text(json.dumps(out, indent=0), encoding='utf-8', newline='\n')
    print(len(out), 'unmatched ARM,', sum(1 for r in out.values() if r['cpp']), 'cpp order,',
          sum(1 for r in out.values() if r['vc']), 'any vcall,', sum(1 for r in out.values() if r['movpc']), 'mov pc lr')
