"""revdecl: reverse the order of the first block of plain local declarations in the first function of a C file.

usage: python revdecl.py IN.c OUT.c
What: finds the first function body, takes the contiguous block of 4-space-indented declarations
(`type name;`, no initializer) and writes them in reverse order. Mwccarm gives the higher register to the
first-declared local, so reversing often changes the register allocation (r30: GetType_around2 25 -> 12 diffs,
func_ov123_020cb7dc 40 -> 31, func_0201eb28 45 -> 37; but it made ov123_0208ed38, ov121, ov114_020e3318 worse).
Origin: round r30 hand matching (agent r30a4), build/hunt/r30/revdecl.py.
"""
import re, sys
src = open(sys.argv[1]).read().split("\n")
decl = re.compile(r"^\s{4}[A-Za-z_][\w\s\*]*\s[\*]?\w+(\[\w*\])?\s*;\s*$")
for i, l in enumerate(src):
    if re.match(r"^[A-Za-z_].*\)\s*\{\s*$", l):
        j = i + 1
        block = []
        while j < len(src) and decl.match(src[j]):
            block.append(j); j += 1
        if len(block) >= 2:
            vals = [src[k] for k in block]
            for k, v in zip(block, reversed(vals)):
                src[k] = v
        break
open(sys.argv[2], "w").write("\n".join(src))
print("reversed", len(block) if 'block' in dir() else 0)
