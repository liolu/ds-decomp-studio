"""stmtcount.py FILE.c [FUNC] : pcode count of the current block at each codegen statement (FUN_004ffc90).
mwcc 2.0/sp1p5 starts a new scheduling block when a statement begins with > 100 pcodes in the current block."""
import sys, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent)); import radump
JS = r"""
const STMT = ptr('0x004ffc90'), CUR = ptr('0x0063a224'), CG = ptr('0x00471850');
let depth = 0;
Interceptor.attach(CG, { onEnter() { send({fn: 'start'}); } });
Interceptor.attach(STMT, { onEnter(a) {
  const b = CUR.readPointer(); send({line: a[0].toInt32() & 0xffff, blk: b.add(0x1c).readS32(), n: b.add(0x28).readS16()}); } });
"""
f = sys.argv[1]; dev = frida.get_local_device()
args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
t0 = time.time()
while not done and time.time() - t0 < 60: time.sleep(0.05)
src = Path(f).read_text().split("\n")
for e in ev:
    if "fn" in e: print("--- function"); continue
    l = e["line"]
    print(f"line {l:4d} block {e['blk']:3d} pcodes {e['n']:4d}  | {src[l-1].strip()[:70] if 0 < l <= len(src) else ''}")
