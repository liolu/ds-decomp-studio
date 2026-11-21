import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coderules as cr


def status(source: str, name: str = "f", **kw) -> dict:
    return cr.check_function(source, name, **kw)


def rules(source: str, name: str = "f") -> list[str]:
    return status(source, name)["rules"]


class GenuineCodePasses(unittest.TestCase):
    """The checks are narrow: what the original programmers wrote must not be flagged."""

    def test_era_idioms(self):
        src = """
typedef struct Node { struct Node *next; int value; } Node;
int f(Node *list, char *dst, const char *src, int count) {
    Node *p;
    int total = 0;
    while (*src) {
        *dst++ = *src++;
    }
    while (--count)
        ;
    for (p = list; p != 0; p = p->next) {
        total += p->value;
    }
    if (!(p = list)) {
        goto fail;
    }
    switch (total) {
        case 0:;
        default:
            break;
    }
    return total * 10 + 0x10;
fail:
    return -1;
}
"""
        self.assertEqual(status(src), {"status": cr.OK, "rules": [], "blocking": [], "placeholders": 0})

    def test_hardware_register_volatile(self):
        src = """
void f(int v) {
    volatile unsigned short *ime = (volatile unsigned short *) 0x04000208;
    *(volatile unsigned short *) 0x4000208 = v;
    *ime = 0;
}
"""
        self.assertEqual(rules(src), [])

    def test_shared_work_area_volatile(self):
        """The ARM7 writes the system work area: the SDK reads it through volatile (CARDi_ReadRomIDCore)."""
        for addr in ("0x027FFE60", "0x27FFC3C", "0x02FFFE60", "0x02fffc00"):
            src = f"u32 f(void) {{\n    u32 v;\n    v = *(volatile u32 *) {addr};\n    return v;\n}}\n"
            self.assertEqual(rules(src), [], addr)
        self.assertEqual(rules("u32 f(void) { return *(volatile u32 *) 0x02001000; }\n"), ["R17"])

    def test_evidence_notes(self):
        src = """
typedef struct {
    int state;
    volatile int stopWait; // volatile: written by the sound thread (NNSSndArcStrm)
    char pad_14[4]; // reserved: NNSSndStrm.reserved
} Strm;
int f(Strm *s) {
    int unused; // R36: the frame keeps a 4-byte slot nothing writes
    return s->state;
}
"""
        self.assertEqual(rules(src), [])

    def test_unknown_members_by_offset_are_open_naming_only(self):
        src = "typedef struct { int unk_58; char unk_5C[12]; } Obj;\nint f(Obj *o) { return o->unk_58; }\n"
        r = status(src)
        self.assertEqual((r["status"], r["placeholders"]), (cr.OK, 1))

    def test_placeholder_function_name_does_not_block(self):
        r = status("void func_0200a808(void) {}\n", "func_0200a808")
        self.assertEqual((r["status"], r["placeholders"]), (cr.OK, 1))


