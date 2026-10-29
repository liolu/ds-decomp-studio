"""Cross-references of a symbol, from the relocations dsd already knows (config/<version>/arm9/**/relocs.txt).

    python ../../studio/gametools/xref.py data_02107860       # who reads/writes it, and at which offsets
    python ../../studio/gametools/xref.py func_0204b070       # callers, and the tables that point to it
    python ../../studio/gametools/xref.py 0x020fcfb8 --table  # pointer slots inside a data symbol (vtables...)
    python ../../studio/gametools/xref.py data_02107860 --siblings  # functions sharing the most data with its users

Functions are marked [x] when a source in delinks.txt owns them (matched), [ ] otherwise.
Addresses of overlays overlap: a name or address that exists in several modules lists them all (use --module).
Studio's "Data" tab uses the same functions (Index + query).
"""
import argparse
import bisect
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SYM = re.compile(r"^(\S+) kind:(\w+)(?:\(([^)]*)\))? addr:0x([0-9a-fA-F]+)")
REL = re.compile(r"^from:0x([0-9a-fA-F]+) kind:(\S+) to:0x([0-9a-fA-F]+) module:(\S+)")
RANGE = re.compile(r"\.text\s+start:0x([0-9a-fA-F]+) end:0x([0-9a-fA-F]+)")


def target_modules(field: str) -> list[str]:
    m = re.fullmatch(r"overlays?\(([\d,\s]+)\)", field)
    return [f"overlay({int(n)})" for n in m.group(1).split(",")] if m else [field]


class Module:
    def __init__(self, name: str, d: Path):
        self.name = name
        self.syms = []  # (addr, name, kind, size)
        for line in (d / "symbols.txt").read_text(encoding="utf-8").splitlines():
            m = SYM.match(line)
            if not m or m.group(2) == "label":
                continue
            size = re.search(r"size=0x([0-9a-fA-F]+)", m.group(3) or "")
            self.syms.append((int(m.group(4), 16), m.group(1), m.group(2), int(size.group(1), 16) if size else None))
        self.syms.sort()
        self.addrs = [s[0] for s in self.syms]
        self.matched = []  # sorted (start, end) of .text owned by a source
        if (d / "delinks.txt").exists():
            self.matched = sorted((int(a, 16), int(b, 16)) for a, b in RANGE.findall((d / "delinks.txt").read_text()))

    def containing(self, addr: int):
        """The symbol holding addr: (name, kind, offset), or None past the end of a sized symbol."""
        i = bisect.bisect_right(self.addrs, addr) - 1
        if i < 0:
            return None
        a, name, kind, size = self.syms[i]
        return (name, kind, addr - a) if addr < self.end(i) else None

    def end(self, i: int) -> int:
        a, _, _, size = self.syms[i]
        return a + size if size else (self.syms[i + 1][0] if i + 1 < len(self.syms) else a + 4)

    def is_matched(self, addr: int) -> bool:
        i = bisect.bisect_right(self.matched, (addr, 1 << 32)) - 1
        return i >= 0 and self.matched[i][0] <= addr < self.matched[i][1]


