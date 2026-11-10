# Ghidra script (Jython): decompile every function that references the allocator/scheduler source-file strings.
# @category mwcc
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import os
OUT = os.environ.get("MWCC_OUT", "out")
KEYS = ["Registers.c", "xSpill.c", "LiveRegisters.c", "SchedulerARM9.c", "Scheduler.c", "RegisterInfo.c",
        "Coloring", "InterferenceGraph", "PCode.c", "PCodeInfo.c", "ValueNumbering", "Spill"]
listing = currentProgram.getListing()
refm = currentProgram.getReferenceManager()
fm = currentProgram.getFunctionManager()
dec = DecompInterface(); dec.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
seen = {}
idx = open(os.path.join(OUT, "index.txt"), "w")
for d in listing.getDefinedData(True):
    v = d.getValue()
    if not isinstance(v, unicode) and not isinstance(v, str):
        continue
    try:
        s = v.encode("ascii", "ignore") if isinstance(v, unicode) else str(v)
    except Exception:
        continue
    if not any(k in s for k in KEYS):
        continue
    for r in refm.getReferencesTo(d.getAddress()):
        f = fm.getFunctionContaining(r.getFromAddress())
        if f is None: continue
        seen.setdefault(f.getEntryPoint().toString(), (f, set()))[1].add(s)
for ep, (f, ss) in sorted(seen.items()):
    idx.write("%s %s %d %s\n" % (ep, f.getName(), f.getBody().getNumAddresses(), " | ".join(sorted(ss))))
    res = dec.decompileFunction(f, 120, mon)
    if res and res.getDecompiledFunction():
        open(os.path.join(OUT, "%s.c" % ep), "w").write(res.getDecompiledFunction().getC().encode("ascii", "replace"))
idx.close()
print("functions: %d" % len(seen))
