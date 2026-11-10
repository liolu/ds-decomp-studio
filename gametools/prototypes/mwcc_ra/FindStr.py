# Ghidra script: functions referencing strings that contain env MWCC_STR (| separated); decompile them to out/str_<addr>.c
# @category mwcc
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import os
OUT = os.environ.get("MWCC_OUT", "out")
keys = os.environ["MWCC_STR"].split("|")
dec = DecompInterface(); dec.openProgram(currentProgram)
refm = currentProgram.getReferenceManager(); fm = currentProgram.getFunctionManager()
for d in currentProgram.getListing().getDefinedData(True):
    v = d.getValue()
    try:
        s = v.encode("ascii", "ignore") if isinstance(v, unicode) else str(v)
    except Exception:
        continue
    if not any(k in s for k in keys): continue
    for r in refm.getReferencesTo(d.getAddress()):
        f = fm.getFunctionContaining(r.getFromAddress())
        if f is None: continue
        print("REF %s from %s %s : %s" % (d.getAddress(), r.getFromAddress(), f.getName(), s[:60]))
        res = dec.decompileFunction(f, 180, ConsoleTaskMonitor())
        if res and res.getDecompiledFunction():
            open(os.path.join(OUT, "str_%s.c" % f.getEntryPoint()), "w").write(res.getDecompiledFunction().getC().encode("ascii", "replace"))
