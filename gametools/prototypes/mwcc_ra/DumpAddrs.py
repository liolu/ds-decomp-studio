# Ghidra script: decompile the functions at the addresses in env MWCC_ADDRS (comma separated), into MWCC_OUT/<addr>.c
# @category mwcc
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import os
OUT = os.environ.get("MWCC_OUT", "out")
dec = DecompInterface(); dec.openProgram(currentProgram)
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
for a in os.environ["MWCC_ADDRS"].split(","):
    f = fm.getFunctionAt(af.getAddress(a))
    if f is None:
        f = fm.getFunctionContaining(af.getAddress(a))
    if f is None:
        print("no function at " + a); continue
    res = dec.decompileFunction(f, 180, ConsoleTaskMonitor())
    c = res.getDecompiledFunction().getC() if res and res.getDecompiledFunction() else "// decompile failed"
    open(os.path.join(OUT, "%s.c" % a.lower()), "w").write(c.encode("ascii", "replace"))
    print("ok " + a)
