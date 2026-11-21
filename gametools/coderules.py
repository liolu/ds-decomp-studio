#!/usr/bin/env python3
"""Code rules checker: is a byte-identical function also a match under the code rules (CODE-RULES.md)?

    python tools/coderules.py                  # every matched function of the game: summary + build/coderules/report.json
    python tools/coderules.py --pending        # the MATCH-PENDING functions and the rules that hold them
    python tools/coderules.py --advisory       # also the findings that do not block a match (naming, banners...)
    python tools/coderules.py FILE.c [...]     # only these files (works outside a project)
    python tools/coderules.py --strict         # exit code 1 when a [match] rule fires

Identical bytes alone are not a match. A function counts only when its bytes match AND no [match] rule fires on it:

    R1   one declaration per type        the same type defined in two files with different bodies (a draft's file-local
                                         helper, `typedef struct D {...} D;` in many files, is advisory)
    R2   one declaration per global      `extern` of a global outside a header; one global declared with two types
    R4   typed members, no offsets       M2C_FIELD, `*(T *)((char *)p + K)`, virtual calls through `*(u8 **)p + K`
    R13  real vtables                    virtuals named pad/dummy (slot counts need vtable data: not checked here)
    R17  no fake code                    volatile outside hardware registers, the tools' own probes (hunt_pad...),
                                         unused locals, empty if/else, bare `;`, do {} while (0), `x = x`, `+ 0`, `* 1`,
                                         padding members
    R18  assembly is not source          an `asm` body, unless the function is ORIGINAL-ASM

Byte-identical but failing = MATCH-PENDING: reported, not counted. ORIGINAL-ASM (the game's config/asm_allowed.txt, or
an `// ASM: <public decomp that proves it>` comment at the function) is listed apart and counted neither way.
The matched set is objdiff's (build/<version>/report.json, what `match.py verify` prints) when it is up to date, else
the functions of the `complete` files of delinks.txt. Each file's scan is cached in build/coderules/scan-cache.json
(size + mtime): a run after a small change rereads only the changed files.

Each check is deliberately narrow, so genuine code passes: `volatile` on a 0x04xxxxxx register, on the shared work
area the ARM7 writes (0x027FFxxx, 0x02FFFxxx on DSi) or with a `// volatile: <evidence>` note, a reserved field
with a `// reserved: <SDK or file format name>` note, an unused local or an odd statement the original really had
with a `// R36: <what the bytes show>` note, empty loop bodies, `case X: ;`.

Advisory findings never block a match: a type declared both `class` and `struct` (R1: mwccarm's mangled names do
not carry the class key), placeholder names (R7: func_02001234, data_..., arg0, temp_r4, M2C_UNK), prototypes
outside a header (R25), functions without a header comment (R33), `#if 0` (R37), assignments inside
conditions (R35), byte-pointer arithmetic that is not dereferenced (R4), `goto` (R14), `!!x`.

Only the standard library, and no project needed at import: workbench.py, match.py and the workers load this file.
"""
import argparse
import bisect
import hashlib
import json
import os
import re
import sys
from pathlib import Path

MATCH_RULES = ("R1", "R2", "R4", "R13", "R17", "R18")
OK, PENDING, ORIGINAL_ASM = "ok", "MATCH-PENDING", "ORIGINAL-ASM"

# ---------------------------------------------------------------- project profile (AGENTS.md, "Code rules profile")
# names a disassembler, dsd or m2c made up: open naming work (R7), never a blocked match
PLACEHOLDER = re.compile(
    r"\b(?:func_(?:ov\d+_)?[0-9a-f]{8}|data_(?:ov\d+_)?[0-9a-f]{8}|lbl_[0-9a-f]{8}|FUN_\w+|DAT_\w+|sub_[0-9A-Fa-f]+"
    r"|unk_?[0-9A-Fa-f]+|field_0x\w+|local_\w+|param_\d+|arg\d+|temp_\w+|var_\w+|phi_\w+|sp[0-9A-F]{1,4}|M2C_UNK"
    r"|[a-z]Var\d+|[a-z]+Stack_?\w+|(?:temp|ptr|result|var|v|t)\d+)\b")
ADDRESS_LIKE = re.compile(r"\b(?![0-9])[A-Za-z_]*?_?(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{6,8}\b")
# what the studio's own search tools write to steer the compiler (hunt.py: pad-param, call-temp, cmp-hoist)
PROBE = re.compile(r"\b(?:hunt_\w+|arg_pad|probe_\w+)\b")
# volatile is genuine on the DS I/O registers (0x04xxxxxx) and on the main-memory areas the other processor writes:
# the shared system work area 0x027FFxxx (0x02FFFxxx on DSi), e.g. the card ROM ID the SDK polls at 0x027FFE60
HW_ADDRESS = re.compile(r"\b0x0?(?:4[0-9A-Fa-f]{6}|2[7Ff][Ff]{2}[0-9A-Fa-f]{3})\b|\bREG_\w+\b")
# names m2c drafts give a struct only the one file uses: the same name in many files is many unrelated types (R1)
LOCAL_TYPE_NAME = re.compile(r"[A-Za-z]{1,2}\d*|Obj|Ctx|Self|Tmp|Temp|Local\w*|Anon\w*|Unk\d*")
PAD_MEMBER = re.compile(r"\b(_?pad(?:ding)?_?(?:[0-9][0-9A-Fa-f]*)?)\s*(?:\[[^\]]*\]\s*)*(?::\s*\d+\s*)?;")
ASM_EVIDENCE = re.compile(r"//\s*ASM:|ORIGINAL-ASM")

