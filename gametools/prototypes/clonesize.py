"""clonesize.py NAME GAME SOURCE_NAME : show what a clone compiles to under this game's CC_FLAGS versus under the source game's own flags.
Diagnoses clone_match `size` refusals. Run from the game dir. Prints both flag lines, sizes, and the objdump of the first."""
import subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clone_match as cm  # noqa: E402

name, game, sname = sys.argv[1:4]
img = cm.Image(cm.ROOT)
oth = next(i for i in cm.other_images() if i.root.name == game)
path = oth.matched()[sname]
base = oth.source_of(sname, path)
names, nums = cm.pair_maps(oth, sname, img, name)
src = cm.rename(base, names)
profile = oth.profile(path)
other_flags = cm._configure_value(oth.root, 'CC_FLAGS', '?')
print('target size', len(img.code(name)), 'profile', profile)
print('this game CC_FLAGS :', cm.CC_FLAGS)
print('source game CC_FLAGS:', other_flags)
print(src[:600])
version, _, flags = profile.partition(' ')
mwcc = cm.am.MWCC_ROOT / version / 'mwccarm.exe'
for label, cc in (('this', cm.CC_FLAGS), ('source', other_flags), ('none', '')):
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'f.c').write_text(src, encoding='utf-8')
        cmd = f'"{mwcc}" {cc} -lang=c {flags} -i "{cm.ROOT / "include"}" -d {cm.project.VERSION} -c f.c -o f.o'
        r = cm.am.run_limited(cmd, cwd=t, shell=True)
        if not (t / 'f.o').exists():
            print(label, 'compile failed', (r.stdout or '')[:300], (r.stderr or '')[:300])
            continue
        obj = cm.donorlib.Obj(t / 'f.o')
        print(label, [(f[0], f[3]) for f in obj.functions()])
        if label == 'this':
            print(subprocess.run(['arm-none-eabi-objdump', '-d', str(t / 'f.o')], capture_output=True, text=True).stdout[:1200])
