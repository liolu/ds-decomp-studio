# Ghidra script: references to the addresses in env MWCC_ADDRS; prints each (from addr, function, ref type)
# @category mwcc
import os
refm = currentProgram.getReferenceManager(); fm = currentProgram.getFunctionManager(); af = currentProgram.getAddressFactory()
for a in os.environ["MWCC_ADDRS"].split(","):
    for r in refm.getReferencesTo(af.getAddress(a)):
        f = fm.getFunctionContaining(r.getFromAddress())
        print("XREF %s <- %s %s %s" % (a, r.getFromAddress(), f.getName() if f else "?", r.getReferenceType()))