BYTE_T = r"(?:(?:un)?signed\s+)?(?:char|u8|s8|BYTE|byte)"
CONST = r"(?:0x[0-9A-Fa-f]+|\d+)"
OFFSET_MACRO = re.compile(r"\bM2C_FIELD\s*\(")
BYTE_PLUS = r"\(\s*\(\s*" + BYTE_T + r"\s*\*\s*\)\s*\(?\s*[\w.\->\[\]]+\s*\)?\s*[+-]\s*" + CONST + r"\s*\)"  # ((u8 *)p + K)
OFFSET_DEREF = re.compile(r"\*\s*\(\s*[A-Za-z_][\w \t]*\*+\s*\)\s*" + BYTE_PLUS)
OFFSET_ARROW = re.compile(r"\(\s*\(\s*[A-Za-z_][\w \t]*\*+\s*\)\s*" + BYTE_PLUS + r"\s*\)\s*->")
OFFSET_VCALL = re.compile(r"\(\s*\*\s*\(\s*[\w \t*]+\(\s*\*+\s*\)\s*\([^()]*\)\s*\)\s*\(\s*\*\s*\(\s*(?:" + BYTE_T +
                          r"|void)\s*\*\s*\*\s*\)\s*\w+\s*\+\s*" + CONST + r"\s*\)\s*\)")
OFFSET_THIS = re.compile(r"\(\s*(?:" + BYTE_T + r"|void|int|s32|u32)\s*\*?\s*\)\s*this\s*[+-]")
BYTE_ARITH = re.compile(r"\(\s*" + BYTE_T + r"\s*\*\s*\)\s*\(?\s*[\w.\->\[\]]+\s*\)?\s*[+-]\s*" + CONST + r"\b")
INT_DEREF = re.compile(r"\*\s*\(\s*[A-Za-z_][\w \t]*\*+\s*\)\s*\(\s*[A-Za-z_]\w*\s*[+-]\s*" + CONST + r"\s*\)")

SELF_ASSIGN = re.compile(r"(?<![\w.>\]=!<+\-*/%&|^])((?:\*\s*)?[A-Za-z_]\w*(?:(?:->|\.)\w+|\[[^\]\n]*\])*)\s*=\s*\1\s*;")
PLUS_ZERO = re.compile(r"[\w)\]]\s*\+\s*0\b(?![.\w])")
TIMES_ONE = re.compile(r"[\w)\]]\s*\*\s*1\b(?![.\w])")
DO_WHILE_0 = re.compile(r"\}\s*while\s*\(\s*0\s*\)\s*;")
EMPTY_STMT, EMPTY_BLOCK = re.compile(r"\s*;"), re.compile(r"\s*\{\s*\}")
EMPTY_ELSE = re.compile(r"\belse\s*(?:\{\s*\}|;)")
NOT_NOT = re.compile(r"!!\s*[\w(]")
ASSIGN_IN_COND = re.compile(r"\b(?:if|while)\s*\([^;{}]*?[^=!<>+\-*/%&|^]=[^=]")
NOT_A_TYPE = {"return", "goto", "break", "continue", "case", "default", "else", "do", "sizeof", "typedef", "extern", "if",
              "while", "for", "switch", "delete", "new", "throw", "using", "asm"}
LOCAL_DECL = re.compile(r"^[ \t]+((?:(?:static|const|register|volatile|unsigned|signed|struct|union|enum)\s+)*[A-Za-z_]\w*)"
                        r"(?:\s*\*+\s*|\s+)([^;()=\n]+?)\s*(=[^;]*)?;", re.M)

_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_DIRECTIVE = re.compile(r"^[ \t]*#(?:[^\n\\]|\\.|\\\r?\n)*", re.M)
_BLANK = re.compile(r"[^\n]")
_BRACE_OR_SEMI = re.compile(r"[{};]")
_LINKAGE = re.compile(r'^extern\s*"\s*"\s*(?=[^\s{])')  # `extern "C" s32 x;` (string blanked) -> `extern s32 x;`


_BRACE, _PAREN_OR_SEMI = re.compile(r"[{}]"), re.compile(r"[()\[\];]")


def _prev_index(text: str, i: int) -> int:
    """Index of the last non-blank character before text[i] (-1 at the start)."""
    j = i - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    return j


def _prev_char(text: str, i: int) -> str:
    j = _prev_index(text, i)
    return text[j] if j >= 0 else ""


def _code_view(text: str) -> str:
    """The text with comments, string contents and preprocessor lines blanked: same length, same lines."""
    def tok(m):
        s = m.group(0)
        if s[0] == '"':
            return '"' + " " * (len(s) - 2) + '"'
        return _BLANK.sub(" ", s)
    return _DIRECTIVE.sub(lambda m: _BLANK.sub(" ", m.group(0)), _TOKEN.sub(tok, text))


class _Lines:
    def __init__(self, text: str):
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer(r"\n", text)]

    def no(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset)

    def line(self, offset: int) -> str:
        i = self.no(offset) - 1
        end = self.starts[i + 1] if i + 1 < len(self.starts) else len(self.text)
        return self.text[self.starts[i]:end]

    def above(self, offset: int, n: int = 12) -> str:
        """The lines just above `offset` (the comment block of a function)."""
        i = self.no(offset) - 1
        return self.text[self.starts[max(0, i - n)]:self.starts[i]]


