/* c2asm patterns: one small C idiom per function, compiled with each game's profile.
 * Format: a line `// @p NAME: description` right before each function `p_NAME`.
 * Globals keep the compiler from folding things away. */
typedef signed char s8;
typedef unsigned char u8;
typedef short s16;
typedef unsigned short u16;
typedef int s32;
typedef unsigned int u32;
typedef long long s64;
typedef unsigned long long u64;

extern s32 g_i;
extern u32 g_u;
extern s64 g_l;
extern void sink(s32);
typedef struct { u32 a : 3; u32 b : 5; u32 c : 8; u32 d : 16; } Bits;
typedef struct { s32 x; s16 y; s8 z; u8 w; s32 v; } Elem; /* 12 bytes */
typedef void (*Fn)(s32);
extern Fn g_table[];

// @p sdiv4: signed division by a power of two
s32 p_sdiv4(s32 x) { return x / 4; }

// @p sdiv10: signed division by 10 (magic multiply)
s32 p_sdiv10(s32 x) { return x / 10; }

// @p udiv10: unsigned division by 10 (magic multiply)
u32 p_udiv10(u32 x) { return x / 10; }

// @p smod8: signed modulo by a power of two
s32 p_smod8(s32 x) { return x % 8; }

// @p sdivvar: signed division by a variable (runtime call)
s32 p_sdivvar(s32 x, s32 y) { return x / y; }

// @p bitget: read a bitfield (5 bits at bit 3)
u32 p_bitget(Bits *p) { return p->b; }

// @p bitset: write a bitfield (5 bits at bit 3)
void p_bitset(Bits *p, u32 v) { p->b = v; }

// @p bool: normalise to 0/1
s32 p_bool(s32 x) { return x != 0; }

// @p min: ternary minimum
s32 p_min(s32 a, s32 b) { return a < b ? a : b; }

// @p abs: absolute value with a ternary
s32 p_abs(s32 a) { return a < 0 ? -a : a; }

// @p clamp255: clamp to 0..255
s32 p_clamp255(s32 a) { if (a < 0) a = 0; else if (a > 255) a = 255; return a; }

// @p zeroloop: zero an array with an index loop
void p_zeroloop(s32 *p, s32 n) { s32 i; for (i = 0; i < n; i++) p[i] = 0; }

// @p add64: 64-bit addition
s64 p_add64(s64 a, s64 b) { return a + b; }

// @p fxmul: fixed-point 20.12 multiply through s64
s32 p_fxmul(s32 a, s32 b) { return (s32)(((s64)a * b) >> 12); }

// @p stride12: index an array of 12-byte structs
s32 p_stride12(Elem *e, s32 i) { return e[i].v; }

// @p sbyte: load a signed byte field
s32 p_sbyte(Elem *e) { return e->z; }

// @p topbit: test the sign bit with a mask
s32 p_topbit(u32 x) { return (x & 0x80000000) ? 1 : 2; }

// @p switch6: dense switch (jump table)
s32 p_switch6(s32 x) {
    switch (x) {
    case 0: return 10; case 1: return 22; case 2: return 31;
    case 3: return 47; case 4: return 55; case 5: return 68;
    }
    return -1;
}

// @p fntable: call through a function-pointer table
void p_fntable(s32 i, s32 a) { g_table[i](a); }

// @p countdown: do-while countdown loop calling a function
void p_countdown(s32 n) { do { sink(n); } while (--n != 0); }

// @p swap16: byte swap of a 16-bit value
u16 p_swap16(u16 x) { return (u16)((x >> 8) | (x << 8)); }

// @p u16wrap: u16 arithmetic truncation
u16 p_u16wrap(u16 a, u16 b) { return (u16)(a + b); }

/* ---- batch 2 (2026-11-27) ---- */
extern s16 g_s16;
extern u8 g_bytes[];
typedef struct Node { struct Node *next; s32 val; } Node;
typedef struct { s32 a, b, c, d, e, f; } Big; /* 24 bytes */
typedef struct { s32 a : 3; s32 b : 5; } SBits;
#define REG32(a) (*(volatile u32 *)(a))
#define REG16(a) (*(volatile u16 *)(a))

// @p sdiv2: signed division by two
s32 p_sdiv2(s32 x) { return x / 2; }

// @p sdiv3: signed division by 3 (magic multiply)
s32 p_sdiv3(s32 x) { return x / 3; }

// @p udivvar: unsigned division by a variable (runtime call)
u32 p_udivvar(u32 x, u32 y) { return x / y; }

// @p umodvar: unsigned modulo by a variable (runtime call)
u32 p_umodvar(u32 x, u32 y) { return x % y; }

// @p smodvar: signed modulo by a variable (runtime call)
s32 p_smodvar(s32 x, s32 y) { return x % y; }

// @p umod10: unsigned modulo by 10
u32 p_umod10(u32 x) { return x % 10; }