class MatchRulesFire(unittest.TestCase):
    def test_r2_extern_outside_header(self):
        src = "extern int g_frameCount;\nint f(void) { return g_frameCount; }\nint g(void) { return 1; }\n"
        self.assertEqual(rules(src), ["R2"])
        self.assertEqual(rules(src, "g"), [])  # only the functions that use the global are held
        self.assertEqual([fd for fd in cr.check_source(src, "frame.h")["findings"] if fd["tier"] == "match"], [])

    def test_r2_function_pointer_global_is_data(self):
        self.assertEqual(rules("extern void (*g_hook)(int);\nvoid f(void) { g_hook(1); }\n"), ["R2"])

    def test_prototype_outside_header_is_advisory(self):
        u = cr.check_source("extern int other(int);\nint f(void) { return other(1); }\n")
        self.assertEqual([fd["rule"] for fd in u["findings"] if fd["tier"] == "match"], [])
        self.assertIn("R25", [fd["rule"] for fd in u["findings"]])

    def test_r4_offsets(self):
        for body in ("return M2C_FIELD(obj, int *, 0x58);",
                     "return *(int *) ((char *) obj + 0x58);",
                     "return ((int *) ((u8 *) obj + 0x58))->x;",
                     "return (*(int (**)(void *)) (*(u8 **) obj + 0x10))(obj);"):
            self.assertEqual(rules("int f(void *obj) { " + body + " }\n"), ["R4"], body)

    def test_r4_byte_arithmetic_alone_is_advisory(self):
        src = "void *f(unsigned char *file) { return (char *) file + 8; }\n"
        self.assertEqual(rules(src), [])
        self.assertIn("R4", [fd["rule"] for fd in cr.check_source(src)["findings"]])

    def test_r13_padded_vtable(self):
        u = cr.check_source("struct A { virtual void pad1(); virtual void Think(); };\n", "a.h")
        self.assertEqual([fd["rule"] for fd in u["findings"]], ["R13"])

    def test_r17_fake_code(self):
        cases = {
            "volatile local": "int f(int a) { volatile int t = a; return t; }",
            "volatile param": "int f(volatile int a) { return a; }",
            "hunt probe": "int f(s32 hunt_pad, int a) { return a; }",
            "unused local": "int f(int a) {\n    int dummy;\n    return a;\n}",
            "empty if": "int f(int a) { if (a) {} return a; }",
            "empty if statement": "int f(int a) { if (a); return a; }",
            "empty else": "int f(int a) { if (a) { a = 1; } else {} return a; }",
            "bare statement": "int f(int a) { a++;; return a; }",
            "do while 0": "int f(int a) { do { a++; } while (0); return a; }",
            "self assignment": "int f(int a) { a = a; return a; }",
            "plus zero": "int f(int a) { return a + 0; }",
            "times one": "int f(int a) { return a * 1; }",
            "padding member": "typedef struct { int a; char pad[3]; } S;\nint f(S *s) { return s->a; }",
        }
        for what, src in cases.items():
            self.assertEqual(rules(src + "\n"), ["R17"], what)

    def test_r17_ignores_macros_comments_and_strings(self):
        src = """
#define SWAP(a, b) do { int t = a; a = b; b = t; } while (0)
/* volatile a = a; */
int f(int a) {
    const char *s = "x = x; + 0";
    return a + (s != 0);
}
"""
        self.assertEqual(rules(src), [])

    def test_r18_assembly(self):
        src = "asm void f(void) {\n    swpb r0, r0, [ip]\n    bx lr\n}\n"
        self.assertEqual(status(src)["status"], cr.PENDING)
        self.assertEqual(rules(src), ["R18"])
        self.assertEqual(status(src, original_asm={"f"})["status"], cr.ORIGINAL_ASM)
        cited = "// ASM: pokediamond arm9/lib/NitroSDK/src/OS_irqHandler.c\n" + src
        self.assertEqual(status(cited)["status"], cr.ORIGINAL_ASM)