def _close(code: str, i: int, open_c: str = "(", close_c: str = ")") -> int:
    """Index just after the bracket that closes the one at code[i]."""
    depth = 0
    for j in range(i, len(code)):
        c = code[j]
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j + 1
    return len(code)


def _functions(code: str) -> tuple[list[dict], list[tuple[int, int]]]:
    """Function definitions at file scope ({name, start, body, end, asm}) and the file-scope statements between
    them (start, end). `extern "C" {` and `namespace X {` are looked through."""
    funcs, stmts, stack, cur, start = [], [], [], None, 0
    blocks = 0  # open "B" entries of the stack
    for mt in _BRACE_OR_SEMI.finditer(code):
        i, c = mt.start(), mt.group(0)
        if c == "{":
            if blocks == 0:
                head = code[start:i]
                h = head.strip()
                if re.search(r'(?:extern\s*"\s*"|\bnamespace\b[\w \t]*)$', h):
                    stack.append("T")
                    start = i + 1
                    continue
                m = re.search(r"\)\s*(?:const\s*)?$", h)
                if m:
                    close = head.rfind(")")
                    depth, open_ = 0, -1
                    for j in range(close, -1, -1):
                        depth += {")": 1, "(": -1}.get(head[j], 0)
                        if depth == 0:
                            open_ = j
                            break
                    nm = re.search(r"([A-Za-z_~][\w:~]*)\s*$", head[:open_]) if open_ > 0 else None
                    if nm and nm.group(1) not in NOT_A_TYPE:
                        lead = len(head) - len(head.lstrip())
                        cur = {"name": nm.group(1), "start": start + lead, "body": i,
                               "asm": bool(re.search(r"\b(?:__)?asm\b", head))}
            stack.append("B")
            blocks += 1
        elif c == "}":
            if stack:
                kind = stack.pop()
                if kind == "T":
                    start = i + 1
                    continue
                blocks -= 1
            if blocks == 0:
                if cur:
                    cur["end"] = i + 1
                    funcs.append(cur)
                    cur, start = None, i + 1
        elif c == ";" and blocks == 0:
            stmts.append((start, i + 1))
            start = i + 1
    return funcs, stmts


def _finding(rule: str, line: int, what: str, function: str | None = None, uses: tuple = ()) -> dict:
    return {"rule": rule, "tier": "match" if rule in MATCH_RULES else "advisory", "line": line, "function": function,
            "what": what, "uses": list(uses)}


def _advice(rule: str, line: int, what: str, function: str | None = None) -> dict:
    f = _finding(rule, line, what, function)
    f["tier"] = "advisory"
    return f


def _noted(lines: _Lines, offset: int, note: str) -> bool:
    """`// note: ...` (or R36) on the line of `offset` or the line above: the evidence the rule asks for."""
    here = lines.line(offset) + lines.above(offset, 1)
    return bool(re.search(r"(?://|/\*)[^\n]*\b" + note, here))


def _fake_code(code: str, lines: _Lines, f: dict) -> list[dict]:
    """R17 inside one function (code = the code view of the file)."""
    out, name = [], f["name"]
    span, s0 = code[f["start"]:f["end"]], f["start"]
    body, b0 = code[f["body"]:f["end"]], f["body"]
    seen = set()

    def add(off: int, what: str) -> None:
        key = (lines.no(off), what)
        if key not in seen and not _noted(lines, off, "R36"):
            seen.add(key)
            out.append(_finding("R17", key[0], what, name))

    for m in re.finditer(r"\bvolatile\b", span):
        off = s0 + m.start()
        stmt = lines.line(off)
        if HW_ADDRESS.search(stmt) or _noted(lines, off, "volatile:"):
            continue
        where = "on a parameter" if off < f["body"] else "in the function body"
        add(off, f"volatile {where} (genuine only on hardware registers, or with a `// volatile: <evidence>` note)")
    for m in PROBE.finditer(span):
        add(s0 + m.start(), f"`{m.group(0)}`: a probe written by a search tool, not source")
    for m in LOCAL_DECL.finditer(body):
        if m.group(1).split()[-1] in NOT_A_TYPE or m.group(1).split()[0] == "static":
            continue
        if _prev_char(body, m.start()) not in (";", "{", "}"):  # the tail of a statement, not a declaration
            continue
        for d in m.group(2).split(","):
            v = re.sub(r"\[[^\]]*\]", "", d).strip(" \t*")
            if not re.fullmatch(r"[A-Za-z_]\w*", v) or v in NOT_A_TYPE:
                continue
            if len(re.findall(rf"\b{re.escape(v)}\b", body)) == 1:
                add(b0 + m.start(2), f"local `{v}` is never used")
    for m in re.finditer(r"\bif\s*\(", body):
        j = _close(body, m.end() - 1)
        if EMPTY_STMT.match(body, j):
            add(b0 + m.start(), "`if` with an empty statement")
        elif EMPTY_BLOCK.match(body, j):
            add(b0 + m.start(), "`if` with an empty block")
    for m in EMPTY_ELSE.finditer(body):
        add(b0 + m.start(), "empty `else`")
    for m in DO_WHILE_0.finditer(body):
        add(b0 + m.start(), "`do { } while (0)` outside a macro (the macro the original called is missing)")
    for m in SELF_ASSIGN.finditer(body):
        add(b0 + m.start(1), f"self-assignment `{m.group(1)} = {m.group(1)}`")
    for rx, what in ((PLUS_ZERO, "`+ 0`"), (TIMES_ONE, "`* 1`")):
        for m in rx.finditer(body):
            add(b0 + m.start() + 1, f"{what} only steers the compiler")
    # bare `;` statements (empty loop bodies, `case X: ;` and `label: ;` are allowed)
    paren, opened, block = 0, [], {}
    for mt in _BRACE.finditer(body):
        i = mt.start()
        if body[i] == "{":
            opened.append(i)
        elif opened:
            block[i] = opened.pop()
    for mt in _PAREN_OR_SEMI.finditer(body):
        i, c = mt.start(), mt.group(0)
        if c in "([":
            paren += 1
        elif c in ")]":
            paren -= 1
        elif paren == 0:
            prev_i = _prev_index(body, i)
            prev = body[prev_i] if prev_i >= 0 else ""
            bare = prev in (";", "{")
            if prev == "}":  # `};` ends an initializer or a type; after a block it is an empty statement
                k = _prev_index(body, block.get(prev_i, 0))
                bare = (k >= 0 and body[k] in "){;}") or bool(re.search(r"\b(?:else|do)$", body[max(0, k - 7):k + 1]))
            if bare:
                add(b0 + i, "bare `;` statement")
    return out


