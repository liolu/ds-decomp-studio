"""optrace.py FILE.c LO HI : backtrace of every pcode created with opcode in [LO, HI] (FUN_004f8370 and siblings)."""
import sys, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent)); import radump
lo, hi = int(sys.argv[2], 0), int(sys.argv[3], 0)
JS = r"""
const MK = [ptr('0x004f8370')];
MK.forEach(f => Interceptor.attach(f, { onEnter(a) { const op = a[0].toInt32();
  if (op >= LO && op <= HI) send({op: op, bt: Thread.backtrace(this.context, Backtracer.FUZZY).slice(0, 7).map(x => x.toString())}); } }));
""".replace("LO", str(lo)).replace("HI", str(hi))
f = sys.argv[1]; dev = frida.get_local_device()
args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
t0 = time.time()
while not done and time.time() - t0 < 60: time.sleep(0.05)
import collections
c = collections.Counter((e["op"], tuple(e["bt"])) for e in ev)
for (op, bt), n in c.most_common(20): print(hex(op), n, " ".join(bt))
