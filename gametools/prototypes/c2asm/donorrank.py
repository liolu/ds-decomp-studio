"""Rank unmatched functions of the current game by how much ONE matched function (any game) covers them with
linemine fragments. Prints JSON lines: target, donor game, donor func, covered/len."""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1])))
import c2asm  # noqa: E402
import linemine  # noqa: E402

game = Path.cwd()
others = sys.argv[2:]
frags = linemine.load_frags(game, others)
for f in frags:
    f.setdefault('game', game.name)
lib = linemine.Library(frags, 3)
# donor function sizes (instructions in fragments) to prefer donors of the same size
dsize = collections.Counter()
for f in frags:
    dsize[(f['game'], f['func'])] += len(f['asm'])
todo, body = c2asm.target_funcs(game, False)
rows = []
for fn, seq in body.items():
    if len(seq) < 8:
        continue
    cov = collections.defaultdict(set)
    for i, sig, frs in lib.hits(seq):
        for d in {(x['game'], x['func']) for x in frs}:
            if d[0] == game.name and d[1] == fn:
                continue
            cov[d].update(range(i, i + len(sig)))
    if not cov:
        continue
    best = max(cov, key=lambda d: (len(cov[d]), -abs(dsize[d] - len(seq))))
    rows.append({'target': fn, 'len': len(seq), 'donor_game': best[0], 'donor': best[1],
                 'covered': len(cov[best]), 'ratio': round(len(cov[best]) / len(seq), 3),
                 'donor_len': dsize[best]})
rows.sort(key=lambda r: -r['ratio'])
for r in rows:
    print(json.dumps(r))
