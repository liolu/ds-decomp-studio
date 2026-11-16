"""asmsig.py - compiler fingerprints read in the TARGET assembly: which profile to try first, before any draft.

    from asmsig import profiles_from_asm
    profiles_from_asm(asm_lines)         # -> ["1.2/b56", ...] (most likely first), [] when no fingerprint

    cd projets/<game>
    python ../../studio/gametools/prototypes/asmsig.py scan        # how many unmatched functions carry each fingerprint
    python ../../studio/gametools/prototypes/asmsig.py eval        # on MATCHED functions: fingerprint vs real profile

Each fingerprint is code that one compiler version emits and the others never do. Found 2026-11-16 on Spyro
(blockmap.py class `short`, 83 functions one instruction shorter than the target):

  b56-addr   `add rX, rY, #off` then `ldr/str rZ, [rX]` (the field address kept in a register for a read-modify-
             write), where 1.2/sp2p3 and every 2.0 fold the offset (`ldr rZ, [rY, #off]` ... `str rZ, [rY, #off]`).
             Every C form gives the folded code on sp2p3/2.0 (M2C_FIELD, struct field, array, pointer temp); only
             1.2/b56 gives the target (func_02047150: `x->f38 |= 2`). Spyro had never used b56, so the profile prior
             (neighbours' profiles) could not propose it.

Add a fingerprint: a function taking the listing (objdump text, one instruction per line) and returning a count;
put it in SIGS with the profiles it points to, then `eval` on a game where those profiles matched.
"""
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def _b56_addr(t: list[str]) -> int:
    n = 0
    for a, b in zip(t, t[1:]):
        m = re.match(r"\s*add\s+(r\d+|ip|lr), (r\d+|ip|lr|sp), #\d+", a)
        # objdump writes `[r1]`, dsd `[r1, #0x0]`
        if m and m.group(2) != "sp" and re.match(rf"\s*(ldr|str)\w*\s+\w+, \[{m.group(1)}(, #0x0|, #0)?\]\s*$",
                                                 b.split("@")[0].split(";")[0]):
            n += 1
    return n


SIGS = [
    ("b56-addr", _b56_addr, ["1.2/b56"]),
]


def fingerprints(lines: list[str]) -> dict[str, int]:
    return {k: f(lines) for k, f, _ in SIGS if f(lines)}


def profiles_from_asm(lines: list[str]) -> list[str]:
    out = []
    for k, f, profs in SIGS:
        if f(lines):
            out += [p for p in profs if p not in out]
    return out


def _listing(name: str) -> list[str]:
    import auto_match as am
    asm = am.function_asm(name) or ""
    out = []
    for l in asm.splitlines():
        l = l.split(";")[0].strip()
        if not l or l.endswith(":") or l.startswith((".", "glabel", "arm_func", "thumb_func")):
            continue
        out.append(l)
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    import gzip
    d = json.load(gzip.open("progress/report.json.gz"))
    profs = {}
    for p in Path("config").glob("*/compilers.txt"):
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip() and not l.startswith("#"):
                path, _, prof = l.strip().partition(" ")
                profs[Path(path).stem] = prof.strip().split(" ")[0]
    c, per = collections.Counter(), collections.defaultdict(collections.Counter)
    for u in d["units"]:
        for f in u.get("functions", []):
            done = f.get("fuzzy_match_percent", 0) >= 100
            if (cmd == "scan") == done:
                continue
            fp = fingerprints(_listing(f["name"]))
            for k in fp:
                c[k] += 1
                if done:
                    per[k][profs.get(u["name"].rsplit("/", 1)[-1], "default")] += 1
    print(dict(c))
    for k, v in per.items():
        print(k, dict(v))


if __name__ == "__main__":
    main()
