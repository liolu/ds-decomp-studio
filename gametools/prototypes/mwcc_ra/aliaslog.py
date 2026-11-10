"""aliaslog.py FILE.c : log mwcc Alias.c FUN_00559450(object, offset, size) calls (object type kind/size, result kind)."""
import sys, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent)); import radump
JS = r"""
const F = ptr('0x00559450'), ALL = ptr('0x0063bb40');
Interceptor.attach(F, { onEnter(a) { this.o = a[0]; this.off = a[1].toInt32(); this.sz = a[2].toInt32(); },
  onLeave(r) { let tk = -1, ts = -1, nm = '';
    try { const t = this.o.add(0xc).readPointer(); tk = t.readU8(); ts = t.add(2).readS32(); } catch (e) {}
    try { const np = this.o.add(0x6).readPointer(); nm = np.add(10).readCString(); } catch (e) { nm = '?'; }
    let k = -1; try { k = r.add(0x30).readU8(); } catch (e) {}
    send([this.o.toString(), nm, tk, ts, this.off, this.sz, k, r.equals(ALL.readPointer()) ? 'ALL' : '']); } });
"""
f = sys.argv[1]; dev = frida.get_local_device()
args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
t0 = time.time()
while not done and time.time() - t0 < 60: time.sleep(0.05)
seen = set()
for e in ev:
    key = tuple(e[1:])
    if key in seen: continue
    seen.add(key)
    print(f"obj {e[0]} name {e[1]!r:20} typekind {e[2]} typesize {e[3]} off {e[4]} size {e[5]} -> kind {e[6]} {e[7]}")
