"""a20 helper: hoist simple local declarations (4-space indented `type name;`) to the top of the
function body, drop exact duplicates, and declare saved_reg_* names as s32 locals.

Usage: python a20_hoist.py FILE.c  (rewrites FILE.c in place, ASCII only).
"""
import re
import sys

path = sys.argv[1]
src = open(path, encoding="ascii").read()
m = re.search(r"\n[^\n;]*\bfunc_\w+\s*\([^;{]*\)\s*\{\n", src)
if not m:
    sys.exit("no function body found")
head, body = src[: m.end()], src[m.end():]
decl = re.compile(r"^    ((?:M2C_UNK|s8|u8|s16|u16|s32|u32|void \*)\s*\*?)\s*(\w+);$", re.M)
found = decl.findall(body)
body = decl.sub("", body)
seen = set()
decls = []
for typ, name in found:
    if name in seen:
        continue
    seen.add(name)
    decls.append("    %s %s;\n" % (typ.strip(), name))
for name in sorted(set(re.findall(r"\bsaved_reg_\w+", body))):
    if name not in seen:
        seen.add(name)
        decls.append("    s32 %s;\n" % name)
open(path, "w", encoding="ascii").write(head + "".join(decls) + body)
print("hoisted:", len(decls))
