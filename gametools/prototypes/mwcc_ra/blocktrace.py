"""blocktrace.py FILE.c FUNC : who creates each pcode block (FUN_004f85e0) during codegen of FUNC (Frida backtrace)."""
import sys, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent)); import radump
JS = r"""
const NEWB = ptr('0x004f85e0'), CURFN = ptr('0x0063a79c'), CODEGEN = ptr('0x00471850');
let infn = false, name = '';
Interceptor.attach(CODEGEN, { onEnter(a) { infn = true; }, onLeave() { infn = false; } });
Interceptor.attach(NEWB, { onEnter() {
  const bt = Thread.backtrace(this.context, Backtracer.FUZZY).slice(0, 8).map(x => x.toString());
  send({bt: bt});
}, onLeave(r) { send({blk: r.add(0x1c).readS32()}); } });
"""
f, func = sys.argv[1], sys.argv[2]
dev = frida.get_local_device()
args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
t0 = time.time()
while not done and time.time() - t0 < 60: time.sleep(0.05)
bt = None
for e in ev:
    if "bt" in e: bt = e["bt"]
    else: print(f"block {e['blk']:3d} <- " + " ".join(bt))
