"""clonesrc.py NAME GAME SOURCE_NAME [--raw] : print the source clone_match would compile for NAME from SOURCE_NAME of GAME (--raw: before renames)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clone_match as cm  # noqa: E402

name, game, sname = sys.argv[1:4]
img = cm.Image(cm.ROOT)
oth = img if game == img.root.name else next(i for i in cm.other_images() if i.root.name == game)
path = oth.matched()[sname]
base = oth.source_of(sname, path)
if '--raw' in sys.argv:
    print(base)
else:
    names, nums = cm.pair_maps(oth, sname, img, name)
    print('names', names, 'nums', nums)
    print(cm.rename(base, names))