def _offsets(code: str, lines: _Lines, f: dict) -> list[dict]:
    """R4 inside one function."""
    out, name = [], f["name"]
    span, s0 = code[f["start"]:f["end"]], f["start"]
    seen, blocked = set(), set()

    def add(rx, what, advisory=False):
        for m in rx.finditer(span):
            ln = lines.no(s0 + m.start())
            if (ln, what) in seen or ln in blocked:  # one line, one finding: the blocking one
                continue
            seen.add((ln, what))
            if not advisory:
                blocked.add(ln)
            out.append((_advice if advisory else _finding)("R4", ln, what, name))

    add(OFFSET_MACRO, "M2C_FIELD: a member read through a fixed offset (declare the struct and use the member)")
    add(OFFSET_DEREF, "a constant offset on a byte-pointer cast, dereferenced: this is a struct member")
    add(OFFSET_ARROW, "a constant offset on a byte-pointer cast, dereferenced: this is a struct member")
    add(OFFSET_VCALL, "a virtual call through a vtable offset: declare the class and its virtuals (R13)")
    add(OFFSET_THIS, "offset arithmetic on `this`")
    add(BYTE_ARITH, "byte-pointer arithmetic with a constant: a member, unless the data has no fixed struct", True)
    add(INT_DEREF, "dereference of `pointer + constant` through a cast: is the pointer typed to dodge the real type?", True)
    return out


def _types(code: str, stmts: list[tuple[int, int]]) -> tuple[dict, dict]:
    """Type definitions at file scope {name: normalized body} and forward declarations {name: class|struct}."""
    defs, forwards = {}, {}
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    for a, b in stmts:
        s = code[a:b].strip()
        m = re.match(r"(?:typedef\s+)?(struct|union|enum|class)\s*(\w*)\s*(?::[^{]*)?\{", s)
        if m:
            close = _close(s, m.end() - 1, "{", "}")
            body = m.group(1) + " " + norm(s[m.end() - 1:close])
            names = [m.group(2)] if m.group(2) else []
            if s.startswith("typedef"):
                names += re.findall(r"\b([A-Za-z_]\w*)\b(?=\s*(?:,|;|\[))", s[close:])
            for n in names:
                defs[n] = body
            continue
        m = re.match(r"(class|struct)\s+(\w+)\s*;$", s)
        if m:
            forwards[m.group(2)] = m.group(1)
            continue
        m = re.match(r"typedef\s+(?!struct\b|union\b|enum\b|class\b)([^;{}()]+?)\b([A-Za-z_]\w*)\s*;$", s)
        if m:
            defs[m.group(2)] = "typedef " + norm(m.group(1))
    return defs, forwards


def _pad_members(code: str, lines: _Lines) -> list[dict]:
    out = []
    for m in re.finditer(r"\b(?:struct|union|class)\b[^;{}()=]*\{", code):
        end = _close(code, m.end() - 1, "{", "}")
        body = code[m.end():end]
        tail = re.match(r"\s*(\w*)", code[end:])
        names = tuple(n for n in (re.sub(r".*\b(?:struct|union|class)\s*(\w*).*", r"\1", m.group(0), flags=re.S),
                                  tail.group(1) if tail else "") if n)
        for p in PAD_MEMBER.finditer(body):
            off = m.end() + p.start()
            if _noted(lines, off, "reserved:"):
                continue
            out.append(_finding("R17", lines.no(off), f"padding member `{p.group(1)}`: name unknown members by their "
                                "offset (unk_58); a reserved field of the SDK or file format takes a `// reserved:` note",
                                uses=names))
    return out


def _virtual_pads(code: str, lines: _Lines) -> list[dict]:
    return [_finding("R13", lines.no(m.start()), f"virtual `{m.group(1)}` pads the vtable: declare the real slot")
            for m in re.finditer(r"\bvirtual\b[^;{}()]*?\b((?:_?pad|dummy)\w*)\s*\(", code)]


