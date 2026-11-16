"""methodtable.py - one line per function of ONE game: `name = method / parameter`, matched or not.

    cd projets/<game>
    python ../../studio/gametools/prototypes/methodtable.py OUT.md [OUT.tsv]

Matched: the tool that produced the file (git commit + the results.json of blockmap/errfix/retarg/ldstfix runs) and
the compiler profile (compilers.txt). Unmatched: the blockmap class (the parameter that blocks it) and the tool for it.
"""
import collections
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blockmap  # noqa: E402

LABEL = {
    "m:auto": "auto_match (m2c + profils du prior)",
    "m:clone": "clone_match (copie d'un jumeau deja matche)",
    "m:hand": "a la main / agent",
    "m:donor": "donor_match (decomp externe)",
    "m:errfix": "errfix (reparation des erreurs de compilation)",
    "m:b56": "vieux compilateur 1.2/b56 (signature asmsig)",
    "m:sinit": "__sinit_ en .init + pointeur .ctor",
    "m:retarg": "retarg (return arg0 : constructeur)",
    "m:ldstfix": "ldstfix (largeur/signe des acces)",
}


def results(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    out_md = Path(sys.argv[1])
    out_tsv = Path(sys.argv[2]) if len(sys.argv) > 2 else out_md.with_suffix(".tsv")
    bm = results("build/blockmap/blockmap.json")
    profs = blockmap.file_profiles()
    meth = blockmap.matched_methods()
    tool_of = {}
    for n, r in results("build/blockmap/submit/results.json").items():
        w = r.get("why", "")
        tool_of[n] = "m:sinit" if n.startswith("__sinit_") else "m:errfix" if w == "errfix" else "m:b56" if "b56" in (r.get("profile") or "") else "m:errfix"
    for d, k in (("build/retarg", "m:retarg"), ("build/ldstfix", "m:ldstfix")):
        for n, r in results(f"{d}/results.json").items():
            if r.get("match"):
                tool_of.setdefault(n, k)
    d = json.load(gzip.open("progress/report.json.gz"))
    rows = []
    for u in d["units"]:
        for f in u.get("functions", []):
            n, size = f["name"], int(f["size"])
            if f.get("fuzzy_match_percent", 0) >= 100:
                stem = u["name"].rsplit("/", 1)[-1]
                m = tool_of.get(n) or "m:" + meth.get(stem, "?")
                rows.append((n, size, "matche", m, profs.get(stem, blockmap.default_profile())))
            else:
                r = bm.get(n, {})
                c = r.get("class", "non classe")
                if n in tool_of:
                    rows.append((n, size, "matche", tool_of[n], r.get("profile") or ""))
                else:
                    rows.append((n, size, "bloque", c, r.get("profile") or ""))
    rows.sort(key=lambda x: (x[2], x[3], x[1]))
    with open(out_tsv, "w", encoding="utf-8") as f:
        f.write("fonction\ttaille\tetat\tmethode_ou_parametre\tprofil\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")
    cnt, byt = collections.Counter(), collections.Counter()
    for n, s, st, m, p in rows:
        cnt[(st, m)] += 1
        byt[(st, m)] += s
    lines = ["| etat | methode / parametre | fonctions | octets | outil |", "|---|---|---:|---:|---|"]
    for (st, m), v in sorted(cnt.items(), key=lambda x: (x[0][0] != "matche", -x[1])):
        tool = LABEL.get(m) or blockmap.TOOLS.get(m) or ("errfix.py" if m.startswith("err:") else "")
        lines.append(f"| {st} | `{m}` | {v} | {byt[(st, m)]} | {tool} |")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} functions -> {out_tsv}, summary -> {out_md}")


if __name__ == "__main__":
    main()