// @p mul3: multiply by 3
s32 p_mul3(s32 x) { return x * 3; }

// @p mul10: multiply by 10
s32 p_mul10(s32 x) { return x * 10; }

// @p shl64: 64-bit shift left by a constant
s64 p_shl64(s64 x) { return x << 12; }

// @p shr64: 64-bit arithmetic shift right by a constant
s64 p_shr64(s64 x) { return x >> 12; }

// @p cmp64: 64-bit signed less-than
s32 p_cmp64(s64 a, s64 b) { return a < b; }

// @p mul64: 64-bit multiply
s64 p_mul64(s64 a, s64 b) { return a * b; }

// @p sbitget: read a signed bitfield
s32 p_sbitget(SBits *p) { return p->b; }

// @p flagset: set a flag bit in a field
void p_flagset(Bits *p) { *(u32 *)p |= 0x10; }

// @p flagclr: clear a flag bit in a field
void p_flagclr(u32 *p) { *p &= ~0x10; }

// @p flagtest: test a flag and branch to a call
void p_flagtest(u32 *p) { if (*p & 0x40) sink(1); }

// @p sext16: sign-extend through s16 cast
s32 p_sext16(s32 x) { return (s16)x; }

// @p sext8: sign-extend through s8 cast
s32 p_sext8(s32 x) { return (s8)x; }

// @p zext8: zero-extend through u8 cast
u32 p_zext8(u32 x) { return (u8)x; }

// @p lt: return a < b
s32 p_lt(s32 a, s32 b) { return a < b; }

// @p eq: return a == b
s32 p_eq(s32 a, s32 b) { return a == b; }

// @p max: ternary maximum
s32 p_max(s32 a, s32 b) { return a > b ? a : b; }

// @p clampminmax: clamp between two arguments
s32 p_clampminmax(s32 x, s32 lo, s32 hi) { return x < lo ? lo : (x > hi ? hi : x); }

// @p tofx: integer to 20.12 fixed point
s32 p_tofx(s32 x) { return x << 12; }

// @p fromfx: 20.12 fixed point to integer
s32 p_fromfx(s32 x) { return x >> 12; }

// @p globinc: increment a global counter
void p_globinc(void) { g_i++; }

// @p glob16: read a global s16
s32 p_glob16(void) { return g_s16; }

// @p regwrite: write a hardware register
void p_regwrite(u32 v) { REG32(0x04000000) = v; }

// @p regrmw: read-modify-write a 16-bit hardware register
void p_regrmw(u16 v) { REG16(0x04000008) = (u16)((REG16(0x04000008) & ~3) | v); }

// @p structcopy: copy a 24-byte struct
void p_structcopy(Big *d, Big *s) { *d = *s; }

// @p swap: swap two values through pointers
void p_swap(s32 *a, s32 *b) { s32 t = *a; *a = *b; *b = t; }

// @p bytesum: sum a byte array with an index loop
s32 p_bytesum(s32 n) { s32 i, s = 0; for (i = 0; i < n; i++) s += g_bytes[i]; return s; }

// @p strlen: count characters until zero
s32 p_strlen(const char *s) { s32 n = 0; while (*s++) n++; return n; }

// @p listwalk: walk a linked list summing a field
s32 p_listwalk(Node *p) { s32 s = 0; while (p) { s += p->val; p = p->next; } return s; }

// @p listfind: find a node by value
Node *p_listfind(Node *p, s32 v) { for (; p; p = p->next) if (p->val == v) return p; return 0; }

// @p arr2d: index a 2D array of 10 ints per row
s32 p_arr2d(s32 (*a)[10], s32 i, s32 j) { return a[i][j]; }

// @p ptrsel: choose between two pointers
s32 *p_ptrsel(s32 c, s32 *a, s32 *b) { return c ? a : b; }

// @p countup: for loop calling a function with the index
void p_countup(s32 n) { s32 i; for (i = 0; i < n; i++) sink(i); }

// @p nullcall: call only when the pointer is not null
void p_nullcall(Node *p) { if (p != 0) sink(p->val); }

// @p wrapidx: wrap an index with a mask
s32 p_wrapidx(s32 i) { return (i + 1) & 0x1f; }

// @p rangechk: unsigned range check of a signed value
s32 p_rangechk(s32 x) { return (u32)x < 10; }

/* ---- batch 3: loops shaped like the most frequent loop bodies of Sims 2 (2026-11-27) ---- */
extern s32 poll(void);
extern void work(void);
typedef struct { u8 pad[3]; u8 flags; } Flags;
typedef struct { s32 a, b, c, d, e; } Rec20; /* 20 bytes */
extern Rec20 g_recs[];
extern u8 g_buf[];

// @p countupk: for loop with a constant bound calling a function with the index
void p_countupk(void) { s32 i; for (i = 0; i < 8; i++) sink(i); }

