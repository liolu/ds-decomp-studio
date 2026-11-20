# Decompilation code rules

These rules are for any matching decompilation: source rebuilt with the original compiler to reproduce a retail
binary. A project's `AGENTS.md` fills in the **project profile** (below) and may tighten or relax a rule. It must
say so explicitly, with the reason.

## Why the rules exist

A matching decompilation exists so people can **understand the original program**. Identical bytes are the proof
that the source is faithful. They are not the goal. Source that matches but that nobody can read has failed at the
job, however good its score.

So every rule serves one test, **the reader test**:

> Would a programmer on the original team, writing in that codebase's style and dialect, have typed this?
> And can a reader see what the code does, and why, without opening the disassembly?

A **fakematch** is source that produces the right bytes but fails the reader test: a dummy temporary, a
`volatile` carrier, an empty block, a reused variable, an offset cast, a statement that exists only to steer the
compiler. A fakematch is not a match (R17). It is a clue to the real source, and work stays open until the real
source is found.

The reader test also protects real code. Idioms that programmers of the era wrote all the time are not fakes, even
when they look dense today: `*dst++ = *src++`, `while (--count)`, `goto fail` cleanup, a long `switch`, a long
function, a bug the original shipped. Section F lists both sides.

**Rule 0: the bytes win.** A change made for style must not change what the compiler emits. Every rule applies
only as far as the original binary allows. When a rule and a match disagree, keep the match and record a rule
exception at the code: `// RULE-EXCEPTION: <rule>, <why the original's bytes need this>`. An exception needs a
reason the bytes give, not convenience. The exception must still pass the reader test: it bends a style rule, it
never licenses fake code.

## Tiers

Each rule is tagged:

| tag | meaning |
|---|---|
| **[match]** | **A function that breaks this rule does not count as matched**, even when its bytes are identical. The checker reports it as `MATCH-PENDING`, and progress counts only functions that match *and* pass every [match] rule. |
| **[free]** | Can't change the emitted code: apply it anywhere. There are two traps: `__LINE__` and line information (R23). |
| **[checked]** | Can change code or layout: apply only with the project's per-function check and its byte gate. |
| **[evidence]** | Changes a name or signature that the binary records (mangled names, exports, RTTI, strings): needs evidence. |

The [match] tier is what keeps "matched" honest. Identical bytes with scattered declarations, offset casts or
fake code reproduce the binary but not the source's structure: the job is half done. Naming is deliberately not
in this tier: a match with placeholder names is a real match whose naming is still open work.

Only rules that a checker can test mechanically belong in this tier, so a match can be computed rather than
argued. **A [match] rule blocks a match exactly where its checker row (at the end of this file) fires.** The rest
of the rule's text is review guidance.

Rule numbers are stable identifiers that other skills and checkers cite. They are grouped by topic, not numbered
in reading order; new rules take the next free number.

## Project profile (filled in per project, in AGENTS.md)

- **Compiler and dialect:** for example VC6 is C++98 with VC6 quirks; GCC 2.95 is pre-standard; IDO is C89.
  List what the compiler accepts and rejects (R22).
- **Annotation format** for functions, stubs, data and parking. The parking mechanism (for example
  `#ifdef NON_MATCHING`) is project-defined and exempt from R37.
- **Naming style:** the original's conventions, as a table (entity → style → examples), and the placeholder
  patterns to reject (`FUN_`, `DAT_`, `sub_`, `unk_`, `local_`, `param_`, `var\d+`, `field_0x`, `m_Unk`,
  `UnkType_`). Without evidence of the original style, start from a default in
  [style-defaults.md](style-defaults.md) and record the choice.
- **Layout style:** brace placement, indent, line limit, function banner and section banner forms.
- **Evidence sources:** surviving source, SDK, symbol files, strings, RTTI, sibling binaries, and published source
  from the same studio or engine family.
- **Line information:** whether the retail binary or its debug data records source line numbers. If it does,
  layout changes are not free (R23).
- **Commands:** the per-function check, the module and number gate, the byte gate, the rule checker.
- **Rule changes:** which rules the project tightens or relaxes, and why.

---

## A. Declarations and types

### R1. Declare each type once, in a shared header. [match]

One declaration per struct, class, enum or typedef, in a header every user includes. These are violations:
- a local copy;
- a partial "layout view" of the same object;
- a forward declaration whose `class`/`struct` keyword differs from the definition (in MSVC that changes the
  mangled name).

❌ **a.cpp**
```cpp
struct Foo { int count; float scale; };
```

❌ **b.cpp**
```cpp
struct FooHead { int count; };          // part of Foo, read through a cast
```

✅ **foo.h**
```cpp
struct Foo
{
    int   count;
    float scale;
};
```

✅ **a.cpp**, **b.cpp**
```cpp
#include "foo.h"
```

Two things are not violations:
- **Unit-private types.** A type used by one unit only may be defined at the top of that unit, as the original
  often did, provided no other unit declares it.