def scan(text: str, path: str = "") -> dict:
    """One file on its own: its functions, type definitions, extern declarations and findings (no status yet)."""
    code, lines = _code_view(text), _Lines(text)
    header = path.lower().endswith((".h", ".hpp", ".inc"))
    funcs, stmts = _functions(code)
    defs, forwards = _types(code, stmts)
    findings, externs = [], {}
    defined = {f["name"] for f in funcs}
    for a, b in stmts:
        s = _LINKAGE.sub("extern ", code[a:b].strip())  # the linkage string is not part of the type
        ln = lines.no(a + len(code[a:b]) - len(code[a:b].lstrip()))
        proto = re.match(r"(?:extern\s+)?[\w \t*]+?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;$", s)
        fnptr = re.match(r"extern\s+([\w \t*]+?)\(\s*\*+\s*([A-Za-z_]\w*)\s*\)\s*(\([^;{}]*\))\s*;$", s)
        if fnptr:  # a function-pointer global is data
            proto = None
        if s.startswith("extern") and not proto:
            m = fnptr or re.match(r"extern\s+(.*?)\b([A-Za-z_]\w*)\s*((?:\[[^\]]*\]\s*)*);$", s, re.S)
            if m:
                externs[m.group(2)] = re.sub(r"\s+", " ", m.group(1) + m.group(3)).strip()
                if not header:
                    findings.append(_finding("R2", ln, f"`extern` of `{m.group(2)}` outside a header: declare it once "
                                             "in a shared header (include/engine.h, with `workbench.py header`)",
                                             uses=(m.group(2),)))
        elif proto and not header and not s.startswith(("typedef", "static")) and proto.group(1) not in defined:
            findings.append(_advice("R25", ln, f"prototype of `{proto.group(1)}` outside a header"))
    findings += _pad_members(code, lines) + _virtual_pads(code, lines)
    for m in re.finditer(r"^[ \t]*#[ \t]*if[ \t]+0\b", text, re.M):
        findings.append(_advice("R37", lines.no(m.start()), "`#if 0` block: a block no build compiles is not source"))
    for a, b in stmts:  # volatile on file-scope data and members
        for m in re.finditer(r"\bvolatile\b", code[a:b]):
            off = a + m.start()
            if not HW_ADDRESS.search(lines.line(off)) and not _noted(lines, off, "volatile:"):
                nm = re.findall(r"[A-Za-z_]\w*", code[off:b])
                findings.append(_finding("R17", lines.no(off), "volatile on ordinary data without a "
                                         "`// volatile: <evidence>` note", uses=tuple(nm[-1:])))
    out_funcs = []
    for f in funcs:
        f["line"] = lines.no(f["start"])
        span = code[f["start"]:f["end"]]
        own = _offsets(code, lines, f) + _fake_code(code, lines, f)
        raw = text[f["start"]:f["end"]]
        above = lines.above(f["start"])
        has_asm = f["asm"] or bool(re.search(r"\b__asm\b|\basm\s*[({]", code[f["body"]:f["end"]]))
        f["asm_evidence"] = bool(ASM_EVIDENCE.search(above + raw))
        if has_asm:
            own.append(_finding("R18", f["line"], "assembly body: verbatim, not matched (ORIGINAL-ASM needs "
                                "config/asm_allowed.txt or an `// ASM: <public decomp>` citation)", f["name"]))
        if not re.search(r"(?:\*/|//[^\n]*)\s*$", above.rstrip() + "\n" if above.strip() else ""):
            own.append(_advice("R33", f["line"], "no header comment", f["name"]))
        if re.search(r"\bgoto\b", span):
            own.append(_advice("R14", f["line"], "`goto`: only where the original's control flow needs it", f["name"]))
        for rx, what in ((NOT_NOT, "`!!x`: sometimes human, needs a look"),
                         (ASSIGN_IN_COND, "assignment inside a condition (fine for the search idioms of R35)")):
            m = rx.search(span)
            if m:
                own.append(_advice("R35", lines.no(f["start"] + m.start()), what, f["name"]))
        names = {m.group(0) for m in PLACEHOLDER.finditer(span)} | {m.group(0) for m in ADDRESS_LIKE.finditer(span)}
        f["placeholders"] = sorted(names)
        f["words"] = set(re.findall(r"[A-Za-z_]\w*", span))
        f["has_asm"] = has_asm
        findings += own
        out_funcs.append(f)
    return {"path": path, "functions": out_funcs, "findings": findings, "types": defs, "forwards": forwards,
            "externs": externs, "header": header}


def _settle(unit: dict, original_asm=frozenset()) -> dict:
    """Unit-level findings go to the functions that use what they name; every function gets its status."""
    users = {}  # word -> names of the functions that use it (one pass, not findings x functions)
    for f in unit["functions"]:
        for w in f["words"]:
            users.setdefault(w, []).append(f["name"])
    by_function = {}
    for fd in unit["findings"]:
        if "functions" not in fd:
            if fd["function"]:
                fd["functions"] = [fd["function"]]
            else:
                names = {n for w in fd["uses"] for n in users.get(w, ())}
                fd["functions"] = [f["name"] for f in unit["functions"] if f["name"] in names]
        for n in dict.fromkeys(fd["functions"]):
            by_function.setdefault(n, []).append(fd)
    result = []
    for f in unit["functions"]:
        mine = by_function.get(f["name"], [])
        rules = sorted({fd["rule"] for fd in mine if fd["tier"] == "match"}, key=lambda r: int(r[1:]))
        status = PENDING if rules else OK
        if f["has_asm"] and (f["name"] in original_asm or f["asm_evidence"]):
            status, rules = ORIGINAL_ASM, []
        result.append({"name": f["name"], "line": f["line"], "status": status, "rules": rules,
                       "placeholders": len(f["placeholders"]),
                       "blocking": [f"{fd['rule']} line {fd['line']}: {fd['what']}" for fd in mine
                                    if fd["tier"] == "match"] if status == PENDING else []})
    return {"path": unit["path"], "functions": result,
            "findings": [{k: v for k, v in fd.items() if k != "uses"} for fd in unit["findings"]]}


