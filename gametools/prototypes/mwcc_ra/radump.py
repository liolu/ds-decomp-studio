"""radump.py - dump mwccarm 2.0/sp1p5's register-allocation decisions (Frida instrumentation of the real compiler).

    python radump.py FILE.c [--func NAME] [-- extra mwcc flags]

Spawns tools/mwccarm/2.0/sp1p5/mwccarm.exe (unmodified) with the game flags, hooks the coloring pass
(FUN_00513930 select, FUN_00513590 simplify) and prints, for every coloring attempt of every function:
  node index, colour chosen (rN), flags, spill cost, degree, neighbours, and the order nodes came off the stack.
See NOTES.md for the structures.
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path
import frida

ROOT = Path(__file__).resolve().parent.parent
MWCC = ROOT / "tools/mwccarm/2.0/sp1p5/mwccarm.exe"
FLAGS = ("-O4,p -enum int -char signed -str noreuse -proc arm946e -gccext,on -fp soft -inline noauto "
         "-Cpp_exceptions off -RTTI off -interworking -w off -sym on -gccinc -nolink -msgstyle gcc -lang=c").split()

JS = r"""
const SELECT = ptr('0x00513930');
const CLASS = ptr('0x00646699'), NODES = ptr('0x0063ba40'), FIRST = ptr('0x0063a2bc'), END = ptr('0x0063d00c');
const CURFN = ptr('0x0063a79c');
function fname() {
  try { const f = CURFN.readPointer(); if (f.isNull()) return '?'; return f.add(8).readPointer().add(10).readCString(); }
  catch (e) { return '?'; }
}
function neighbours(base, n, idx) {
  const out = []; let e = n.add(0x32).readPointer(); let guard = 0;
  while (!e.isNull() && guard++ < 10000) {
    let s = e.add(0xe).readS16();
    const other = (s <= idx) ? e.add(0xc).readS16() : s;
    out.push(other);
    e = (idx < e.add(0xe).readS16()) ? e.add(4).readPointer() : e.add(8).readPointer();
  }
  return out;
}
Interceptor.attach(SELECT, {
  onEnter(args) {
    this.stack = []; let p = args[0]; let g = 0;
    const base = NODES.readPointer();
    while (!p.isNull() && g++ < 100000) { this.stack.push(p.sub(base).toInt32() / 0x36); p = p.readPointer(); }
  },
  onLeave(ret) {
    const cls = CLASS.readS8(); const base = NODES.readPointer();
    const first = FIRST.add(cls * 4).readU32(), end = END.add(cls * 4).readU32();
    const nodes = [];
    for (let i = 0; i < end; i++) {
      const n = base.add(i * 0x36);
      nodes.push({i: i, color: n.add(0x2a).readS16(), flags: n.add(0x2c).readU16(), cost: n.add(0xc).readS32(),
                  nb: (i >= first) ? neighbours(base, n, i) : []});
    }
    send({fn: fname(), ok: ret.toInt32(), first: first, end: end, stack: this.stack, nodes: nodes});
  }
});
"""


FORCE_JS = r"""
Interceptor.attach(SELECT, { onLeave(ret) {
  if (ret.toInt32() !== 1 || fname() !== FORCE_FN) return;
  const n = NODES.readPointer().add(FORCE_IDX * 0x36);
  n.add(0x2a).writeS16(FORCE_REG);
}});
"""


def run(cfile, extra, include, force=None, out="radump_tmp.o"):
    args = [str(MWCC)] + FLAGS + ["-i", include] + extra + ["-c", Path(cfile).name, "-o", out]
    dev = frida.get_local_device()
    pid = dev.spawn(args, cwd=str(Path(cfile).resolve().parent))
    sess = dev.attach(pid)
    events = []
    js = JS
    if force:
        fn, idx, reg = force
        js += f"const FORCE_FN = {json.dumps(fn)}, FORCE_IDX = {idx}, FORCE_REG = {reg};\n" + FORCE_JS
    script = sess.create_script(js)
    script.on("message", lambda m, d: events.append(m["payload"]) if m["type"] == "send" else print(m, file=sys.stderr))
    script.load()
    done = []
    dev.on("process-crashed", lambda *a: done.append(1))
    sess.on("detached", lambda *a: done.append(1))
    dev.resume(pid)
    import time
    t0 = time.time()
    while not done and time.time() - t0 < 60:
        time.sleep(0.05)
    return events


REGN = ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "sl", "fp", "ip", "sp", "lr", "pc"]


def disasm(obj, func):
    """Instruction texts of `func` in the object (no addresses)."""
    out = subprocess.run(["arm-none-eabi-objdump", "-d", "--no-show-raw-insn", obj], capture_output=True, text=True).stdout
    lines, on = [], False
    for l in out.split("\n"):
        if l.endswith(f"<{func}>:"):
            on = True; continue
        if on:
            if not l.strip() or l.endswith(">:"):
                if lines: break
                continue
            parts = l.split("\t")
            if len(parts) >= 2:
                lines.append("\t".join(p.strip() for p in parts[1:]).split(";")[0].strip())
    return lines


def vmap(cfile, func, extra, include):
    """Annotate the listing of `func` with the virtual register(s) behind each instruction's operands."""
    base_ev = [e for e in run(cfile, extra, include) if e["fn"] == func]
    final = [e for e in base_ev if e["ok"] == 1][-1]
    d = str(Path(cfile).resolve().parent / "radump_tmp.o")
    base = disasm(d, func)
    used = {r for l in base for r in REGN if f"{r}" in l.replace(",", " ").split()}
    marker = next((k for k in (12, 11, 10, 9, 8, 7, 6, 5, 4) if REGN[k] not in " ".join(base)), 12)
    notes = [[] for _ in base]
    for n in final["nodes"][final["first"]:]:
        if n["color"] < 0:
            continue
        run(cfile, extra, include, force=(func, n["i"], marker), out="radump_force.o")
        alt = disasm(str(Path(cfile).resolve().parent / "radump_force.o"), func)
        if len(alt) != len(base):
            continue
        mk = REGN[marker]
        orig = REGN[n["color"]] if 0 <= n["color"] < 16 else None
        for k, (x, y) in enumerate(zip(base, alt)):
            # strict: the line differs only by the marker standing where the vreg's own register was
            if x != y and orig and re.sub(rf"\b{mk}\b", orig, y) == x:
                notes[k].append(f"v{n['i']}")
    return final, base, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--func"); ap.add_argument("--json")
    ap.add_argument("--map", action="store_true", help="annotate the listing of --func with virtual registers")
    ap.add_argument("--include", default=str(ROOT / "projets/tom-and-jerry-tales/include"))
    a, extra = ap.parse_known_args()
    extra = [x for x in extra if x != "--"]
    if a.map:
        final, base, notes = vmap(a.file, a.func, extra, a.include)
        for k, l in enumerate(base):
            print(f"{k:4d}  {l:40s} {' '.join(notes[k])}")
        print("\nnodes (stack pops first -> last):", " ".join(f"v{i}" for i in final["stack"]))
        for n in final["nodes"][final["first"]:]:
            c = f"r{n['color']}" if n["color"] >= 0 else "--"
            print(f"   v{n['i']:<4d} {c:4s} flags {n['flags']:04x} cost {n['cost']:6d} nb {sorted(n['nb'])}")
        return
    ev = run(a.file, extra, a.include)
    if a.func:
        ev = [e for e in ev if e["fn"] == a.func]
    if a.json:
        Path(a.json).write_text(json.dumps(ev))
    for e in ev:
        print(f"== {e['fn']} attempt ok={e['ok']} vregs {e['first']}..{e['end'] - 1}")
        order = list(e["stack"])
        print("   select order:", " ".join(map(str, order)))
        for n in e["nodes"][e["first"]:]:
            c = f"r{n['color']}" if n["color"] >= 0 else "--"
            print(f"   v{n['i']:<4d} {c:4s} flags {n['flags']:04x} cost {n['cost']:6d} nb {sorted(n['nb'])}")


if __name__ == "__main__":
    main()
