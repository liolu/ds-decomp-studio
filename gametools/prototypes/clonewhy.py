"""clonewhy.py [NAME...] : why clone_match keeps no candidate, it never says. Default names: every unmatched function with a matched twin.
For each candidate twin prints the reason of `check` per variant (first 3), or `no source` / `pair_maps failed`. Nothing changes. Run from the game dir."""
import collections, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clone_match as cm  # noqa: E402


def main():
    img = cm.Image(cm.ROOT)
    others = cm.other_images()
    ex, tp = cm.families(img, others)
    matched = img.matched()
    sources = {(img, n): matched[n] for n in matched}
    for im in others:
        for n, f in im.matched().items():
            sources[(im, n)] = f
    wanted = set(sys.argv[1:])
    total = collections.Counter()
    for n in img.funcs:
        if n in matched or (wanted and n not in wanted):
            continue
        e, t = cm.shapes(img.code(n))
        cands = [(im, s, 'dup' if im is img else 'game') for im, s in ex.get(e, []) if (im, s) in sources]
        cands += [(im, s, 'template') for im, s in tp.get(t, []) if im is img and (im, s) in sources]
        if not cands:
            if wanted:
                print(n, 'no twin')
            continue
        for im, s, kind in cands[:3]:
            path = sources[(im, s)]
            base = im.source_of(s, path)
            tag = f'{n} <- {im.root.name}:{s} [{kind}] {path}'
            if base is None:
                print(tag, ': no source')
                total['no source'] += 1
                continue
            pm = cm.pair_maps(im, s, img, n)
            if pm is None:
                print(tag, ': pair_maps failed')
                total['pair_maps failed'] += 1
                continue
            names, nums = pm
            profile = im.profile(path)
            why = collections.Counter()
            for cand in (c for v in cm.or_variants(cm.rename(base, names), nums) for c in cm.with_constants(v, nums)):
                r = cm.check(img, n, cand, profile)
                why[r or 'MATCH'] += 1
                if not r:
                    break
            print(tag, profile, ':', dict(why.most_common(3)))
            total[why.most_common(1)[0][0].split(' ')[0] if why else 'no variant'] += 1
    print(total)


if __name__ == '__main__':
    main()