def check_source(text: str, path: str = "f.c", original_asm=frozenset()) -> dict:
    """One file judged alone (R1 and the two-types half of R2 need the other files: see check_files)."""
    return _settle(scan(text, path), original_asm)


def check_function(text: str, name: str, original_asm=frozenset(), limit: int = 12) -> dict:
    """What workbench.judge attaches to a byte match: {"status": ok | MATCH-PENDING | ORIGINAL-ASM, "rules": [...],
    "blocking": [the first `limit` findings], "placeholders": n}. A function the checker cannot find in the text is
    left `ok`."""
    for f in check_source(text, "f.c", original_asm)["functions"]:
        if f["name"] == name:
            r = {k: f[k] for k in ("status", "rules", "blocking", "placeholders")}
            more = len(r["blocking"]) - limit
            if more > 0:
                r["blocking"] = r["blocking"][:limit] + [f"... and {more} more"]
            return r
    return {"status": OK, "rules": [], "blocking": [], "placeholders": 0}


def check_files(files: dict[str, str], original_asm=frozenset()) -> dict[str, dict]:
    """{path: text} judged together: R1 (one type, two bodies) and R2 (one global, two types) are found across the
    files. Returns {path: settled unit}."""
    return _check_units({p: scan(t, p) for p, t in files.items()}, original_asm)


def _local_helper_type(name: str, bodies: dict, units: dict) -> bool:
    """A name m2c drafts give a struct only their own file uses (`typedef struct D {...} D;` in 180 files with 180
    bodies): unrelated types that share a placeholder name, not one type declared twice. Never when a header
    defines it; else a placeholder-like name, or a name nearly every file defines its own way."""
    files = [p for ps in bodies.values() for p in ps]
    if any(units[p]["header"] for p in files):
        return False
    return bool(LOCAL_TYPE_NAME.fullmatch(name)) or (len(files) >= 3 and 2 * len(bodies) >= len(files))


def _check_units(units: dict[str, dict], original_asm=frozenset()) -> dict[str, dict]:
    types, keywords, globals_ = {}, {}, {}
    for p, u in units.items():
        for n, body in u["types"].items():
            types.setdefault(n, {}).setdefault(body, []).append(p)
            keywords.setdefault(n, {}).setdefault(body.split()[0], []).append(p)
        for n, kw in u["forwards"].items():
            keywords.setdefault(n, {}).setdefault(kw, []).append(p)
        for n, t in u["externs"].items():
            globals_.setdefault(n, {}).setdefault(t, []).append(p)
    for n, bodies in types.items():
        if len(bodies) > 1:
            where = sorted({p for ps in bodies.values() for p in ps})
            listed = f"{', '.join(where[:3])}{'...' if len(where) > 3 else ''}"
            if _local_helper_type(n, bodies, units):
                for p in where:
                    units[p]["findings"].append(_advice(
                        "R1", 1, f"`{n}` names {len(bodies)} different file-local types ({listed}): a draft's "
                        "placeholder; name each after what it is, or share it from a header if it is one type"))
                continue
            for p in where:
                units[p]["findings"].append(_finding("R1", 1, f"type `{n}` has {len(bodies)} different definitions "
                                                     f"({listed}): declare it once in a shared header", uses=(n,)))
        else:
            ps = [p for p in next(iter(bodies.values())) if not units[p]["header"]]
            if len(ps) > 1:
                for p in ps:
                    units[p]["findings"].append(_advice("R1", 1, f"type `{n}` is defined in {len(ps)} units: one "
                                                        "declaration in a shared header"))
    for n, kws in keywords.items():
        if {"class", "struct"} <= set(kws):  # mwccarm's mangling has no class key (only MSVC's does): one spelling
            for p in sorted({p for ps in kws.values() for p in ps}):
                units[p]["findings"].append(_advice("R1", 1, f"`{n}` is declared both `class` and `struct`: pick "
                                                    "one spelling (it does not change mwccarm's mangled names)"))
    for n, ts in globals_.items():
        if len(ts) > 1:
            for p in sorted({p for ps in ts.values() for p in ps}):
                units[p]["findings"].append(_finding("R2", 1, f"global `{n}` is declared with {len(ts)} different types: "
                                                     + " / ".join(sorted(ts)), uses=(n,)))
    return {p: _settle(u, original_asm) for p, u in units.items()}


# ---------------------------------------------------------------- a whole game
FUNC_SYM = re.compile(r"^(\S+) kind:function\((?:arm|thumb),size=0x([0-9a-f]+)\) addr:0x([0-9a-f]+)", re.M)
DELINK_BLOCK = re.compile(r"^(\S+):\n((?:[ \t]+.*\n?)*)", re.M)
DELINK_SEC = re.compile(r"\.(\w+)\s+start:0x([0-9a-f]+) end:0x([0-9a-f]+)")
SOURCE_SUFFIXES = (".c", ".cpp", ".cc", ".cp", ".h", ".hpp", ".inc")
CACHE_NAME = "scan-cache.json"


