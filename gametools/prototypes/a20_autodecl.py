"""a20 helper: declare undeclared m2c stack locals (spXX) at the top of the function body.

Usage: python a20_autodecl.py FILE.c  (rewrites FILE.c in place).
Only inserts `s32 spXX;` lines for identifiers matching sp[0-9A-Fa-f]+ used but not declared.
"""
import re
import sys

path = sys.argv[1]
src = open(path, encoding="ascii").read()
m = re.search(r"\n[^\n;]*\bfunc_\w+\s*\([^;{]*\)\s*\{\n", src)
if not m:
    sys.exit("no function body found")
body = src[m.end():]
used = set(re.findall(r"\bsp[0-9A-Fa-f]+\b", body))
declared = set(re.findall(r"\bs32\s+(sp[0-9A-Fa-f]+)\b", src)) | set(re.findall(r"\bu32\s+(sp[0-9A-Fa-f]+)\b", src))
missing = sorted(used - declared)
if missing:
    decl = "".join("    s32 %s;\n" % n for n in missing)
    src = src[: m.end()] + decl + src[m.end():]
    open(path, "w", encoding="ascii").write(src)
print("declared:", " ".join(missing))
