"""Judge the whole C of the best linemine donor of each candidate (build/linemine/donorrank.jsonl, ratio >= MIN)
in the current game. Donor source preprocessed in its own game (mwcc -E), `#` lines dropped, donor name renamed.
Writes build/hunt/linemine/<target>.c and build/linemine/donortry.jsonl."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])  # decomp ds folder
MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
sys.path.insert(0, str(ROOT / 'studio/gametools/prototypes/c2asm'))
import c2asm  # noqa: E402
import linemine  # noqa: E402

GAMES = {p.name: p for p in [ROOT / 'projets/lego-star-wars-ii-the-original-trilogy', ROOT / 'projets/sims-2-the']
         + list((ROOT / 'All-nds-decomp-games/games').glob('*/*'))}
game = Path.cwd()
out_dir = game / 'build/hunt/linemine'
out_dir.mkdir(parents=True, exist_ok=True)
rows = [json.loads(l) for l in open(game / 'build/linemine/donorrank.jsonl')]
rows = [r for r in rows if r['ratio'] >= MIN]
settings_cache = {}
results = []


def donor_file(dgame, func):
    for f in list((dgame / 'src').rglob('*.c')) + list((dgame / 'src').rglob('*.cpp')):
        t = f.read_text(encoding='utf-8', errors='replace')
        if re.search(r'^[A-Za-z_][^;\n]*\b' + re.escape(func) + r'\s*\([^;]*$', t, re.M) and func + '(' in t:
            # a definition: name( ... ) followed by { somewhere after, not only a prototype
            if re.search(r'\b' + re.escape(func) + r'\s*\([^;{]*\)\s*\{', t):
                return f
    return None


for r in rows:
    dgame = GAMES.get(r['donor_game'])
    res = dict(r)
    f = donor_file(dgame, r['donor']) if dgame else None
    if not f:
        res['status'] = 'no donor source'
        results.append(res)
        print(json.dumps(res), flush=True)
        continue
    if dgame not in settings_cache:
        settings_cache[dgame] = linemine.file_settings(dgame)
    rel = f.relative_to(dgame).as_posix()
    _, lab = settings_cache[dgame].get(rel, (None, '2.0/sp1p5'))
    prof, _, extra = lab.partition(' ')
    lang = 'c++' if f.suffix == '.cpp' else 'c'
    cmd = ([str(c2asm.find_mwcc(dgame, prof))] + c2asm.game_flags(dgame) + ['-lang=' + lang] + extra.split()
           + ['-i', 'include', '-E', rel])
    pp = subprocess.run(cmd, cwd=dgame, capture_output=True, text=True, errors='replace')
    if pp.returncode != 0 or not pp.stdout.strip():
        res['status'] = 'preprocess failed'
        res['why'] = (pp.stdout + pp.stderr)[-300:]
        results.append(res)
        print(json.dumps(res), flush=True)
        continue
    src = '\n'.join(l for l in pp.stdout.splitlines() if not l.lstrip().startswith('#'))
    if r['donor'] != r['target']:
        src = re.sub(r'\b' + re.escape(r['donor']) + r'\b', r['target'], src)
    path = out_dir / (r['target'] + ('.cpp' if lang == 'c++' else '.c'))
    path.write_text(src, encoding='utf-8', newline='\n')
    j = subprocess.run(['python', str(ROOT / 'studio/gametools/workbench.py'), 'judge', r['target'], str(path)],
                       cwd=game, capture_output=True, text=True, errors='replace')
    try:
        v = json.loads(j.stdout.strip().splitlines()[-1])
    except Exception:
        v = {'status': 'judge error', 'why': (j.stdout + j.stderr)[-300:]}
    res.update({k: v.get(k) for k in ('status', 'match', 'profile', 'diffs', 'total', 'size', 'target_size', 'why')})
    if v.get('status') == 'compile':
        res['why'] = (v.get('errors') or '')[-200:]
    res['donor_file'] = f'{r["donor_game"]}/{rel}'
    results.append(res)
    print(json.dumps(res), flush=True)

(game / 'build/linemine/donortry.jsonl').write_text('\n'.join(json.dumps(x) for x in results), encoding='utf-8')
