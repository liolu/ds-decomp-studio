"""schedtrace.py FILE.c FUNC [--pass N] : trace mwcc 2.0/sp1p5's list scheduler (Frida), cycle by cycle.

For every call of the ready-list picker (FUN_004ff590) in function FUNC it prints the candidates and the one taken,
with the fields the picker compares (see NOTES.md "Scheduler"):
  ready  = preds 0 and earliest <= cycle      urgent = deadline <= cycle
  unl    = successors this one would unblock (FUN_004ff560, more wins)
  h      = critical-path height (+0x18, more wins)       kind = FUN_004febf0 class (+0x12, smaller wins)
Ties keep the list order (= program order). Pass 1 = before register allocation (vregs), pass 2 = after.
"""
import argparse, sys, time
from pathlib import Path
import frida
sys.path.insert(0, str(Path(__file__).parent))
import radump

JS = r"""
const PICK = ptr('0x004ff590'), SCHED = ptr('0x004ff750'), CURFN = ptr('0x0063a79c');
function fname() { try { return CURFN.readPointer().add(8).readPointer().add(10).readCString(); } catch (e) { return '?'; } }
function pc(p) {
  const n = p.add(0x2c).readS16(); const ops = [];
  for (let k = 0; k < n && k < 10; k++) { const o = p.add(0x2e + k * 0xe);
    const kind = o.readU8(), fl = o.add(2).readU16();
    ops.push(kind === 0 ? ((fl & 2) ? 'v' + o.add(4).readS16() + '=' : 'v' + o.add(4).readS16())
                        : (kind === 1 ? 'r' + o.add(4).readS16() : 'k' + o.add(6).readS32())); }
  return '0x' + p.add(0x28).readU16().toString(16) + ' ' + ops.join(' ');
}
function unl(node) { let c = 0; let s = node.add(8).readPointer();
  while (!s.isNull()) { if (s.add(4).readPointer().add(0x1a).readS16() === 1) c++; s = s.readPointer(); } return c; }
let passn = {};
Interceptor.attach(SCHED, { onEnter() { const f = fname(); passn[f] = (passn[f] || 0) + 1; this.f = f; } });
Interceptor.attach(PICK, {
  onEnter(args) {
    this.cyc = args[1].toInt32() & 0xffff; this.f = fname();
    const c = []; let n = args[0];
    while (!n.isNull()) {
      const su = []; let e = n.add(8).readPointer();
      while (!e.isNull()) { su.push([e.add(4).readPointer().toString(), e.add(8).readU16()]); e = e.readPointer(); }
      c.push({id: n.toString(), su: su, pc: pc(n.add(0xc).readPointer()), pred: n.add(0x1a).readS16(),
              early: n.add(0x14).readU16(), dl: n.add(0x16).readU16(), h: n.add(0x18).readU16(),
              kind: n.add(0x12).readU16(), unl: unl(n)});
      n = n.readPointer();
    }
    this.c = c;
  },
  onLeave(ret) {
    send({fn: this.f, pass: passn[this.f] || 0, cyc: this.cyc, cand: this.c, pick: ret.isNull() ? null : ret.toString()});
  }
});
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("func"); ap.add_argument("--pass", dest="pas", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="also list candidates that are not ready")
    ap.add_argument("--dag", action="store_true", help="print the dependency graph of the first pick of each pass")
    a = ap.parse_args()
    dev = frida.get_local_device()
    args = [str(radump.MWCC)] + radump.FLAGS + ["-i", str(radump.ROOT / "projets/tom-and-jerry-tales/include"),
                                                 "-c", Path(a.file).name, "-o", "radump_tmp.o"]
    pid = dev.spawn(args, cwd=str(Path(a.file).resolve().parent)); s = dev.attach(pid); ev = []
    sc = s.create_script(JS); sc.on("message", lambda m, d: ev.append(m["payload"]) if m["type"] == "send" else print(m)); sc.load()
    done = []; s.on("detached", lambda *x: done.append(1)); dev.resume(pid)
    t0 = time.time()
    while not done and time.time() - t0 < 60:
        time.sleep(0.05)
    shown = set()
    for e in ev:
        if e["fn"] != a.func or (a.pas and e["pass"] != a.pas):
            continue
        if a.dag and e["pass"] not in shown:
            shown.add(e["pass"])
            names = {c["id"]: f"n{k}" for k, c in enumerate(e["cand"])}
            print(f"pass {e['pass']} DAG (succ:latency):")
            for c in e["cand"]:
                print(f"  {names[c['id']]:4s} h {c['h']:2d} {c['pc'][:60]:60s} -> " + " ".join(f"{names.get(x, '?')}:{l}" for x, l in c["su"]))
        if e["pick"] is None:
            continue
        print(f"pass {e['pass']} cycle {e['cyc']}:")
        for c in e["cand"]:
            ready = c["pred"] == 0 and c["early"] <= e["cyc"]
            if not ready and not a.all:
                continue
            mark = "->" if c["id"] == e["pick"] else "  "
            urg = "U" if c["dl"] <= e["cyc"] else " "
            print(f"  {mark}{urg} unl {c['unl']} h {c['h']:2d} kind {c['kind']} early {c['early']:2d} pred {c['pred']}  {c['pc']}")


if __name__ == "__main__":
    main()
