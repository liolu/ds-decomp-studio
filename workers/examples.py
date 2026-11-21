#!/usr/bin/env python3
"""Examples for the AI agents: matched functions of all our games (assembly -> the C that compiles to it exactly),
found by how close their instructions are to the function being worked on.

    python workers/examples.py build                 # index every project (decomp ds/examples.sqlite)
    python workers/examples.py query <game> <function> [-n 3]

Index: for each ARM function of the main module that is matched (a `complete` .text range of delinks.txt) and not
too big, its disassembly (one objdump run per game), its mnemonics, and its C (the whole file when it defines only
this function, else its declarations + this function). Similarity: Jaccard of the instruction 3-grams (mnemonics
only: registers and constants vary), sizes within a factor 2.
"""
import argparse
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

STUDIO = Path(__file__).resolve().parent.parent


def _load_donorlib():
    """gametools/donorlib.py loaded by its path: putting gametools/ on sys.path would make a game's tools
    (auto_match, project...) resolve to the Studio's copies in the agents that import this module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("studio_donorlib", STUDIO / "gametools" / "donorlib.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


donorlib = _load_donorlib()  # only C splitting (top_level_items, function_name)


def _load_workspace():
    """gametools/workspace.py (where the games are: projets/ and All-nds-decomp-games/games/<L>/), by its path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("studio_workspace", STUDIO / "gametools" / "workspace.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


workspace = _load_workspace()

WORKSPACE = STUDIO.parent
DB = WORKSPACE / "examples.sqlite"
PROJETS = WORKSPACE / "projets"
MAX_SIZE = 512       # bytes: bigger functions make long prompts and are rarely close to anything
MAX_C = 3000         # characters of C
FUNC_RE = re.compile(r"^(\S+) kind:function\(arm,size=0x([0-9a-f]+)\).*?addr:0x([0-9a-f]+)", re.M)
DELINK_RE = re.compile(r"^(src/\S+):\n((?:[ \t]+\S.*\n?)+)", re.M)
TEXT_RE = re.compile(r"\.text\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+)")
MARKER = "/* compiler: "


def disassemble(binary: Path, base: int = 0x02000000) -> dict[int, str]:
    """{address: 'mnemonic operands'} of a whole ARM binary (one objdump call)."""
    objdump = shutil.which("arm-none-eabi-objdump")
    if objdump is None:
        raise SystemExit("arm-none-eabi-objdump not found (source env.sh)")
    r = subprocess.run([objdump, "-D", "-b", "binary", "-marm", f"--adjust-vma={base}", str(binary)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().endswith(":"):
            try:
                out[int(parts[0].strip()[:-1], 16)] = " ".join(parts[2:]).split(";")[0].split("@")[0].strip()
            except ValueError:
                pass
    return out


def mnemonics(lines: list[str]) -> list[str]:
    return [l.split(None, 1)[0] if l.strip() else "?" for l in lines]


def grams(mn: list[str], n: int = 3) -> set[str]:
    return {" ".join(mn[i:i + n]) for i in range(max(1, len(mn) - n + 1))}


def function_c(text: str, name: str) -> str | None:
    if text.startswith(MARKER):
        text = text.split("\n", 1)[1]
    items = donorlib.top_level_items(text)
    defs = [donorlib.function_name(it) for it in items if it.rstrip().endswith("}")]
    if name not in defs:
        return None
    if len([d for d in defs if d]) == 1:
        return text.strip() + "\n"
    keep = [it for it in items if not it.rstrip().endswith("}") or donorlib.function_name(it) == name]
    return "\n\n".join(keep).strip() + "\n"


def clean_c(c: str) -> str:
    """Without what only matters to the repository: clang-format switches, attribution comments, blank runs."""
    c = re.sub(r"/\*[^*]*?(?:reused by|license:)[\s\S]*?\*/\n?", "", c)
    c = re.sub(r"^\s*// clang-format (?:on|off)\s*\n", "", c, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", c).strip() + "\n"


def index_game(con, root: Path, log=print) -> int:
    vers = sorted(p.name for p in (root / "config").iterdir() if (p / "arm9" / "symbols.txt").exists())
    if not vers:
        return 0
    v = vers[0]
    cfg = root / "config" / v / "arm9"
    binary = root / "extract" / v / "arm9" / "arm9.bin"
    if not binary.exists():
        return 0
    files = []
    head, _, rest = (cfg / "delinks.txt").read_text(encoding="utf-8", errors="replace").partition("\n\n")
    for path, body in DELINK_RE.findall(rest):
        if "complete" in body:
            files += [(int(a, 16), int(b, 16), path) for a, b in TEXT_RE.findall(body)]
    if not files:
        return 0
    files.sort()
    funcs = [(n, int(a, 16), int(s, 16)) for n, s, a in FUNC_RE.findall((cfg / "symbols.txt").read_text(encoding="utf-8", errors="replace"))]
    comp = {}
    ct = root / "config" / v / "compilers.txt"
    if ct.exists():
        for line in ct.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                p, _, prof = line.partition(" ")
                comp[p] = prof.strip()
    dis = disassemble(binary)
    import bisect
    starts = [f[0] for f in files]
    rows, texts = [], {}
    for name, addr, size in funcs:
        if size > MAX_SIZE or size < 8:
            continue
        i = bisect.bisect_right(starts, addr) - 1
        if i < 0 or not files[i][0] <= addr < files[i][1]:
            continue
        path = files[i][2]
        if path not in texts:
            try:
                texts[path] = (root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[path] = ""
        c = function_c(texts[path], name) if texts[path] else None
        if not c or re.search(r"\b(asm|__asm)\b", c):
            continue  # assembly-language functions teach nothing about C
        c = clean_c(c)
        if len(c) > MAX_C:
            continue
        lines = [dis.get(a, "") for a in range(addr, addr + size, 4)]
        rows.append((root.name, name, size, " ".join(mnemonics(lines)), "\n".join(lines), c, comp.get(path, "")))
    con.execute("DELETE FROM ex WHERE game=?", (root.name,))
    con.executemany("INSERT INTO ex VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    log(f"{root.name}: {len(rows)} examples")
    return len(rows)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS ex(game, name, size, mnem, asm, c, profile)")
    return con


class Examples:
    """In-memory index for queries (loaded once by an agent run)."""

    def __init__(self):
        con = sqlite3.connect(DB)
        self.rows = con.execute("SELECT game, name, size, mnem, asm, c FROM ex").fetchall()
        con.close()
        self.grams = [grams(r[3].split()) for r in self.rows]

    def similar(self, mn: list[str], size: int, game: str = "", name: str = "", n: int = 3,
                min_score: float = 0.25) -> list[tuple[float, tuple]]:
        g = grams(mn)
        out, seen_c = [], set()
        scored = []
        for row, rg in zip(self.rows, self.grams):
            if not size / 2 <= row[2] <= size * 2 or (row[0] == game and row[1] == name):
                continue
            inter = len(g & rg)
            if inter:
                scored.append((inter / len(g | rg), row))
        scored.sort(key=lambda x: -x[0])
        for s, row in scored:
            if s < min_score:
                break
            key = re.sub(r"0x[0-9a-f]{6,}", "X", row[4])
            if key in seen_c:
                continue  # the same code in several games: one is enough
            seen_c.add(key)
            out.append((s, row))
            if len(out) >= n:
                break
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "query"])
    ap.add_argument("game", nargs="?")
    ap.add_argument("function", nargs="?")
    ap.add_argument("-n", type=int, default=3)
    a = ap.parse_args()
    if a.action == "build":
        con = connect()
        total = 0
        for d in workspace.game_dirs():
            if (d / "config").is_dir():
                try:
                    total += index_game(con, d)
                except Exception as e:  # one broken project must not stop the others
                    print(f"{d.name}: skipped ({e})")
        print(f"{total} examples -> {DB}")
        return
    root = workspace.find_game(a.game) or PROJETS / a.game
    v = sorted(p.name for p in (root / "config").iterdir() if (p / "arm9" / "symbols.txt").exists())[0]
    m = re.search(rf"^{re.escape(a.function)} kind:function\(arm,size=0x([0-9a-f]+)\).*?addr:0x([0-9a-f]+)",
                  (root / "config" / v / "arm9" / "symbols.txt").read_text(encoding="utf-8"), re.M)
    size, addr = int(m.group(1), 16), int(m.group(2), 16)
    data = (root / "extract" / v / "arm9" / "arm9.bin").read_bytes()[addr - 0x02000000: addr - 0x02000000 + size]
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "f.bin").write_bytes(data)
        lines = list(disassemble(Path(t) / "f.bin", addr).values())
    for s, row in Examples().similar(mnemonics(lines), size, a.game, a.function, a.n):
        print(f"--- {s:.2f} {row[0]}:{row[1]} ({row[2]} bytes)\n{row[4]}\n{row[5]}")


if __name__ == "__main__":
    main()
