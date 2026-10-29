"""Cross-references of a symbol, from the relocations dsd already knows (config/<version>/arm9/**/relocs.txt).

    python ../../studio/gametools/xref.py data_02107860       # who reads/writes it, and at which offsets
    python ../../studio/gametools/xref.py func_0204b070       # callers, and the tables that point to it
    python ../../studio/gametools/xref.py 0x020fcfb8 --table  # pointer slots inside a data symbol (vtables...)
    python ../../studio/gametools/xref.py data_02107860 --siblings  # functions sharing the most data with its users

Functions are marked [x] when a source in delinks.txt owns them (matched), [ ] otherwise.
Addresses of overlays overlap: a name or address that exists in several modules lists them all (use --module).
"""
import argparse
import bisect
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project import ARM9  # noqa: E402

SYM = re.compile(r"^(\S+) kind:(\w+)(?:\(([^)]*)\))? addr:0x([0-9a-fA-F]+)")
REL = re.compile(r"^from:0x([0-9a-fA-F]+) kind:(\S+) to:0x([0-9a-fA-F]+) module:(\S+)")
RANGE = re.compile(r"\.text\s+start:0x([0-9a-fA-F]+) end:0x([0-9a-fA-F]+)")


def module_name(d: Path) -> str:
    if d == ARM9:
        return "main"
    if d.parent.name == "overlays":
        return f"overlay({int(d.name[2:])})"
    return d.name  # itcm, dtcm


def target_modules(field: str) -> list[str]:
    m = re.fullmatch(r"overlays?\(([\d,\s]+)\)", field)
    return [f"overlay({int(n)})" for n in m.group(1).split(",")] if m else [field]


class Module:
    def __init__(self, name: str, d: Path):
        self.name, self.dir = name, d
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
        end = a + size if size else (self.syms[i + 1][0] if i + 1 < len(self.syms) else a + 1)
        return (name, kind, addr - a) if addr < end else None

    def is_matched(self, addr: int) -> bool:
        i = bisect.bisect_right(self.matched, (addr, 1 << 32)) - 1
        return i >= 0 and self.matched[i][0] <= addr < self.matched[i][1]


def load():
    mods = {}
    for f in sorted(ARM9.rglob("symbols.txt")):
        mods[module_name(f.parent)] = Module(module_name(f.parent), f.parent)
    rels = []  # (from_module, from_addr, kind, to_module, to_addr)
    for f in sorted(ARM9.rglob("relocs.txt")):
        src = module_name(f.parent)
        for line in f.read_text(encoding="utf-8").splitlines():
            m = REL.match(line)
            if m:
                for tm in target_modules(m.group(4)):
                    rels.append((src, int(m.group(1), 16), m.group(2), tm, int(m.group(3), 16)))
    return mods, rels


def find(mods, key: str, module: str | None):
    """[(module, addr, name, kind, size)] for a symbol name or an address."""
    out = []
    addr = int(key, 16) if re.fullmatch(r"(0x)?[0-9a-fA-F]{7,8}", key) else None
    for mod in mods.values():
        if module and mod.name != module:
            continue
        for a, name, kind, size in mod.syms:
            if name == key or a == addr:
                out.append((mod.name, a, name, kind, size))
    return out


def describe(mods, mod: str, addr: int) -> str:
    m = mods.get(mod)
    hit = m.containing(addr) if m else None
    if not hit:
        return f"0x{addr:08x} ({mod})"
    name, kind, off = hit
    mark = ("[x] " if m.is_matched(addr) else "[ ] ") if kind == "function" else ""
    where = f"{name}+0x{off:x}" if off else name
    return f"{mark}{where}" + ("" if mod == "main" else f" ({mod})")


def refs_to(rels, mod: str, start: int, end: int):
    return [r for r in rels if r[3] == mod and start <= r[4] < end]


def symbol_end(mods, mod: str, addr: int, size) -> int:
    if size:
        return addr + size
    m = mods[mod]
    i = bisect.bisect_right(m.addrs, addr)
    return m.addrs[i] if i < len(m.addrs) else addr + 4


def show(mods, rels, hit):
    mod, addr, name, kind, size = hit
    end = symbol_end(mods, mod, addr, size)
    print(f"{name}  {kind}  0x{addr:08x}-0x{end:08x}  ({mod})")
    by_user = defaultdict(set)
    for fm, fa, k, _, ta in refs_to(rels, mod, addr, end):
        by_user[describe(mods, fm, fa).split("+")[0]].add((k, ta - addr))
    if not by_user:
        print("  no references")
    for user in sorted(by_user):
        kinds = sorted({k for k, _ in by_user[user]})
        offs = sorted({o for _, o in by_user[user]})
        offs_s = ", ".join(f"+0x{o:x}" for o in offs) if any(offs) else ""
        print(f"  {user:<44} {'/'.join(kinds):<12} {offs_s}")


def table(mods, rels, hit):
    """Pointer slots inside a data symbol, in address order (relocations whose source lies in it)."""
    mod, addr, name, kind, size = hit
    end = symbol_end(mods, mod, addr, size)
    slots = sorted((fa, tm, ta) for fm, fa, k, tm, ta in rels if fm == mod and addr <= fa < end)
    print(f"{name}  0x{addr:08x}-0x{end:08x}  {len(slots)} pointer slot(s)")
    for fa, tm, ta in slots:
        print(f"  +0x{fa - addr:<5x} -> {describe(mods, tm, ta)}")


def siblings(mods, rels, hit, top: int):
    """Functions that share the most data symbols with the users of this symbol: the same module of the game."""
    mod, addr, name, kind, size = hit
    end = symbol_end(mods, mod, addr, size)
    users = {describe(mods, fm, fa).split("+")[0] for fm, fa, k, _, _ in refs_to(rels, mod, addr, end)}
    data_of = defaultdict(set)  # function -> data symbols it loads
    for fm, fa, k, tm, ta in rels:
        if k != "load" or tm not in mods:
            continue
        d = mods[tm].containing(ta)
        if d and d[1] != "function":
            data_of[describe(mods, fm, fa).split("+")[0]].add((tm, d[0]))
    shared = set().union(*(data_of[u] for u in users)) if users else set()
    score = Counter({f: len(ds & shared) for f, ds in data_of.items() if f not in users and ds & shared})
    print(f"users of {name}: {len(users)}; functions sharing their data (shared symbols):")
    for f, n in score.most_common(top):
        print(f"  {f:<44} {n}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="symbol name or address (0x...)")
    ap.add_argument("--module", help="main, itcm, dtcm or overlay(N)")
    ap.add_argument("--table", action="store_true", help="list the pointer slots inside a data symbol")
    ap.add_argument("--siblings", action="store_true", help="functions sharing the most data with its users")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    mods, rels = load()
    hits = find(mods, args.symbol, args.module)
    if not hits:
        raise SystemExit(f"{args.symbol}: no such symbol")
    for i, hit in enumerate(hits):
        if i:
            print()
        if args.table:
            table(mods, rels, hit)
        elif args.siblings:
            siblings(mods, rels, hit, args.top)
        else:
            show(mods, rels, hit)


if __name__ == "__main__":
    main()
