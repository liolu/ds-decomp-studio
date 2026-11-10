"""phasesnap.py FILE.c FUNC : opcode histogram (selected opcodes) of FUNC's pcode after each backend pass (Frida)."""
import sys, time, json
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent)); import radump
PASSES = {'coloring': '0x00513ca0', 'peephole': '0x0050ba40', 'fd380': '0x004fd380', 'fbf70': '0x004fbf70',
          'prolog': '0x004fd9e0', 'epilog': '0x004fe100', '03bf0': '0x00503bf0', '03c10': '0x00503c10', 'sched': '0x004ff8c0',
          'fe660': '0x004fe660'}
JS = r"""
const BLOCKS = ptr('0x0063a828'), CURFN = ptr('0x0063a79c');
function fname() { try { return CURFN.readPointer().add(8).readPointer().add(10).readCString(); } catch (e) { return '?'; } }
function snap() { const ops = []; let b = BLOCKS.readPointer(); let g = 0;
  while (!b.isNull() && g++ < 500) { let p = b.add(0x18).readPointer(); let k = 0;
    const blk = []; while (!p.isNull() && k++ < 3000) { blk.push(p.add(0x28).readU16()); p = p.add(4).readPointer(); }
    ops.push(blk.reverse()); b = b.readPointer(); } return ops; }
const P = PASSES;
for (const name in P) Interceptor.attach(ptr(P[name]), { onLeave() { send({fn: fname(), pass: name, ops: snap()}); } });
""".replace("PASSES", json.dumps(PASSES))
f, func = sys.argv[1], sys.argv[2]; dev = frida.get_local_device()
args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
t0 = time.time()
while not done and time.time() - t0 < 60: time.sleep(0.05)
for e in ev:
    if e["fn"] != func: continue
    last = e["ops"][-2] if len(e["ops"]) > 1 else []
    allops = [o for b in e["ops"] for o in b]
    stm = [hex(o) for o in allops if 0xd8 <= o <= 0xdf]
    print(f"{e['pass']:9s} pcodes {len(allops):4d}  stm-like {stm}  str(0xee) {allops.count(0xee)}")
