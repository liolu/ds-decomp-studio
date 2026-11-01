"""batchsubmit.py DIR [DIR...] : submit the matches of agent rounds in ONE build, for games whose link is slow.

`workbench submit` links once per function and `submit-many` bisects a failing group: with a 35 min link (Sims 2, 6200
objects) neither ends. This integrates every match of DIR/results.json (status match, the file DIR/NAME.c, its profile),
then find_culprits.repair compares the ROM byte by byte, drops only the files that break it (moved to build/culprits/,
never committed ones) and rebuilds. What survives goes to the pending list, also the files of an earlier interrupted
job that delinks.txt already declares but no commit has: `workbench commit` commits config/ whole, so they must go with it.
Run from the game dir. Then `workbench.py commit`."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import workbench as wb  # noqa: E402
import find_culprits  # noqa: E402

items, seen = [], set()
am, project, ROOT = wb.am, wb.project, wb.ROOT
for d in map(Path, sys.argv[1:]):
    res = json.loads((d / 'results.json').read_text(encoding='utf-8'))
    for n, r in res.items():
        if not r.get('match') or n in seen:
            continue
        wb.select_module(n)
        f = wb.function(n)
        if wb.covered(f['addr']):
            continue
        if not am.MAIN_TEXT[0] <= f['addr'] < am.MAIN_TEXT[1]:
            print('not in .text', n, flush=True)
            continue
        src = (d / f'{n}.c').read_text(encoding='utf-8', errors='replace')
        if r['profile'] != f'{am.COMPILERS[0][0]} {am.COMPILERS[0][1]}'.strip() and not src.startswith(am.MARKER):
            src = f"{am.MARKER}{r['profile']} */\n" + src
        seen.add(n)
        items.append((f, src))
print(len(items), 'matches to integrate', flush=True)
with wb.pipeline_lock('workbench'):
    files = [project.DELINKS, am.COMPILERS_TXT, project.SYMBOLS]
    wb.journal_begin(files)
    created = []
    for f, src in items:
        wb.select_module(f['name'])
        created += am.integrate([(f['name'], f['size'], f['addr'], src)])
    wb.journal_created(created)
    wb.clang_format(created)
    wb.journal_end()  # from here culprits are dropped one by one, nothing to undo as a whole
    t0 = time.time()
    ok, dropped = find_culprits.repair(find_culprits.all_new_files(), rounds=6)
    print(f'ROM {"OK" if ok else "STILL DIFFERS"} after {int(time.time() - t0)} s, dropped {len(dropped)}: {dropped}', flush=True)
    if ok:
        pend = wb.load_pending()
        have = {p['file'] for p in pend}
        stamp = time.strftime('%Y-%m-%d %H:%M')
        names = {f['name'] for f, _ in items}
        for rel in sorted(find_culprits.all_new_files()):
            if rel in have or rel in dropped or not (ROOT / rel).exists() or not rel.startswith('src/'):
                continue
            n = Path(rel).stem
            pend.append({'name': n, 'file': rel, 'who': 'claude' if n in names else 'auto', 'time': stamp})
        wb.save_pending(pend)
        print('pending', len(pend), flush=True)
