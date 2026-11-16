"""profprior.py - which compiler profile an unmatched function most likely needs, from the files already matched.

    python ../../studio/gametools/prototypes/profprior.py eval            # leave-one-out accuracy on this game
    python ../../studio/gametools/prototypes/profprior.py eval --all      # every game in projets/ (one line each)
    python ../../studio/gametools/prototypes/profprior.py show NAME|0xADDR
    python ../../studio/gametools/prototypes/profprior.py census          # the game's profiles, most used first

Run from the project dir (projets/<game>). Nothing is written.

Why (2026-11-16): every game records the profile of each matched file in config/<ver>/compilers.txt (files not listed
use game.toml mwcc_version). Nothing read it back: auto_match / hunt / agentround only try a fixed list plus
AUTO_EXTRA_PROFILES, so game-specific profiles (Cooking Mama: 268 files `1.2/sp2p3 -O4,p -lang c99 -inline on,noauto`;
11k files over all games `2.0/sp1p5 -O4,p -lang c99 -ipa file -inline on,noauto`; `1.2/b56`, `-O4,s`, `-profile`...)
were never tried on new functions. Original translation units are contiguous in the ROM and one TU = one set of
flags, so the profiles of the nearest matched neighbours are a strong prior.

API (used by auto_match.profiles_for): `prior(root).predict(addr, k)` -> [(profile, weight)], best first;
`prior(root).census()` -> [(profile, count)].
"""
import bisect
import collections
import functools
import re
import sys
from pathlib import Path

SEC = re.compile(r'^\s+\.text\s+start:0x([0-9a-fA-F]+)\s+end:0x([0-9a-fA-F]+)', re.M)


def _default_version(root: Path) -> str:
    t = root / 'game.toml'
    if t.exists():
        m = re.search(r'^mwcc_version\s*=\s*"([^"]+)"', t.read_text(encoding='utf-8', errors='replace'), re.M)
        if m:
            return m.group(1)
    return '2.0/sp1p5'


def _norm(p: str) -> str:
    """'1.2/sp2p3 -O4,p' and '1.2/sp2p3' are the same build (-O4,p is the default level)."""
    v, _, extra = p.strip().partition(' ')
    toks = extra.split()
    if toks[:1] == ['-O4,p'] and len(toks) == 1:
        toks = []
    return ' '.join([v] + toks)


class Prior:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.default = _default_version(self.root)
        cfgs = sorted(p for p in (self.root / 'config').iterdir() if p.is_dir()) if (self.root / 'config').is_dir() else []
        # the version in use: the one with compilers.txt, else the first
        cfg = next((c for c in cfgs if (c / 'compilers.txt').exists()), cfgs[0] if cfgs else None)
        self.prof = {}
        if cfg and (cfg / 'compilers.txt').exists():
            for line in (cfg / 'compilers.txt').read_text(encoding='utf-8', errors='replace').splitlines():
                if not line.strip() or line.startswith('#'):
                    continue
                f, _, p = line.partition(' ')
                if p.strip():
                    self.prof[f] = _norm(p)
        # module (delinks file) -> sorted [(start, end, file)]
        self.mods = collections.defaultdict(list)
        if cfg:
            for dl in cfg.rglob('delinks.txt'):
                body = dl.read_text(encoding='utf-8', errors='replace').split('\n\n', 1)
                if len(body) < 2:
                    continue
                for block in body[1].split('\n\n'):
                    head = block.strip().split('\n', 1)[0].strip()
                    if not head.endswith(':'):
                        continue
                    m = SEC.search(block)
                    if m:
                        s, e = int(m.group(1), 16), int(m.group(2), 16)
                        if e > s:
                            self.mods[dl].append((s, e, head[:-1]))
        for v in self.mods.values():
            v.sort()
        self.starts = {k: [x[0] for x in v] for k, v in self.mods.items()}

    def profile_of(self, f: str) -> str:
        return self.prof.get(f, self.default)

    def census(self):
        c = collections.Counter(self.profile_of(f) for v in self.mods.values() for _, _, f in v)
        return c.most_common()

    def module_of(self, addr: int):
        for k, v in self.mods.items():
            if not v:
                continue
            i = bisect.bisect_right(self.starts[k], addr) - 1
            lo, hi = v[0][0], v[-1][1]
            if lo - 0x4000 <= addr < hi + 0x4000:
                return k, i
        return None, None

    def predict(self, addr: int, k: int = 3, skip: str | None = None):
        """Profiles of the k nearest matched files before and after addr (same module), weighted 1/rank."""
        mod, i = self.module_of(addr)
        if mod is None:
            return []
        v = self.mods[mod]
        w = collections.Counter()
        before = [x for x in v[max(0, i - k - 1):i + 1] if x[2] != skip and x[0] <= addr][-k:][::-1]
        after = [x for x in v[i + 1:i + k + 2] if x[2] != skip and x[0] > addr][:k]
        for side in (before, after):
            for r, (_, _, f) in enumerate(side):
                w[self.profile_of(f)] += 1.0 / (r + 1)
        return w.most_common()


@functools.lru_cache(maxsize=4)
def prior(root) -> Prior:
    return Prior(Path(root))


def _eval(root: Path, k: int = 3):
    p = Prior(root)
    tot = top1 = top3 = base = nd = nd1 = 0
    cen = p.census()
    if not cen:
        return None
    common = cen[0][0]
    for v in p.mods.values():
        for s, e, f in v:
            want = p.profile_of(f)
            pr = [x for x, _ in p.predict(s, k, skip=f)]
            if not pr:
                continue
            tot += 1
            top1 += pr[0] == want
            top3 += want in pr[:3]
            base += want == common
            if want != common:
                nd += 1
                nd1 += pr[0] == want
    return dict(files=tot, top1=top1, top3=top3, base=base, rare=nd, rare_top1=nd1, profiles=len(cen), common=common)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    if a[0] == 'eval':
        roots = [Path.cwd()]
        if '--all' in a:
            roots = sorted(d for d in (Path.cwd().parent if (Path.cwd() / 'game.toml').exists() else Path.cwd()).iterdir()
                           if (d / 'game.toml').exists())
        for r in roots:
            try:
                e = _eval(r)
            except Exception as x:  # noqa: BLE001
                print(f'{r.name:45} error {x}'); continue
            if not e or not e['files']:
                continue
            pc = lambda n, d: f'{100 * n / d:5.1f}%' if d else '   - '
            print(f"{r.name:45} files {e['files']:5}  profiles {e['profiles']:2}  base {pc(e['base'], e['files'])}  "
                  f"top1 {pc(e['top1'], e['files'])}  top3 {pc(e['top3'], e['files'])}  "
                  f"not-common {e['rare']:5} found {pc(e['rare_top1'], e['rare'])}")
    elif a[0] == 'census':
        for prof, n in prior(Path.cwd()).census():
            print(f'{n:6} {prof}')
    elif a[0] == 'show':
        x = a[1]
        if x.startswith('0x'):
            addr = int(x, 16)
        else:
            m = re.search(r'([0-9a-f]{8})$', x)
            addr = int(m.group(1), 16)
        for prof, w in prior(Path.cwd()).predict(addr):
            print(f'{w:5.2f} {prof}')


if __name__ == '__main__':
    main()