def asm_allowed(root: Path) -> set[str]:
    p = root / "config" / "asm_allowed.txt"
    if not p.is_file():
        return set()
    return {l.split()[0] for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")}


def _source_files(root: Path) -> list[tuple[str, os.DirEntry]]:
    """(path relative to the game, entry) of every source file under src/ and include/, sorted."""
    out, todo = [], [(base, root / base) for base in ("src", "include")]
    while todo:
        rel, d = todo.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                todo.append((f"{rel}/{e.name}", e.path))
            elif e.name.lower().endswith(SOURCE_SUFFIXES):
                out.append((f"{rel}/{e.name}", e))
    return sorted(out, key=lambda pe: pe[0])


def _checker_version() -> str:
    """Changes whenever this file does: a cache written by another version of the checks is not reused."""
    return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()


def scan_game(root: Path, cache: bool = True) -> dict[str, dict]:
    """scan() of every source file of the game, through build/coderules/scan-cache.json: a file whose size and
    mtime did not change since the last run is not read again."""
    path = root / "build" / "coderules" / CACHE_NAME
    version, old = _checker_version(), {}
    if cache:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            old = data["files"] if data.get("version") == version else {}
        except (OSError, ValueError, KeyError, TypeError):
            old = {}
    units, new = {}, {}
    for rel, e in _source_files(root):
        st = e.stat()
        stamp = [st.st_mtime_ns, st.st_size]
        hit = old.get(rel)
        if hit and hit["stamp"] == stamp:
            u = hit["scan"]
        else:
            with open(e.path, encoding="utf-8", errors="replace") as fh:
                u = scan(fh.read(), rel)
            for f in u["functions"]:
                f["words"] = sorted(f["words"])
        new[rel] = {"stamp": stamp, "scan": u}
        units[rel] = u
    if cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": version, "files": new}, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
    # the cross-file pass adds findings and settle reads `words` as sets: hand it copies, never the cached entries
    return {rel: {**u, "findings": [dict(fd) for fd in u["findings"]],
                  "functions": [{**f, "words": set(f["words"])} for f in u["functions"]]} for rel, u in units.items()}


def _report_matched(report: dict) -> tuple[dict, list[tuple[str, str, int]]] | None:
    """From objdiff's report.json (the one `match.py verify` and `status` print): the totals, and (source path,
    name, size) of every function it finds byte-identical. None when the report has no function lists (match.py's
    config_report)."""
    units = report.get("units") or []
    if not any("functions" in u for u in units):
        return None
    m = report.get("measures", {})
    matched = []
    for u in units:
        path = u.get("metadata", {}).get("source_path") or u.get("name", "")
        for f in u.get("functions", []):
            if float(f.get("fuzzy_match_percent", 0) or 0) >= 100.0:
                matched.append((path, f["name"], int(f.get("size", 0) or 0)))
    return {"functions": int(m.get("total_functions", 0) or 0), "code": int(m.get("total_code", 0) or 0)}, matched


def _delinks_matched(config: Path) -> tuple[dict, list[tuple[str, str, int]]]:
    """Without objdiff's report: every function of a `complete` file (delinks.txt + symbols.txt of every module,
    like match.py's config_report)."""
    tot, matched = {"functions": 0, "code": 0}, []
    for delinks in sorted(config.rglob("delinks.txt")):
        symbols = delinks.with_name("symbols.txt")
        if not symbols.exists():
            continue
        funcs = sorted((int(a, 16), n, int(sz, 16)) for n, sz, a in FUNC_SYM.findall(symbols.read_text(encoding="utf-8")))
        addrs = [a for a, _n, _sz in funcs]
        tot["functions"] += len(funcs)
        tot["code"] += sum(sz for _a, _n, sz in funcs)
        for m in DELINK_BLOCK.finditer(delinks.read_text(encoding="utf-8")):
            path, body = m.group(1), m.group(2)
            if not path.startswith("src/") or "complete" not in body.split():
                continue
            for n, s, e in DELINK_SEC.findall(body):
                if n == "text":
                    lo, hi = bisect.bisect_left(addrs, int(s, 16)), bisect.bisect_left(addrs, int(e, 16))
                    matched += [(path, fn, sz) for _a, fn, sz in funcs[lo:hi]]
    return tot, matched


def project_report(root: Path, config: Path, report: dict | None = None, cache: bool = True) -> dict:
    """The functions matched by bytes, judged under the rules. The matched set is objdiff's (`report`, the
    build/<version>/report.json that match.py prints), so both numbers count the same functions; without a report
    with function lists, the functions of the `complete` files of delinks.txt. A symbol the checker cannot find in
    its source file (C++ method, macro-made function) follows its file: it passes only when no [match] rule fires
    in the file. A matched function with no source file to read (an objdiff unit outside src/) is `no_source`."""
    units = _check_units(scan_game(root, cache), asm_allowed(root))
    got = _report_matched(report) if report else None
    source = "objdiff" if got else "delinks"
    counts, matched = got or _delinks_matched(config)
    tot = {"source": source, "functions": counts["functions"], "code": counts["code"], "bytes_matched": 0,
           "bytes_matched_code": 0, "rules_matched": 0, "rules_matched_code": 0, "pending": 0, "original_asm": 0,
           "original_asm_code": 0, "unlocated": 0, "no_source": 0, "placeholders": 0}
    by_rule, pending, original, rows = {}, [], [], {}
    known = {p: {f["name"]: f for f in u["functions"]} for p, u in units.items()}
    blocked = {p: sorted({fd["rule"] for fd in u["findings"] if fd["tier"] == "match"}, key=lambda r: int(r[1:]))
               for p, u in units.items()}
    for path, n, sz in matched:
        tot["bytes_matched"] += 1
        tot["bytes_matched_code"] += sz
        row = rows.setdefault(path, {"path": path, "functions": 0, "rules_matched": 0, "pending": 0, "original_asm": 0})
        row["functions"] += 1
        if path not in units:
            tot["no_source"] += 1
            continue
        f = known[path].get(n)
        if f is None:
            tot["unlocated"] += 1
            f = {"status": PENDING if blocked[path] else OK, "placeholders": 0, "rules": blocked[path]}
        tot["placeholders"] += 1 if f["placeholders"] else 0
        if f["status"] == ORIGINAL_ASM:
            tot["original_asm"] += 1
            tot["original_asm_code"] += sz
            row["original_asm"] += 1
            original.append({"name": n, "file": path})
        elif f["status"] == PENDING:
            tot["pending"] += 1
            row["pending"] += 1
            pending.append({"name": n, "file": path, "rules": f["rules"]})
            for r in f["rules"]:
                by_rule[r] = by_rule.get(r, 0) + 1
        else:
            tot["rules_matched"] += 1
            tot["rules_matched_code"] += sz
            row["rules_matched"] += 1
    return {"totals": tot, "by_rule": dict(sorted(by_rule.items(), key=lambda kv: int(kv[0][1:]))), "pending": pending,
            "original_asm": original, "units": list(rows.values())}


SOURCES = {"objdiff": "objdiff's report.json", "delinks": "the complete files of delinks.txt"}


def summary(rep: dict) -> str:
    """The number under the rules, and how the byte-identical functions it starts from split (the byte count is
    the one of the matched set it was given, never a count of the checker's own)."""
    t = rep["totals"]
    counted = t["functions"] - t["original_asm"]
    rules = ", ".join(f"{r} {n}" for r, n in rep["by_rule"].items())
    return (f"{t['rules_matched']}/{counted} functions matched under the code rules: of the {t['bytes_matched']} "
            f"byte-identical ones ({SOURCES.get(t.get('source'), t.get('source'))}), {t['pending']} MATCH-PENDING"
            f"{' (' + rules + ')' if rules else ''}, {t['original_asm']} ORIGINAL-ASM listed apart"
            + (f", {t['no_source']} with no source file to read" if t.get("no_source") else ""))


def write_report(root: Path, rep: dict) -> Path:
    """build/coderules/report.json (everything) and totals.json (the counts alone: the studio reads it for every
    game on each refresh)."""
    out = root / "build" / "coderules" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8", newline="\n")
    out.with_name("totals.json").write_text(json.dumps(rep["totals"]) + "\n", encoding="utf-8", newline="\n")
    return out


def objdiff_report(project) -> dict | None:
    """The game's build/<version>/report.json when it is newer than every config file (like match.py progress),
    else None (the matched set then comes from delinks.txt)."""
    path = getattr(project, "REPORT", None)
    try:
        newest = max((q.stat().st_mtime for q in project.CONFIG.rglob("*.txt")), default=0)
        if path and path.stat().st_mtime >= newest:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="check only these files (default: every complete file of the game)")
    ap.add_argument("--pending", action="store_true", help="list the MATCH-PENDING functions")
    ap.add_argument("--advisory", action="store_true", help="also print the findings that do not block a match")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--strict", action="store_true", help="exit code 1 when a [match] rule fires")
    ap.add_argument("--no-cache", action="store_true", help="read every file again (build/coderules/scan-cache.json)")
    a = ap.parse_args()
    if a.files:
        texts = {f: Path(f).read_text(encoding="utf-8", errors="replace") for f in a.files}
        units = check_files(texts)
        bad = 0
        if a.json:
            print(json.dumps(units, indent=1))
        for p, u in units.items():
            for fd in sorted(u["findings"], key=lambda x: x["line"]):
                if fd["tier"] == "match" or a.advisory:
                    who = ", ".join(fd["functions"]) or "(file scope)"
                    if not a.json:
                        print(f"{p}:{fd['line']}: {fd['rule']} [{fd['tier']}] {who}: {fd['what']}")
            for f in u["functions"]:
                bad += f["status"] == PENDING
                if not a.json:
                    print(f"{p}: {f['name']}: {f['status']}" + (f" ({', '.join(f['rules'])})" if f["rules"] else "")
                          + (f", {f['placeholders']} placeholder name(s)" if f["placeholders"] else ""))
        sys.exit(1 if a.strict and bad else 0)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import project  # the game: DSD_PROJECT, this file's game, or the current folder
    rep = project_report(project.ROOT, project.CONFIG, objdiff_report(project), cache=not a.no_cache)
    out = write_report(project.ROOT, rep)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        if a.pending:
            for f in rep["pending"]:
                print(f"MATCH-PENDING {f['name']} ({f['file']}): {', '.join(f['rules'])}")
            for f in rep["original_asm"]:
                print(f"ORIGINAL-ASM  {f['name']} ({f['file']})")
        print(summary(rep))
        t = rep["totals"]
        print(f"open naming (R7): {t['placeholders']} matched functions still use placeholder names; "
              f"{t['unlocated']} symbol(s) judged with their file; report: {out.relative_to(project.ROOT).as_posix()}")
    if t.get("source") != "objdiff":
        print("matched set: the complete files of delinks.txt (no up-to-date build/<version>/report.json; "
              "`match.py verify --rules` uses objdiff's)")
    sys.exit(1 if a.strict and rep["totals"]["pending"] else 0)


if __name__ == "__main__":
    main()