// @p regwait16: busy-wait while a 16-bit hardware register bit is set
void p_regwait16(void) { while (REG16(0x04000280) & 0x8000) {} }

// @p regwait32: busy-wait while a 32-bit hardware register bit is set
void p_regwait32(void) { while (REG32(0x040001a4) & 0x80000000) {} }

// @p copybytes: copy n bytes with post-increment pointers
void p_copybytes(u8 *d, const u8 *s, s32 n) { while (n-- > 0) *d++ = *s++; }

// @p copyhalves: copy n halfwords with post-increment pointers
void p_copyhalves(u16 *d, const u16 *s, s32 n) { while (n-- > 0) *d++ = *s++; }

// @p pollwait: call until it returns zero
void p_pollwait(void) { while (poll() != 0) {} }

// @p flagwait: work until a flag bit appears
void p_flagwait(Flags *f) { do { work(); } while (!(f->flags & 4)); }

// @p vcounter: volatile loop counter (kept on the stack)
s32 p_vcounter(s32 n, s32 k) { volatile s32 i; s32 s = 0; for (i = 0; i < n; i++) s += k; return s; }

// @p recinit: set one field of a constant-size array of 20-byte records
void p_recinit(s32 v) { s32 i; for (i = 0; i < 16; i++) g_recs[i].c = v; }

// @p bytefill: fill a byte buffer from the index
void p_bytefill(s32 k) { u32 i; for (i = 0; i < 32; i++) g_buf[i] = (u8)(i + k); }

// @p strcpy: copy a string up to its zero
void p_strcpy(char *d, const char *s) { while ((*d++ = *s++) != 0) {} }

/* ---- batch 4: same asm, other C (2026-11-27, Pokemon Dash) ---- */
// @p ptrdiff4: difference of two pointers to 4-byte elements (same asm as x / 4)
s32 p_ptrdiff4(s32 *a, s32 *b) { return a - b; }

// @p ptrdiff12: difference of two pointers to 12-byte structs (magic multiply by 1/12)
s32 p_ptrdiff12(Elem *a, Elem *b) { return a - b; }

/* ---- batch 5: parameterised idioms (@vary, 2026-11-27) ---- */
typedef struct { s32 pad0, pad1, pad2; s8 b8; u8 ub8; s16 h16; u16 uh16; s32 w32; } Fields;

// @p divk: signed division by a constant
// @vary K: 3 5 6 7 9 10 12 16 20 24 30 32 60 100 1000
s32 p_divk(s32 x) { return x / @K; }

// @p udivk: unsigned division by a constant
// @vary K: 3 5 6 7 10 12 20 60 100 1000
u32 p_udivk(u32 x) { return x / @K; }

// @p modk: signed modulo by a constant
// @vary K: 3 4 5 6 7 10 12 16 32 60 100
s32 p_modk(s32 x) { return x % @K; }

// @p umodk: unsigned modulo by a constant
// @vary K: 3 5 6 7 10 12 60 100
u32 p_umodk(u32 x) { return x % @K; }

// @p mulk: multiply by a constant
// @vary K: 5 6 7 9 12 20 24 36 40 100
s32 p_mulk(s32 x) { return x * @K; }

// @p fieldadd: add to a field of a given type
// @vary F: b8 ub8 h16 uh16 w32
void p_fieldadd(Fields *p, s32 v) { p->@F += v; }

// @p fieldcmp: compare a field of a given type with a constant
// @vary F: b8 ub8 h16 uh16 w32
s32 p_fieldcmp(Fields *p) { return p->@F == 3; }

// @p castadd: add two values then cast
// @vary T: s8 u8 s16 u16
s32 p_castadd(s32 a, s32 b) { return (@T)(a + b); }

// @p fxmulsh: fixed-point multiply with a given shift
// @vary S: 8 10 12 14 16
s32 p_fxmulsh(s32 a, s32 b) { return (s32)(((s64)a * b) >> @S); }

// @p cmpsel: select one of two constants on a comparison
// @vary OP: < <= > >= == !=
s32 p_cmpsel(s32 a, s32 b) { return (a @OP b) ? 7 : 9; }

// @p regwaitk: busy-wait on a hardware register bit
// @vary W: u16 u32
// @vary B: 0x1 0x80 0x8000 0x80000000
void p_regwaitk(void) { while (*(volatile @W *)0x04000280 & @B) {} }

// @p loopk: for loop with a constant bound and a call
// @vary N: 2 3 4 8 16 32
// @vary OP: < <= !=
void p_loopk(void) { s32 i; for (i = 0; i @OP @N; i++) sink(i); }

// @p arrclr: clear a constant-size array of a given type
// @vary T: u8 u16 u32
// @vary N: 4 8 16 32
void p_arrclr(@T *p) { s32 i; for (i = 0; i < @N; i++) p[i] = 0; }
