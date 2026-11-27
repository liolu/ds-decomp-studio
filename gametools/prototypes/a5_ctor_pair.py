"""Hunt agent a5 helper: vtable ctor pairs and sub-object ctor calls.

For an m2c draft that stores addresses into *arg0, this writes two C variants
and judges them with workbench.py:
  NAME.c    the m2c draft as is,
  NAME_v.c  `arg0 + N` read as byte offsets (u8 *), and when the draft has two
            `*arg0 = &X;` stores, they go through locals a then b (first declared
            local gets the higher register, which matches mwcc's load order).

Usage: python a5_ctor_pair.py PROFILE NAME [NAME ...]
"""
import json
import re
import subprocess
import sys

G = "../../studio/gametools"
PY = sys.executable
NL = chr(10)
INCLUDE = '#include "m2c.h"'


def info(name):
    out = subprocess.run([PY, G + "/workbench.py", "info", name],
                         capture_output=True, text=True).stdout
    return json.loads(out[out.find("{"):])


def judge(name, path, profile):
    out = subprocess.run([PY, G + "/workbench.py", "judge", name, path, "--profile", profile],
                         capture_output=True, text=True).stdout
    line = out.strip().splitlines()[-1] if out.strip() else "{}"
    try:
        return json.loads(line)
    except ValueError:
        return {"status": "error", "raw": line[:200]}


def variant_u8(draft):
    text = draft.replace("arg0 + ", "(u8 *)arg0 + ")
    text = text.replace(INCLUDE, INCLUDE + NL + NL + "typedef unsigned char u8;", 1)
    stores = re.findall(r"\n    \*arg0 = &(\w+);", text)
    if len(stores) == 2:
        a, b = stores
        text = text.replace("    *arg0 = &%s;" % a, "    a = &%s;" % a, 1)
        text = text.replace("    *arg0 = &%s;" % b,
                            "    b = &%s;" % b + NL + "    *arg0 = a;" + NL + "    *arg0 = b;", 1)
        text = re.sub(r"(\{\n)(    a = &)", lambda m: m.group(1) + "    void *a;" + NL
                      + "    void *b;" + NL + NL + m.group(2), text, count=1)
    return text


def main():
    profile = sys.argv[1]
    for name in sys.argv[2:]:
        draft = info(name).get("draft") or ""
        raw = "build/hunt/r3/a5/%s.c" % name
        with open(raw, "w", encoding="ascii", errors="replace") as f:
            f.write(draft)
        res = judge(name, raw, profile)
        if res.get("diffs") == 0:
            print(name, "MATCH draft", profile)
            continue
        v = variant_u8(draft)
        vpath = "build/hunt/r3/a5/%s_v.c" % name
        with open(vpath, "w", encoding="ascii", errors="replace") as f:
            f.write(v)
        res2 = judge(name, vpath, profile)
        print(name, res.get("status"), res.get("diffs"), "variant:", res2.get("status"), res2.get("diffs"))


if __name__ == "__main__":
    main()