class AcrossFiles(unittest.TestCase):
    def test_r1_two_bodies(self):
        units = cr.check_files({
            "src/a.c": "typedef struct { int count; float scale; } Foo;\nint a(Foo *f) { return f->count; }\n",
            "src/b.c": "typedef struct { int count; } Foo;\nint b(Foo *f) { return f->count; }\nint c(void) { return 0; }\n",
        })
        self.assertEqual({f["name"]: f["rules"] for f in units["src/b.c"]["functions"]}, {"b": ["R1"], "c": []})
        self.assertEqual(units["src/a.c"]["functions"][0]["status"], cr.PENDING)

    def test_r1_same_body_twice_is_advisory(self):
        t = "typedef unsigned short u16;\nu16 %s(void) { return 1; }\n"
        units = cr.check_files({"src/a.c": t % "a", "src/b.c": t % "b"})
        self.assertEqual(units["src/a.c"]["functions"][0]["status"], cr.OK)
        self.assertEqual([fd["tier"] for fd in units["src/a.c"]["findings"] if fd["rule"] == "R1"], ["advisory"])

    def test_r1_class_struct_mismatch_is_advisory(self):
        """mwccarm does not put the class key in mangled names (only MSVC does), and a .c file cannot say `class`."""
        units = cr.check_files({"include/a.h": "class Actor;\n", "include/b.h": "struct Actor { int x; };\n",
                                "src/c.c": "struct Actor;\nint f(struct Actor *a) { return 0; }\n"})
        self.assertEqual([(fd["rule"], fd["tier"]) for fd in units["include/a.h"]["findings"]], [("R1", "advisory")])
        self.assertEqual(units["src/c.c"]["functions"][0]["status"], cr.OK)

    def test_r1_file_local_helper_types_are_advisory(self):
        """m2c drafts name their own local struct `D`, `Obj`...: unrelated types sharing a placeholder name."""
        files = {f"src/f{i}.c": f"typedef struct D {{ int a{i}; }} D;\nint f{i}(D *d) {{ return d->a{i}; }}\n"
                 for i in range(4)}
        units = cr.check_files(files)
        self.assertEqual({u["functions"][0]["status"] for u in units.values()}, {cr.OK})
        self.assertEqual({fd["tier"] for u in units.values() for fd in u["findings"] if fd["rule"] == "R1"},
                         {"advisory"})
        # nearly one body per file, whatever the name
        files = {f"src/g{i}.c": f"typedef struct {{ int b{i}; }} Owner;\nint g{i}(Owner *o) {{ return o->b{i}; }}\n"
                 for i in range(3)}
        self.assertEqual({u["functions"][0]["status"] for u in cr.check_files(files).values()}, {cr.OK})

    def test_r1_holds_header_types_and_shared_names(self):
        local = "typedef struct D { int z; } D;\nint f(D *d) { return d->z; }\n"
        units = cr.check_files({"include/d.h": "typedef struct D { int a; } D;\n", "src/f.c": local})
        self.assertEqual(units["src/f.c"]["functions"][0]["rules"], ["R1"])
        # one real type spelled two ways in many files (Vec3 in Lego: 202 files, 14 bodies) stays R1
        v1, v2 = "typedef struct { s32 x, y, z; } Vec3;\n", "typedef struct { int x; int y; int z; } Vec3;\n"
        files = {f"src/v{i}.c": (v1 if i % 3 else v2) + f"int v{i}(Vec3 *v) {{ return v->x; }}\n" for i in range(6)}
        self.assertEqual({u["functions"][0]["status"] for u in cr.check_files(files).values()}, {cr.PENDING})

    def test_r2_two_types(self):
        units = cr.check_files({"include/a.h": "extern int g_frameCount;\n", "include/b.h": "extern long g_frameCount;\n"})
        self.assertEqual([fd["rule"] for fd in units["include/b.h"]["findings"]], ["R2"])

    def test_r2_linkage_string_is_not_part_of_the_type(self):
        h = 'extern s32 data_02101a64;\n'
        a = 'extern "C" s32 data_02101a64;\ns32 f(void) { return data_02101a64; }\n'
        units = cr.check_files({"include/engine.h": h, "src/a.cpp": a})
        self.assertEqual([fd["what"] for u in units.values() for fd in u["findings"] if "different types" in fd["what"]],
                         [])
        self.assertEqual(units["src/a.cpp"]["functions"][0]["rules"], ["R2"])  # still an extern outside a header
        units = cr.check_files({"include/engine.h": 'extern "C" {\nextern s32 g;\n}\n',
                                "include/other.h": 'extern "C"   s32 g;\n'})
        self.assertEqual([fd for u in units.values() for fd in u["findings"]], [])


def make_game(root: Path) -> Path:
    cfg = root / "config" / "eu"
    (cfg / "arm9").mkdir(parents=True)
    (root / "src" / "auto").mkdir(parents=True)
    (cfg / "arm9" / "symbols.txt").write_text(
        "clean kind:function(arm,size=0x10) addr:0x02000000\n"
        "func_02000010 kind:function(arm,size=0x20) addr:0x02000010\n"
        "OS_GetLockID kind:function(arm,size=0x8) addr:0x02000030\n"
        "func_02000038 kind:function(arm,size=0x40) addr:0x02000038\n", encoding="utf-8")
    (cfg / "arm9" / "delinks.txt").write_text(
        "    .text start:0x02000000 end:0x02000078 kind:code align:4\n\n"
        "src/auto/clean.c:\n    complete\n    .text start:0x02000000 end:0x02000010\n\n"
        "src/auto/func_02000010.c:\n    complete\n    .text start:0x02000010 end:0x02000030\n\n"
        "src/auto/OS_GetLockID.c:\n    complete\n    .text start:0x02000030 end:0x02000038\n", encoding="utf-8")
    (root / "src" / "auto" / "clean.c").write_text("int clean(int a) { return a; }\n", encoding="utf-8")
    (root / "src" / "auto" / "func_02000010.c").write_text(
        "extern int data_02001000;\nint func_02000010(void *p) { return M2C_FIELD(p, int *, 4) + data_02001000; }\n",
        encoding="utf-8")
    (root / "src" / "auto" / "OS_GetLockID.c").write_text(
        "// ASM: pokediamond arm9/lib/NitroSDK/src/OS_spinLock.c\nasm int OS_GetLockID(void) {\n    bx lr\n}\n",
        encoding="utf-8")
    return cfg