class Index:
    """Symbols, matched ranges and relocations of every module of one game (arm9 = config/<version>/arm9)."""

    def __init__(self, arm9: Path):
        def name(d: Path) -> str:
            if d == arm9:
                return "main"
            return f"overlay({int(d.name[2:])})" if d.parent.name == "overlays" else d.name  # itcm, dtcm
        self.files = sorted(arm9.rglob("symbols.txt")) + sorted(arm9.rglob("relocs.txt")) + sorted(arm9.rglob("delinks.txt"))
        self.mods = {name(f.parent): Module(name(f.parent), f.parent) for f in sorted(arm9.rglob("symbols.txt"))}
        self.rels = []  # (from_module, from_addr, kind, to_module, to_addr)
        for f in sorted(arm9.rglob("relocs.txt")):
            src = name(f.parent)
            for line in f.read_text(encoding="utf-8").splitlines():
                m = REL.match(line)
                if m:
                    for tm in target_modules(m.group(4)):
                        self.rels.append((src, int(m.group(1), 16), m.group(2), tm, int(m.group(3), 16)))

    def stamp(self) -> float:
        return max((f.stat().st_mtime for f in self.files if f.exists()), default=0)

    def find(self, key: str, module: str = "") -> list[dict]:
        key = key.strip()
        addr = int(key, 16) if re.fullmatch(r"(0x)?[0-9a-fA-F]{7,8}", key) else None
        out = []
        for mod in self.mods.values():
            if module and mod.name != module:
                continue
            for i, (a, nm, kind, size) in enumerate(mod.syms):
                if nm == key or (addr is not None and a <= addr < mod.end(i)):
                    out.append({"module": mod.name, "addr": a, "end": mod.end(i), "name": nm, "kind": kind})
        return out

    def ref(self, mod: str, addr: int) -> dict:
        """What sits at addr: the containing symbol (+offset), and whether it is a matched function."""
        m = self.mods.get(mod)
        hit = m.containing(addr) if m else None
        if not hit:
            return {"name": f"0x{addr:08x}", "module": mod, "kind": "", "off": 0, "matched": None}
        nm, kind, off = hit
        return {"name": nm, "module": mod, "kind": kind, "off": off,
                "matched": m.is_matched(addr) if kind == "function" else None}

    def users(self, sym: dict) -> list[dict]:
        """Who points into the symbol: one row per user symbol, with the reloc kinds and the offsets used."""
        rows = {}
        for fm, fa, k, tm, ta in self.rels:
            if tm == sym["module"] and sym["addr"] <= ta < sym["end"]:
                r = self.ref(fm, fa)
                row = rows.setdefault((r["module"], r["name"]), {**r, "kinds": set(), "offs": set()})
                row["kinds"].add(k)
                row["offs"].add(ta - sym["addr"])
        return [{**r, "kinds": sorted(r["kinds"]), "offs": sorted(r["offs"]), "off": 0}
                for r in sorted(rows.values(), key=lambda r: (r["module"] != "main", r["name"]))]

    def table(self, sym: dict) -> list[dict]:
        """Pointer slots inside a data symbol, in address order (relocations whose source lies in it)."""
        return [{"slot": fa - sym["addr"], **self.ref(tm, ta)}
                for fm, fa, k, tm, ta in sorted(self.rels, key=lambda r: r[1])
                if fm == sym["module"] and sym["addr"] <= fa < sym["end"]]

    def siblings(self, sym: dict, top: int = 25) -> list[dict]:
        """Functions sharing the most data symbols with the users of this symbol: the same module of the game."""
        users = {(u["module"], u["name"]) for u in self.users(sym)}
        data_of, info = defaultdict(set), {}
        for fm, fa, k, tm, ta in self.rels:
            if k != "load" or tm not in self.mods:
                continue
            d = self.mods[tm].containing(ta)
            if d and d[1] != "function":
                r = self.ref(fm, fa)
                data_of[(r["module"], r["name"])].add((tm, d[0]))
                info[(r["module"], r["name"])] = r
        shared = set().union(*(data_of[u] for u in users if u in data_of))
        score = Counter({f: len(ds & shared) for f, ds in data_of.items() if f not in users and ds & shared})
        return [{**info[f], "off": 0, "shared": n} for f, n in score.most_common(top)]


def query(ix: Index, key: str, mode: str = "users", module: str = "", top: int = 25) -> dict:
    hits = ix.find(key, module)
    out = []
    for s in hits[:20]:
        rows = ix.table(s) if mode == "table" else ix.siblings(s, top) if mode == "siblings" else ix.users(s)
        out.append({**s, "rows": rows})
    return {"query": key, "mode": mode, "symbols": out}


def label(r: dict) -> str:
    mark = "" if r.get("matched") is None else "[x] " if r["matched"] else "[ ] "
    where = f"{r['name']}+0x{r['off']:x}" if r.get("off") else r["name"]
    return mark + where + ("" if r["module"] == "main" else f" ({r['module']})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="symbol name or address (0x...)")
    ap.add_argument("--module", default="", help="main, itcm, dtcm or overlay(N)")
    ap.add_argument("--table", action="store_true", help="list the pointer slots inside a data symbol")
    ap.add_argument("--siblings", action="store_true", help="functions sharing the most data with its users")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project import ARM9
    mode = "table" if args.table else "siblings" if args.siblings else "users"
    res = query(Index(ARM9), args.symbol, mode, args.module, args.top)
    if args.json:
        return print(json.dumps(res, indent=1))
    if not res["symbols"]:
        raise SystemExit(f"{args.symbol}: no such symbol")
    for i, s in enumerate(res["symbols"]):
        print(("\n" if i else "") + f"{s['name']}  {s['kind']}  0x{s['addr']:08x}-0x{s['end']:08x}  ({s['module']})")
        if not s["rows"]:
            print("  nothing")
        for r in s["rows"]:
            if mode == "table":
                print(f"  +0x{r['slot']:<5x} -> {label(r)}")
            elif mode == "siblings":
                print(f"  {label(r):<44} {r['shared']} shared")
            else:
                offs = ", ".join(f"+0x{o:x}" for o in r["offs"]) if any(r["offs"]) else ""
                print(f"  {label(r):<44} {'/'.join(r['kinds']):<14} {offs}")


if __name__ == "__main__":
    main()