- **C's inheritance idiom.** A struct that starts with another struct as its first member is a deliberate design
  (DOOM's `thinker_t` at the head of `mobj_t`). A layout view is a *copy* of another struct's leading fields,
  read through a cast.

### R2. Declare each global once, as `extern` in a header; define it once, in its owning unit. [match]

❌ Each unit writes its own declaration, possibly of a different type:
```cpp
extern int g_frameCount;                // a.cpp
extern long g_frameCount;               // b.cpp: a different type that still links
```

✅ **frame.h**
```cpp
extern int g_frameCount;
```

✅ **frame.cpp**, the owner: the unit whose data range holds the address
```cpp
#include "frame.h"
int g_frameCount;                       // with the project's data annotation
```

Never model an address inside an object as separate storage: declare the containing object and use its member.
Where a definition sits decides which data section holds it, and declaration order can decide layout (some
compilers order `.bss` by a hash of the name). So moving or reordering definitions is [checked].

Much 1990s C declared `extern`s inside the `.c` file. A project with surviving source showing that habit may relax
this rule in its profile.

### R3. Reconstructed headers have a fixed shape. [free for comments and blank lines; checked for order]

A reader should know where to look before opening a header. When the original header's order is unknown, use
this one:

1. include guard (`#ifndef FOO_H` / `#define FOO_H`, or the original's guard style);
2. the includes the header itself needs;
3. shared constants and flag groups;
4. enums and typedefs;
5. structs and classes, each followed by its inline methods if any;
6. `extern` globals;
7. prototypes, **grouped by the unit that defines them**, each group under a `// unit.c` comment. Constants that
   belong to one unit's API sit right after that unit's prototypes.

✅ **g_local.h**
```c
//
// g_combat.c
//
qboolean CanDamage( gentity_t *targ, vec3_t origin );
void G_Damage( gentity_t *targ, gentity_t *inflictor, gentity_t *attacker,
               vec3_t dir, vec3_t point, int damage, int dflags, int mod );

// damage flags
#define DAMAGE_RADIUS       0x00000001  // damage was indirect
#define DAMAGE_NO_ARMOR     0x00000002  // armour does not protect from this damage
```

Since one unit is one object file (R15), the `// unit.c` groups document the binary's own layout.

When the original or SDK header's order is known, keep it. Reordering a header is [checked]:
- include order decides which macros are visible;
- `#pragma pack` state carries from one declaration to the next;
- some compilers (GCC 2.x) inline only functions defined before their use.

Split headers by audience, as the original engines did:
- a **public** header is the contract between modules (`g_public.h`, `RenderSystem.h`);
- a **local** header is shared only inside one module (`g_local.h`, `tr_local.h`, `Common_local.h`).

Comment `#else` and `#endif` with their condition when the block is longer than a few lines.

### R4. Use typed members, never fixed offsets. [match]

❌
```cpp
float r = *(float *)((char *)obj + 0x58);
*(int *)((char *)model + 0x10) |= 1;
```

✅
```cpp
float r = obj->radius;
model->flags |= MODEL_DIRTY;
```

These don't count either:
- casts of `this` followed by offset arithmetic or a dereference;
- offset macros;
- a pointer typed `void *` or `int` only to dodge the real type.

Byte-pointer arithmetic is legitimate where the data has no fixed struct: file parsers, allocator headers,
`offsetof` in field-description tables (Quake III's `FOFS`). Passing `this` as a callback cookie, and C++ casts
between bases and derived classes, are legitimate too.

### R5. Use an enum for a proven finite set of values. [evidence]

❌
```cpp
int BlendFor(Surface *s)
{
    return (s->flags & 4) ? 2 : 0;
}
```

✅
```cpp
enum BlendMode { BLEND_NONE = 0, BLEND_ADD = 1, BLEND_MODULATE = 2 };

BlendMode BlendFor(Surface *s)
{
    return (s->flags & SURF_MODULATE) ? BLEND_MODULATE : BLEND_NONE;
}
```

Name the values for what they mean. Changing a parameter or return type to an enum changes C++ mangling. A field
the original stores as 1 or 2 bytes keeps that width, using the enum only for its values. Prefer an enum the
engine or SDK already defines.

Adding or moving an enumerator, such as a count at the end, is [checked]: with short enums (Metrowerks, GCC
`-fshort-enums`) it can change the enum's size, and without explicit values it renumbers what follows. Enum naming
is in R29.

### R6. Use the original's own types and APIs. [evidence]

Use the engine's and SDK's types (`LTBOOL`, `qboolean`, `DWORD`, `u32`, `s16`, `HRESULT`) where the original used
them. Use `bool` only where the evidence shows `bool`: sizes and mangling differ. Include the real SDK and platform
headers; never hand-roll their declarations.

### R25. Every function has a prototype in scope, with its real types. [checked]

In C, calling a function without a prototype silently promotes `float` arguments to `double`, `char` and `short`
to `int`, and assumes an `int` return. That changes call sites. A missing or wrong prototype is also a reader's
dead end: the reader can't see what the function takes.

- Each function called from another unit has its prototype in a header (R3), never a local `extern` in the caller.
- A function with no parameters is declared `(void)` in C.
- A `static` function used before its definition gets a forward declaration near the top of the unit, as the
  original did.

Two cases keep the original's form:
- **Unprototyped calls.** If the original really called a function without a prototype (the bytes show the
  promotion), keep that with a `RULE-EXCEPTION`.
- **K&R definitions.** Don't convert an old-style (K&R) definition to a prototype without checking. The
  definition's style decides how the callee expects `float` and `char` parameters.

### R26. Keep pointers typed; leave `void *` at the boundary. [checked]

`void *` throws the type away, and the reader with it.
- Use the real pointee type in parameters, members and locals.
- Where the original API really takes `void *` (callbacks, allocators, `qsort` comparators, user-data slots), assign
  it to a typed local at the top of the function and use only that.
- In C, don't cast a `void *` on assignment: the conversion is implicit.

❌
```c
int SortByDist( const void *a, const void *b )
{
    return ((const drawSurf_t *)a)->sort - ((const drawSurf_t *)b)->sort;
}
```

✅
```c
int SortByDist( const void *a, const void *b )
{
    const drawSurf_t *surfA = a;
    const drawSurf_t *surfB = b;

    return surfA->sort - surfB->sort;
}
```

The typed local is usually free under optimization, but on some compilers it can move a load. Check it.

### R27. Lay out structs and classes so they read as documentation. [free for comments; checked for order]

A struct definition is the best documentation a decompilation produces. Write it so:
- **One member per line**, with the type and the name in aligned columns.
- **Comments** give units, owners and lifetimes: `int nextthink; // level.time when think() runs`, `// cleared
  each map`, `// gentity->flags`.
- **Groups:** separate members that are already contiguous into commented groups (`// physics`, `// rendering`).
- **Bit flags** that live in one member are defined as a block next to the struct, under a comment naming the
  member they belong to (R29).

**Unknown members** keep a placeholder name with their offset (`int unk_58;` or `byte unk_58[12];` for a range no
recovered code touches). They are open work (R7), never an invented confident name. An array named for its offset
that covers an untouched range is honest. A padding array that pushes known members into place, or swallows
members that recovered code does touch, is fake (R17).

What may never move in a class:
- **Data members:** their declaration order is the memory layout, set by the binary (R1).
- **Virtual methods:** their declaration order is the vtable order, set by the binary (R13).
- **Access level:** MSVC records whether a method is public, protected or private in its mangled name.

A class may be grouped into sections, with event handlers and callbacks last, only as far as each member keeps its
access level and the data order holds. Never merge sections that contain data members. Moving inline methods is
[checked]: it can change which copies the compiler emits and in what order.

---

## B. Names

### R7. Name things for what they mean; no placeholders. [checked; evidence for recorded names]

Names are not required for a match, but the checker reports placeholders as open naming work. These are
placeholders:
- disassembler placeholders: `FUN_`, `DAT_`, `sub_`, `unk_`, `local_`, `param_`, `field_0x`, `uStack`, `iVar3`,
  `var3`;
- address-derived names (`g_004e370c`, `Func_10023860`);
- compiler ordinals;
- numbered generic names: `temp1`, `ptr2`, `result2`, `v3`.

A plain `temp` in a swap, or a `flag` the original codebase's style uses, is not a placeholder.

❌
```cpp
int var3 = 2;
void FUN_10023860(int param_1);
extern DWORD DAT_004e370c;
```

✅
```cpp
int retries = 2;
void d3d_ProcessLight(LTObject *light);
extern uint32 g_CV_TraceConsole;
```

- **Evidence first.** The binary often names things itself:
  - an error or log string that starts with a function name (`"Z_Free: NULL pointer"`, `"FS_Read: -1 bytes
    read"`) names the function that prints it;
  - a console variable's string (`"g_gravity"`) names the variable that holds it;
  - a console command's string (`"vid_restart"`) names its handler (`Vid_Restart_f`);
  - assert text, RTTI, exports and debug symbols name what they cover.
- **Recorded names are kept verbatim**, including their case and their misspellings (`persistant`,
  `allready`). Don't correct a recorded name: [evidence].
- **Invented names.** A name we invent is allowed but recorded as invented (provenance), never presented as
  original.
- **Unknown purpose.** When the purpose is truly unknown, keep the placeholder or leave an identity-TODO marker;
  never write a fake descriptive name.
- **Names that change bytes.** Renaming is [checked]:
  - static and file-scope names can decide data layout;
  - local names can decide stack slots on some compilers;
  - names reach the data through stringizing macros (`assert( count > 0 )` embeds its text), `__FUNCTION__`, RTTI
    type names and debug information.

### R8. Follow the original codebase's naming style, module by module. [free, within R7's limits]

Use the style in the project profile's table; mixing two styles in one module is worse than either.

Real codebases are written by several teams, and their style differs by module. Quake III's bot library uses
Allman braces, lower-case run-together locals and `} //end of the function` markers, while its game module uses
K&R braces and `/* ==== */` function banners. Both styles are original. Follow the style of the module or unit
you're in, and don't normalize one team's code into another's. The profile's table may have one row per module.

Without evidence of the original's style, start from a default in [style-defaults.md](style-defaults.md) (a C
engine style and a C++ engine style, both taken from id Software's released engines) and write the choice into
the profile.

Applying a style to a name is free only where the name doesn't reach the bytes (R7). Otherwise it is [checked].

### R28. Free functions carry their module's prefix. [checked; evidence for recorded names]

A prefix tells the reader where a function lives and who may call it, and C has no namespaces to do it instead.
- **The prefix names the subsystem**, and the subsystem matches the unit or the group of units: `G_` game, `CG_`
  client game, `SV_` server, `R_` renderer, `RB_` render back end, `FS_` file system, `Cvar_`, `Cmd_`, `Com_`.
  Classic DOOM uses one capital: `P_` play, `R_`, `S_`, `Z_` zone memory.
- **Shape:** `Prefix_VerbNoun` (`G_RunThink`, `FS_ReadFile`, `P_SpawnMobj`), in the style the profile chose.
- **Units are named after the prefix:** `g_combat.c`, `tr_main.c`, `p_mobj.c`. When you name a unit whose original
  name is lost, use the prefix of the functions it holds.
- **`static` helpers** may drop the prefix if the original style does (Quake III's `SetFarClip`), but never take
  another module's prefix.
- **Role suffixes and prefixes** are part of the name:
  - `_f` for console command handlers (`Cmd_Wait_f`);
  - `SP_` for spawn functions (`SP_func_door`);
  - `Event_` for script event handlers;
  - `trap_` for system-call wrappers, keeping the callee's own prefix (`trap_FS_Read`).

### R29. Name each kind of thing by its rule. [free, within R7's limits; evidence where recorded]

The project's style table fixes the exact case. Whatever the case, every kind of thing follows one pattern, so a
reader can tell a type from a constant from a function at a glance.

**Types**
- **Struct typedefs** carry a type marker: `gentity_t`, `drawSurf_t`. A self-referencing C struct uses a tag
  (`struct gentity_s`) and a typedef (`gentity_t`).
- **C++ classes** carry the project's class marker: `idEntity`, `CPlayer`.
- **Interfaces and implementations:** an implementation is named after its interface (`idCommon` and
  `idCommonLocal`, `idGame` and `idGameLocal`).

**Enums and constants**
- **Enum values** are upper case and share a prefix that names their type (`GT_FFA`, `GT_CTF` in `gametype_t`;
  `MOVETYPE_ANIM`). If the set has a count value, it comes last: `GT_MAX_GAME_TYPE`, `NUM_MOVETYPES`. Adding one is
  [checked] (R5).
- **Constants** are upper case: a `#define` or enum in C, a `const` in C++ (R11 explains why C differs).
  - `MAX_` for a capacity or limit (`MAX_GENTITIES`);
  - `NUM_` for a count;
  - a unit suffix or comment on durations and distances (`FRAMETIME 100 // msec`, `WEAPON_DROP_TIME`).
  - A function-like macro that stands in for a function may use the function style (`VectorCopy`), as the
    original did.
- **Bit flags** share a prefix that names their owner (`FL_GODMODE` for `ent->flags`, `SVF_NOCLIENT` for
  `svFlags`, `CVAR_ARCHIVE`). Write them in hex and keep them in one block.

**Functions**
- **Accessors and queries** use stable verbs: `Get`/`Set`, `Is`/`Has` for booleans, `Num` for counts, `Find`
  (may fail and return null) versus `Get` (always succeeds), `Init`/`Shutdown`, `Alloc`/`Free`, `Spawn`.
- **Callbacks** are named by the role they fill: `Think`, `Touch_Door`, `Use_Target`, `player_die`, `Event_Hide`.
  A function-pointer typedef names the role too.

**Variables**
- **Booleans** name the state, not the test: `inuse`, `hidden`, `spawning`, `readyToExit`.
- **Globals** use the original's marker, or `g_` for game state. **Console variables** keep their console
  string as the variable name (`g_gravity` holds `"g_gravity"`).
- **Subsystem state** often lives in one struct with a short global (`level`, `cg`, `tr`, `svs`). Use such a
  struct only when the binary shows the fields are contiguous and accessed through one base. Don't build one to
  tidy separate globals: that changes layout (R2).

### R30. One local, one meaning, one name. [checked]

Optimizing compilers reuse a register or stack slot for values that never overlap, and decompilers then merge
those values into one variable. The original programmer usually wrote separate variables.
- Split a merged variable into one local per meaning, each named for that meaning. A `count` that later holds a
  pointer is two variables.
- Conventional short names are good names where the original codebase uses them: `i`, `j` for loop indices;
  `ent`, `self`, `other`, `cl`, `ps`, `tr` for engine objects. Use them consistently.
- Declare each local in the narrowest block that **already exists**: a loop or `if` body. In C89 that is the top
  of such a block (R22). Never add a `{ }` block just to scope a variable: that is an arbitrary block (R17).
- Initialize a local at its declaration only when the original evidently did.

❌
```c
int v1;
v1 = TeamCount( -1, TEAM_RED );
...
v1 = (int)ent->client;          // same slot, a new meaning
```

✅
```c
int        teamCount;
gclient_t *client;

teamCount = TeamCount( -1, TEAM_RED );
...
client = ent->client;
```

If the bytes need one variable where two meanings live, keep one and record a `RULE-EXCEPTION`.

---

## C. Literals and operations

### R9. Write numbers in the base that fits their meaning. [free within the signed int range; checked beyond]

- **Decimal:** counts, sizes, indices, angles, arithmetic.
- **Hex:** masks, flags, colours, hardware registers, addresses.

Never write a float as raw bits (`0x3f800000`); write `1.0f`.

❌
```cpp
if (flags & 2048)
for (i = 0; i < 0x20; ++i)
```

✅
```cpp
if (flags & FLAG_SOLID)
for (i = 0; i < 32; ++i)
```

A literal that doesn't fit in a signed `int` takes a type that depends on its base: `0x80000000` is
`unsigned int`, while `2147483648` is `long` or `unsigned long`. On a 16-bit-`int` target, the same happens from
`0x8000` and `32768` upwards. The type decides signed versus unsigned comparisons, shifts and divides, so
changing the base of such a literal is [checked].

### R10. Name bit operations; don't replace them. [checked]

Keep the original's masks and shifts, since replacing them changes codegen. Give them names instead: flag
constants, packing macros or inline helpers. Add parentheses wherever bit operators mix with other operators.

❌
```cpp
c = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
```

✅
```cpp
c = RGB555(r, g, b);
```

### R11. Name meaningful constants. [free for `#define` and enum; checked otherwise]

Name each value by its meaning, with an enum or a `#define`: both fold to the same immediate. Struct offsets, sizes
taken from the binary and arbitrary format constants need a comment, not necessarily a name.

Two other forms are [checked]:
- **`const` integers.** In C++ a `const int` folds like a literal. In C it is an object: unoptimized builds load
  it from memory, and it can't size an array or label a `case`. In C, use `#define` or an enum.
- **Floats.** A named `const float` may be loaded from its own storage instead of the pooled literal, which
  changes the referenced symbol. Use a macro, or keep the literal with a comment.

Write a constant the way its author thought of it. Integer constant expressions fold to the same immediate, so
these are free:
- `20 * 1000` instead of `20000` for twenty seconds in milliseconds;
- `1 << GENTITYNUM_BITS` instead of `1024`;
- `MAX_GENTITIES - 1` instead of `1023`.

Expressions that change type are [checked]:
- `sizeof( table ) / sizeof( table[0] )` is a `size_t`, so comparing it with an `int` becomes an unsigned
  comparison;
- floating-point constant expressions such as `1.0f / 3.0f` may round differently from the written literal.

A literal whose meaning is plain from its line needs no name: `* 0.5f` for a half, `% 2` for odd and even, `+ 1`
for a terminator. A tuning value used once may stay inline with a comment, as the original engines often did.

### R31. Macros are hygienic and named for what they do. [free for new macros; checked for changes]

- **Parameters:** in a macro you reconstruct, parenthesize every use of every parameter, and parenthesize the
  whole expansion.
- **Names:** an upper-case name for a constant or a statement-like macro; the function style only for a macro
  that stands in for a function, as the original did (`VectorCopy`).
- **Macro or function:** keep the form the original had. A macro and a function that do the same thing compile
  differently, and engines sometimes kept both (`VectorCopy` and `_VectorCopy`).
- **Multi-statement macros:** wrap in `do { ... } while ( 0 )` only where the original's macro had that shape. In
  an unoptimized build the wrapper can emit a loop test.

Some original macros are unhygienic, and their call sites rely on it. Those keep their shape, labelled as an
original quirk (R36). Changing an existing macro is [checked].

---

## D. Structure

### R12. Functions live where the original put them. [evidence]

- **Methods:** a function the binary shows as a method (`this` register, vtable slot, mangled `Class::` name) is a
  method of that class.
- **Free functions:** a function the original wrote as free stays free, with its module's prefix (R28), declared
  in that module's header.
- **Statics:** use `static` only where the original function was local to its object.

Don't move functions into classes for style: it changes mangled and exported names.

### R13. Vtables are recovered from evidence. [match]

- **Slots:** every declared virtual is a slot in the binary's vtable, and every slot in the binary's vtable is
  declared. A slot whose purpose is unknown keeps a placeholder name: that is open naming work (R7), not a
  violation. Never declare a virtual the binary's vtable doesn't have.
- **Inheritance:** inherited slots are not redeclared. Mark overrides with a comment, or by repeating `virtual`,
  in C++98.
- **Count:** there is one vtable per polymorphic base. Single inheritance gives one vtable; multiple inheritance
  gives one for each polymorphic base.

A padded vtable can silently truncate the real one.

### R14. `goto` only where the original's control flow needs it. [checked]

Prefer structured flow. `goto` jumps to a labelled cleanup or retry point with a meaningful name: `fail`, `done`
or `retry`. A backward `goto retry` lands at the head of a block, never in the middle of a loop.

A shared `goto fail` exit compiles differently from nested returns, and it is a genuine idiom of the era. Write
it plainly where the bytes need it. Add a `RULE-EXCEPTION` only when sibling code or the module's style suggests
the original didn't use `goto`.

### R15. Keep the original's function order and unit boundaries. [checked]

- **Order:** within a unit, functions stay in the order the binary shows. Most old compilers emit non-COMDAT
  functions in source order. Some don't (Metrowerks moves inline and `static` functions), so check the project's
  compiler.
- **Units:** one source unit is one original object file. Don't split or merge units for tidiness; group with
  headers and section comments instead.
- **Folders** follow the original source tree where it is known.
- **`__FILE__`:** check that moving a file doesn't change an embedded path string.

### R16. Restore helpers instead of open-coding them. [checked]

When a statement reaches into another type's internals, or the same expression repeats across sites, restore the
accessor, inline helper or macro the original called, and convert every site.

❌
```cpp
if (t->levels[s] <= lvl && t->levels[s] != 0)
```

✅
```cpp
if (t->GetLevel(s) <= lvl && t->GetLevel(s) != 0)
```

**Evidence:** repetition is a hint, not proof. Restore a helper when one of these supports it:
- surviving or sibling source that has it;
- the same retail shape in several functions;
- an out-of-line copy of the helper in the binary.

This applies to inline helpers and macros. An out-of-line function that the binary doesn't call can't be
introduced (R34).

### R32. Each unit opens and is divided the same way. [free for comments; checked for order]

A reader skimming a unit should find its purpose, its data and its sections without reading code.

✅
```c
// g_combat.c -- damage, death and scoring

#include "g_local.h"

/*
================
AddScore

Adds score to the client and to its team
================
*/
void AddScore( gentity_t *ent, vec3_t origin, int score ) {
```

The unit is laid out in this order:
1. **A one-line purpose comment:** `// unit.c -- what this unit does`. Use `/* */` in a strict C89 dialect.
2. **Includes:** the module's local header first (or the precompiled header, if the original used one), then
   anything else the unit needs.
3. **Unit data:** file-scope types, statics and tables.
4. **Functions in binary order** (R15).

The comments and banners are [free]. Include order and data order are [checked]:
- include order decides which macros are visible;
- data order is layout (R2), so file-scope data sits where the binary's data order needs it, ideally before the
  first function that uses it.

Separate groups of related functions with a section banner (`/* ===== CVAR CALLBACKS ===== */`), in the profile's
form. Where the order the binary forces interleaves topics, the banners make that visible rather than hiding it.

### R33. Every function has a header comment. [free]

Put a header comment above each function definition. It names the function, then, when it isn't obvious, says
what the function does, its caller contract (what may be null, who owns what, which globals it changes) and
anything surprising. Use the profile's banner form. id's engines used this one for twenty years:

```cpp
/*
================
idEntity::BecomeActive

Activates the entity's thinking, physics or animation, according to flags.
================
*/
```

When the purpose is unknown, the banner holds the name only, or a `guess:` line. Never a confident invented
description (R7). A trivial accessor needs only the name, or nothing when the profile says so. Where one team of
the original used a different banner (Quake III's bot library writes `// Parameter: / Returns: / Changes
Globals:` boxes), follow that module's form (R8).

### R34. Don't split or merge functions for readability. [checked]

Function boundaries are the binary's. A function that was 250 lines in the original stays 250 lines (Quake III's
`G_Damage` is about that long). Splitting it changes call and inlining decisions, and merging two functions loses
one of them.

Make a long function readable from the inside:
- section comments over its phases (`// check for godmode`, `// apply knockback`);
- guard clauses that return early, where the bytes allow (R35);
- names for the locals it already has (R30).

### R35. Statements read top to bottom. [free for layout; checked for expression shape]

These are the defaults when the module's style is unknown. Where evidence of the original's style exists
(surviving source from the same team), R8 decides instead.

Layout, [free] (except under R23's line-number traps):
- **One statement per line.**
- **Braces on every block,** even single statements, and the statement on its own line. Braces never change the
  code, and they remove a whole class of misreadings.

Expression shape, [checked] because each can change codegen:
- **No hidden state changes.** Don't change state inside a larger expression where a separate statement says it
  plainly. `if ( ( x = Calc() ) == 0 )` reads better as `x = Calc();` then `if ( x == 0 )`.
- **Results get names.** Where a function's result is already kept in a local, give that local a name and test
  the name: `written = FS_Write( ... ); if ( written != len )`. A predicate whose name reads as a question may sit
  in a condition: `if ( IsMirror( surf ) )`. Don't add a local the original evidently didn't have.
- **Guard clauses** that return early instead of nesting the main path, where the bytes allow: `if ( !ent->inuse )
  { return; }`. A function with a shared cleanup exit keeps it (R14).
- **The comma operator** belongs in `for` headers only.
- **A multiple assignment** (`a = b = 0`) only for values that belong together.
- **`?:`** chooses between values, never between actions.

The exceptions are the era's own idioms, which the original programmers wrote constantly and every reader of C
knows:
- `*dst++ = *src++`;
- `while ( --count )`;
- `p = p->next` in a loop header;
- `if ( !( ent = G_Find( ... ) ) )` or `while ( ( ent = G_Find( ent, ... ) ) != NULL )` in a search.

When the bytes need such a form, write it plainly. It is not a fakematch, and it needs no exception. A contortion
no one would write is a fakematch (R17).

---

## E. Honesty of the source

### R17. No fake code. [match]

None of these may remain in a matched function:
- probes or unused declarations;
- dummy locals or `volatile` carriers;
- padding fields or members;
- arbitrary blocks, or statements that exist only to steer the compiler.

A permuter result is a clue to the original source, never source to copy. Section F lists fakematch patterns and
their human counterparts.

Code the binary contains is not fake, however odd it is. Duplicated statements, dead stores and bugs that the
original shipped stay in, labelled with R36. These are genuine too:
- `volatile` on hardware registers and on data shared with interrupt handlers;
- locals used only in debug builds;
- reserved fields that the SDK or file format names.

### R18. Assembly is not source. [match]

A function whose body is inline or pasted assembly (`__asm`, `asm()`, `INCLUDE_ASM`, emitted bytes) is "verbatim",
not matched. Two exceptions:
- **Original helpers.** An inline-asm helper that the evidence shows the original had, such as an `imul`
  high-word helper, is allowed inside otherwise-C functions. Those functions are listed, but counted.
- **Original assembly.** A function the evidence shows was written in assembly (a `.s` unit, a naked function
  with hand-scheduled code, a vendor library object) is reported as `ORIGINAL-ASM`. It is listed on its own and
  left out of both the matched count and the total.

### R19. Use casts only where the meaning needs them. [free for arithmetic casts; checked for pointer casts]

A cast is a symptom: retype the member or parameter instead. Don't cast where an assignment converts implicitly
(`int` to `float`, `void *` to a typed pointer in C). Cast where the meaning needs it:
- true division of integers;
- a deliberate truncation;
- the `void *` boundary of R26;
- passing an object as a callback cookie.

At a real boundary, use a named cast in C++ and a plain C cast in C. Changing a pointer cast is [checked]:
- a C-style cast on an incomplete class acts as `reinterpret_cast`, while `static_cast` applies the
  multiple-inheritance pointer adjustment;
- varargs and unprototyped calls depend on casts for their promotions.

### R20. Keep `const` and references as the evidence shows them. [evidence]

Both change mangling and can change temporaries and evaluation order. In C, where `const` is not mangled, add it
to pointer parameters the function never writes through: it documents the contract. Check it like any change.
Never add `const` to file-scope data without a layout check: it moves the data to the read-only section.

### R21. Comments say what the code means, and why the bytes need it. [free]

Comments are for:
- annotations;
- ABI or codegen constraints;
- evidence for names and types;
- `RULE-EXCEPTION` notes;
- `guess:` markers;
- **why**: the purpose of a block, a unit or a range, when the code alone doesn't say;
- the original's quirks (R36).

Don't restate the code (`i++; // increment i`). No history, scores, dates or campaign notes; those belong in
version control. No addresses in comments, except the annotation format and unknown-member offsets (R27).

An include whose use isn't obvious from its name may carry a trailing comment listing what the unit takes from
it: `#include "be_aas_def.h" // aas_t, aasworld`. Keep it accurate or leave it out.

### R22. Write the compiler's dialect only. [free]

Write only what the original compiler accepts, and know its quirks. Examples:
- **VC6 `for` scope:** a variable declared in a `for` header stays in scope after the loop. A second
  `for ( int i ...)` in the same scope is an error, and `i` stays visible after the loop.
- **C89:** declarations at the top of a block, and `/* */` comments only when the compiler is strict.
- **Before C++11:** no `nullptr`, `auto` or `enum class`.
- **Before C99:** no `stdint.h`, `stdbool.h` or `for`-loop declarations. Designated initializers, compound
  literals and variable-length arrays depend on the compiler: GCC 2.95 accepts them as extensions, VC6 doesn't.
- **Trailing commas** after the last enumerator: avoid them where the compiler warns or errors.

The project profile lists what its compiler accepts and rejects.

### R23. Formatting is free, but it gets its own commits. [free, with two traps]

The profile fixes one layout per module (R8):
- brace placement;
- indent;
- spacing inside parentheses;
- line limit (79 columns if the profile says nothing);
- banner forms.

Separate functions with one or two blank lines, and allow at most one blank line inside a function.

Two traps make layout changes [checked]:
- **`__LINE__`.** In a unit that uses `assert`, an allocator tag or an error macro that embeds the line number,
  adding or removing lines changes those constants.
- **Line information.** When the retail binary or its debug data records source lines (debug builds, `-g`
  builds, SN Systems symbol files), moving statements between lines changes that data.

Run the unit's byte gate once per batch of formatting changes, even when every change is [free].

### R24. Never edit generated or prebuilt material. [free]

Build output, progress reports, disassembler exports and prebuilt library objects are outputs: regenerate them.

### R36. Label the original's quirks; don't fix them. [free]

The goal is to understand the program as it shipped, including its mistakes. When the binary contains something
odd, keep it and say so in a comment:
- a bug: `// BUG: original compares the wrong team`;
- a redundant statement: `// NOTE: original frees muzzleFlashHandle twice`;
- an unused result;
- a dead store;
- an unreachable branch;
- an unhygienic macro.

Don't silently "fix" it, and don't remove it as fake code (R17).

R36 is not a loophole. A quirk label claims the original had this code, so it needs bytes that simpler source
can't explain. A plausible correct version must have been tried and must not match. When the claim is uncertain,
write `guess:` instead of `BUG:`. A quirk label on a steering trick is still a fakematch.

### R37. Conditional compilation models real builds only. [checked]

Use `#if` / `#ifdef` only for build variants the original had (a mission pack, debug, a platform), written as the
original condition. Never use them to park alternative reconstructions, failed attempts or code "kept for
reference": those belong in version control. A block that no build compiles is not source.

The project's own parking mechanism, defined in its profile (for example `#ifdef NON_MATCHING` around an
unfinished function), is exempt. It marks work in progress, not finished source.

---

## F. Fakematches and human idioms

A fakematch hides the original's meaning behind a trick that steers the compiler. Each row is a symptom: the fix is
to find what the original programmer actually wrote. These are usually a missing helper (R16), a wrong type (R6),
a wrong declaration order or scope (R30) or a missing inline function.

| fakematch | what it usually hides | the human form |
|---|---|---|
| `volatile` on a local, or on ordinary data, to force a load or store | wrong type, an aliasing pointer, or a missing call | the real type or pointer; the original helper |
| a dummy local assigned and never read, or read only to burn a register | a value the original kept for later use; a missing inline helper | the meaning-bearing variable, or the helper |
| an empty `{ }` block or a bare `;` statement | a scoped local, a macro's expansion, a removed debug call | the real block or macro; a debug macro that compiles to nothing |
| `do { ... } while ( 0 )` in a function body | a macro the original called | the macro (R31) |
| `if ( x ) { }`, `if ( 0 )`, `x = x;`, `x + 0`, `x * 1`, `!!x` | a sequence point, a type width, a missing helper or inline | the real expression |
| one variable reused for unrelated values | separate variables sharing a slot | one local per meaning (R30) |
| arithmetic on `(char *)p + N` | a struct member | a typed member (R4) |
| a cast to the same type, or a cast chain | a wrong declared type | the right declared type (R19) |
| a comma-operator chain, or an assignment hidden in an argument, that only reorders evaluation | a different statement order, or a helper with that order inside | the statements in the original's order |
| a temporary with no meaning (`tmp`, `t1`) that exists only to split an expression for the compiler | an intermediate value with a meaning, or an inlined accessor | a named intermediate (R30) or the accessor (R16) |
| `register` on a few locals chosen to steer allocation, in a codebase that doesn't otherwise use it | a different declaration order or type | the original declaration order. `register` itself is genuine where the codebase uses it and the compiler honours it (GCC at `-O0`, IDO) |
| a padding member that pushes known members into place, a padding virtual, or an array sized to steer layout | unknown members, or a wrong base class | placeholder members named by offset (R27), the real hierarchy (R13) |
| `goto` into the middle of a loop, or a label used only to reorder blocks | a `continue`, a `do`/`while` shape, a different condition | the structured loop |

Patterns that look dense to a modern eye, and are human:
- `*dst++ = *src++`, `while ( --n )`, `for ( ; *s; s++ )`, `while ( *s++ ) ;`;
- `if ( !( p = Find() ) )` in a search;
- `goto fail` with one cleanup label;
- a long function with a long `switch`;
- the same check written twice, because the original had a bug or a merge leftover (R36);
- `x = y = 0` for related state;
- a macro used where a modern codebase would use an inline function;
- braceless one-line `if`s in a module whose surviving source writes them (R8).

---

## Making [match] mechanical

A project's rule checker runs over the source of every matched function and reports one line per finding. It
lists the violated rules, so matches with violations become `MATCH-PENDING` (by function and unit). A [match] rule
blocks a match only where its row here fires. Each row is narrow enough not to flag real code.

| rule | how the checker tests it |
|---|---|
| R1 | the same type name defined in two files with different bodies; a struct whose fields copy a prefix of another struct's fields **and** that is accessed through a cast to or from that struct; a `class`/`struct` keyword mismatch |
| R2 | an `extern` of a global outside its header, unless the profile relaxes this; one global declared with different types |
| R4 | a constant offset added to a `(char *)` / `(BYTE *)` cast, followed by a dereference cast; `this` used in such arithmetic; offset macros outside `offsetof` field tables |
| R13 | a declared virtual with no matching slot in the binary's vtable (the project's vtable data drives this); virtuals named `pad`/`dummy` |
| R17 | `volatile` on locals, or on members and globals without a `// volatile: <evidence>` note; locals unused in every `#if` branch, unless marked R36; statements marked as probes; empty `if`/`else` blocks and bare `;` statements (empty loop bodies, `case X: ;` and `label: ;` are allowed); `do { } while ( 0 )` outside a macro; self-assignment; the token-bounded literals `+ 0` and `* 1`; padding members (`pad\d*`, `_pad`) not named by the SDK or file format |
| R18 | the inline-assembly tokens of the dialect, outside `ORIGINAL-ASM` functions and listed helpers |

Progress then reports both numbers: **bytes matched** and **matched under the rules** (bytes matched, and every
[match] rule passing). The second is the project's headline figure. `ORIGINAL-ASM` functions are listed
separately and left out of both.

The checker also reports advisory findings that don't block a match:
- **Open naming (R7):** the profile's placeholder regexes, and address-like identifiers, in the function, its
  locals and parameters, and the globals, types and members it references. An address-like identifier is a
  whole-word hex run of six to eight characters that contains a digit, alone or after a prefix and an optional
  underscore. The regex is `\b[A-Za-z_]*?_?(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{6,8}\b`. Requiring a digit avoids
  `defaced`; the profile may whitelist names like `COLOR_FF0000`.
- **Readability:**
  - functions without a header comment (R33);
  - `if`/`else`/loop bodies without braces (R35), where the profile doesn't record braceless style;
  - assignments inside conditions outside the idioms of R35;
  - local `extern` declarations (R25);
  - `#if 0` blocks (R37);
  - pointers typed `void *` or `int` only to dodge the real type (R4);
  - `!!x` and casts to the variable's own type (Section F), which are sometimes human and need a look.