class WholeGame(unittest.TestCase):
    def test_matched_set_is_objdiffs(self):
        """With objdiff's report the byte count is the report's: a function matched in a file that is not `complete`
        yet counts, one the report says differs does not (match.py verify prints the same number)."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = make_game(root)
            (root / "src" / "auto" / "wip.c").write_text("int func_02000038(int a) { return a + 0; }\n",
                                                         encoding="utf-8")
            unit = lambda path, *fns: {"name": "eu/" + path, "metadata": {"source_path": path}, "functions": [  # noqa
                {"name": n, "size": str(sz), **({"fuzzy_match_percent": p} if p else {})} for n, sz, p in fns]}
            report = {"measures": {"total_functions": 4, "matched_functions": 3, "total_code": "120"}, "units": [
                unit("src/auto/clean.c", ("clean", 16, 100.0)),
                unit("src/auto/func_02000010.c", ("func_02000010", 32, 87.5)),
                unit("src/auto/wip.c", ("func_02000038", 64, 100.0)),
                unit("asm/gap_02000030.s", ("OS_GetLockID", 8, 100.0))]}
            t = cr.project_report(root, cfg, report, cache=False)["totals"]
            self.assertEqual((t["source"], t["functions"], t["bytes_matched"], t["rules_matched"], t["pending"],
                              t["no_source"]), ("objdiff", 4, 3, 1, 1, 1))
            # match.py progress without a fresh objdiff report: config_report has no function lists
            t = cr.project_report(root, cfg, {"measures": {}, "units": [{"name": "x", "measures": {}}]})["totals"]
            self.assertEqual((t["source"], t["bytes_matched"]), ("delinks", 3))

    def test_scan_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = make_game(root)
            first = cr.project_report(root, cfg)
            self.assertTrue((root / "build" / "coderules" / cr.CACHE_NAME).is_file())
            orig = cr.scan
            try:  # nothing changed: no file is scanned again, same report
                cr.scan = lambda *a, **k: self.fail("scanned a file the cache holds")
                self.assertEqual(cr.project_report(root, cfg), first)
            finally:
                cr.scan = orig
            f = root / "src" / "auto" / "func_02000010.c"
            f.write_text("int func_02000010(int *p) { return p[1]; }\n", encoding="utf-8")
            t = cr.project_report(root, cfg)["totals"]
            self.assertEqual((t["rules_matched"], t["pending"]), (2, 0))

    def test_both_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = make_game(root)
            rep = cr.project_report(root, cfg)
            t = rep["totals"]
            self.assertEqual((t["functions"], t["bytes_matched"], t["rules_matched"], t["pending"], t["original_asm"]),
                             (4, 3, 1, 1, 1))
            self.assertEqual(rep["by_rule"], {"R2": 1, "R4": 1})
            self.assertEqual(rep["pending"], [{"name": "func_02000010", "file": "src/auto/func_02000010.c",
                                               "rules": ["R2", "R4"]}])
            self.assertIn("1/3 functions matched under the code rules: of the 3 byte-identical ones (the complete "
                          "files of delinks.txt), 1 MATCH-PENDING (R2 1, R4 1), 1 ORIGINAL-ASM", cr.summary(rep))
            self.assertTrue(cr.write_report(root, rep).is_file())
            self.assertIn('"rules_matched": 1', (root / "build" / "coderules" / "totals.json").read_text())

    def test_blocking_list_is_capped(self):
        body = "".join(f"    M2C_FIELD(p, int *, {4 * i}) = {i};\n" for i in range(20))
        r = cr.check_function("void f(void *p) {\n" + body + "}\n", "f", limit=5)
        self.assertEqual((len(r["blocking"]), r["blocking"][-1]), (6, "... and 15 more"))


if __name__ == "__main__":
    unittest.main()
