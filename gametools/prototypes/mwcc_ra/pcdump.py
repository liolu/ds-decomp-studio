"""pcdump.py FILE.c FUNC : dump mwcc's pcode (per block, operands with vreg numbers) at register-allocation entry."""
import sys, json, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent))
import radump
JS = r"""
const DRIVER = ptr('0x00513ca0'), BLOCKS = ptr('0x0063a828'), CURFN = ptr('0x0063a79c');
function fname() { try { return CURFN.readPointer().add(8).readPointer().add(10).readCString(); } catch (e) { return '?'; } }
Interceptor.attach(DRIVER, { onEnter(args) {
  const out = []; let b = BLOCKS.readPointer(); let gb = 0;
  while (!b.isNull() && gb++ < 2000) {
    const blk = {idx: b.add(0x1c).readS32(), pc: []};
    let p = b.add(0x18).readPointer(); let gp = 0;
    while (!p.isNull() && gp++ < 5000) {
      const n = p.add(0x2c).readS16(); const ops = [];
      for (let k = 0; k < n && k < 12; k++) { const o = p.add(0x2e + k * 0xe);
        ops.push([o.readU8(), o.add(1).readS8(), o.add(2).readU16(), o.add(4).readS16(), o.add(6).readS32(), o.add(10).readS32()]); }
      blk.pc.push({raw: Array.from(new Uint8Array(p.readByteArray(0x2c))), ops: ops});
      p = p.add(4).readPointer();
    }
    out.push(blk); b = b.readPointer();
  }
  send({fn: fname(), blocks: out});
}});
"""
def main():
    f, func = sys.argv[1], sys.argv[2]
    dev = frida.get_local_device()
    args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"), "-c", Path(f).name, "-o", "radump_tmp.o"]
    pid = dev.spawn(args, cwd=str(Path(f).resolve().parent)); s = dev.attach(pid); ev = []
    sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
    done = []; s.on("detached", lambda *a: done.append(1)); dev.resume(pid)
    t0 = time.time()
    while not done and time.time() - t0 < 60: time.sleep(0.05)
    ev = [e for e in ev if e["fn"] == func]
    Path(f + ".pcode.json").write_text(json.dumps(ev))
    e = ev[0]
    for b in e["blocks"]:
        print(f"block {b['idx']}")
        for p in b["pc"]:
            raw = p["raw"]
            ops = " ".join(f"{'v' if o[0]==0 else 'k'+str(o[0])}{o[3] if o[0]==0 else o[4]}{'=' if o[2]&2 else ''}" for o in p["ops"])
            print(f"   {bytes(raw[8:0x2c]).hex()}  {ops}")
main()
