# Code rules: source that matches and reads like the original

These rules apply to the C and C++ written in every game of the studio (`projets/<game>/src`, `include`). The
project profile (compiler dialect, names, layout, commands, the rules this studio changes) is in
[AGENTS.md](AGENTS.md#code-rules-profile). The checker is `gametools/coderules.py` (`tools/coderules.py` in a game).

## The reader test

A matching decompilation exists so people can understand the original program. Identical bytes prove the source is
faithful; readable source is the point. Every rule serves one test:

> Would a programmer on the original team, writing in that codebase's style and dialect, have typed this?
> And can a reader see what it does, and why, without opening the disassembly?

A **fakematch** gets the right bytes and fails this test: a dummy temporary, a `volatile` carrier, an empty block, a
reused variable, an offset cast, a statement that only steers the compiler. It is a clue to the real source, not a
match. The era's own idioms pass, however dense: `*dst++ = *src++`, `while (--count)`, `goto fail` cleanup, a long
function, a bug the original shipped.

## The two laws

1. **The bytes win.** A change made for style never changes what the compiler emits. When a rule and the bytes
   disagree, keep the bytes and write `// RULE-EXCEPTION: <rule>, <reason the bytes give>` at the code. An exception
   bends a style rule; it never licenses fake code.
2. **Identical bytes alone are not a match.** A function counts as matched only when its bytes match and it passes
   every **[match]** rule (R1, R2, R4, R13, R17, R18). Byte-identical but failing is `MATCH-PENDING`: reported, kept
   in the game (the ROM needs it), and not counted. A function the original wrote in assembly is `ORIGINAL-ASM`:
   listed apart and counted neither way. Names are not required: placeholder names are open work, not a failed match.

Progress therefore has two numbers: **bytes matched** and **matched under the rules**. The second is the headline.

## Tiers

| tag | before applying |
|---|---|
| [free] | nothing: it cannot change the output (traps: `__LINE__`, and names that reach strings or RTTI) |
| [checked] | `workbench.py judge` on the function, then the byte gate (`match.py verify`) |
| [evidence] | evidence for the name or signature: a public decompilation, an SDK name found by fingerprint, a string |
| [match] | required before the function counts; also [checked] when you fix it |

## The rules

Rule numbers are stable identifiers shared with other projects; they are grouped by topic, not in reading order.

**A. Declarations and types**

| rule | tier | |
|---|---|---|
| R1 | match | Each type is declared once, in a shared header. No local copy, no partial "view" of another struct, no `class`/`struct` mismatch. A type only one unit uses may stay at the top of that unit. |
| R2 | match | Each global is declared once, `extern` in a header, and defined once in the unit that owns its address. |
| R3 | free / checked | Headers have a fixed shape: guard, includes, constants, enums and typedefs, structs, externs, prototypes grouped by the unit that defines them. |
| R4 | match | Typed members, never fixed offsets: no `M2C_FIELD`, no `*(T *)((u8 *)p + K)`, no virtual call through `*(u8 **)p + K`. Byte arithmetic is fine where the data has no fixed struct (file parsers). |
| R5 | evidence | An enum for a proven finite set of values. |
| R6 | evidence | The original's own types and APIs (NitroSDK `u8`/`s32`/`BOOL`/`fx32`, its structs); `bool` only where the evidence shows it. |
| R25 | checked | Every called function has a prototype in scope, in a header, with its real types. |
| R26 | checked | Pointers stay typed; `void *` only at a real boundary (callbacks, allocators). |
| R27 | free / checked | Structs read as documentation: one member per line, comments for units and owners. Unknown members are named by offset (`unk_58`), never by an invented name. |

**B. Names**

| rule | tier | |
|---|---|---|
| R7 | checked / evidence | Names say what things mean. Placeholders (`func_02001234`, `data_...`, `arg0`, `temp_r4`, `M2C_UNK`) are reported as open naming work. Recorded names are kept verbatim; an unknown purpose keeps its placeholder. |
| R8 | free | The original codebase's naming style, module by module. |
| R28 | checked | Free functions carry their module's prefix (`OS_`, `GX_`, `NNS_Snd`). |
| R29 | free | One naming pattern per kind of thing: types, enum values, constants, flags, accessors. |
| R30 | checked | One local, one meaning, one name: split a variable the decompiler merged. |

**C. Literals and operations**

| rule | tier | |
|---|---|---|
| R9 | free / checked | Decimal for counts and sizes, hex for masks and registers; never a float as raw bits. |
| R10 | checked | Bit operations keep their shape and get names (flag constants, packing macros). |
| R11 | free / checked | Meaningful constants are named (`#define` or enum in C). |
| R31 | free / checked | Macros are hygienic and named for what they do; an original macro keeps its form. |

**D. Structure**

| rule | tier | |
|---|---|---|
| R12 | evidence | Functions live where the original put them: methods stay methods, `static` only where the original was. |
| R13 | match | Vtables come from evidence: every declared virtual is a real slot, no padding virtuals. |
| R14 | checked | `goto` only where the original's control flow needs it. |
| R15 | checked | The original's function order and unit boundaries: one source file, one original object file. |
| R16 | checked | Restore the helper, accessor or macro instead of open-coding it, when evidence supports it. |
| R32 | free / checked | Each unit opens the same way: purpose comment, includes, unit data, functions in binary order. |
| R33 | free | Every function has a header comment; an unknown purpose gets the name only, or a `guess:` line. |
| R34 | checked | Functions are never split or merged for readability. |
| R35 | free / checked | Statements read top to bottom: one per line, braces, no hidden state changes outside the era's idioms. |

**E. Honesty of the source**

| rule | tier | |
|---|---|---|
| R17 | match | No fake code: no probes, dummy or unused locals, `volatile` carriers, padding members, statements that only steer the compiler. |
| R18 | match | Assembly is not source: an `asm` body is "verbatim", not matched, unless the function is `ORIGINAL-ASM`. |
| R19 | free / checked | Casts only where the meaning needs them: retype the member or parameter instead. |
| R20 | evidence | `const` and references as the evidence shows them. |
| R21 | free | Comments say what the code means and why the bytes need it. No history, scores or addresses. |
| R22 | free | Only what the original compiler accepts. |
| R23 | free | Formatting is free, in its own commits. Run the byte gate once per batch anyway. |
| R24 | free | Never edit generated or prebuilt material: regenerate it. |
| R36 | free | Label the original's quirks (`// BUG:`, `// NOTE:`); do not fix them and do not remove them as fake code. |
| R37 | checked | `#if` only for build variants the original had; never to park alternative attempts. |

## Fakematches, and what they usually hide

| fakematch | what it usually hides |
|---|---|
| `volatile` on a local, a parameter or ordinary data | a wrong type, an aliasing pointer, varargs or a struct passed by value, a missing call |
| a dummy local, an unused leading parameter (`hunt_pad`) | a value the original kept, a missing argument, a method's `this` |
| an empty block, a bare `;`, `do { } while (0)` | a scoped local, a macro the original called, a removed debug call |
| `if (x) { }`, `x = x;`, `x + 0`, `x * 1`, `!!x` | a sequence point, a type width, a missing inline helper |
| one variable reused for unrelated values | separate variables sharing a slot (R30) |
| `(u8 *)p + K`, `M2C_FIELD`, an `extern` array plus casts | a struct member (R4) |
| a temporary with no meaning that splits an expression (`hunt_t`) | a named intermediate, or an inlined accessor (R16) |
| `goto` into a loop, a label that only reorders blocks | a `continue`, a `do`/`while` shape, a different condition |

A permuter or mutation result that matches through one of these is a diagnosis. Keep it out of the count, and look for
the source it points to.

## What the checker tests

A [match] rule blocks a match exactly where its row fires. The rows are narrow on purpose, so genuine code passes.

| rule | row |
|---|---|
| R1 | the same type name defined in two files with different bodies; a `class`/`struct` keyword mismatch |
| R2 | an `extern` of a global outside a header; one global declared with different types |
| R4 | `M2C_FIELD`; a constant added to a byte-pointer cast and dereferenced through a cast; a virtual call through a vtable offset; offset arithmetic on `this` |
| R13 | virtuals named `pad`/`dummy` (slot counts against the binary's vtables are not checked yet) |
| R17 | `volatile` on a local or parameter, or on a member or global without a `// volatile: <evidence>` note (lines that name a `0x04xxxxxx` register pass); the search tools' probes (`hunt_*`, `arg_pad`); locals never used; empty `if`/`else`; bare `;` (empty loop bodies, `case X: ;`, `label: ;` pass); `do { } while (0)` outside a macro; self-assignment; `+ 0`, `* 1`; members named `pad*` without a `// reserved: <SDK or format name>` note |
| R18 | an `asm` body, unless the function is in the game's `config/asm_allowed.txt` or carries an `// ASM: <public decompilation>` citation |

A statement the original really had (an unused local that keeps a stack slot, a store written twice) passes R17 with
an `// R36: <what the bytes show>` note on its line, after a plain version was tried and did not match.

Advisory findings never block a match: placeholder names (R7), prototypes outside a header (R25), functions without
a header comment (R33), `#if 0` (R37), assignments inside conditions (R35), byte-pointer arithmetic that is not
dereferenced (R4), `goto` (R14), `!!x`.

```shell
python tools/coderules.py                # this game: both numbers, build/coderules/report.json
python tools/coderules.py --pending      # the MATCH-PENDING functions and the rules that hold them
python tools/coderules.py --advisory src/nitro/os/os_alloc.c
```

## Cleaning up existing source

1. Run the checker. Fix in tiers: [free] fixes first, in their own commit; then each [checked] or [evidence] fix with
   `workbench.py judge` and `match.py verify`. Never mix formatting with code changes.
2. A fix that breaks a match is reverted or reshaped, never kept. A rule the bytes defeat gets a `RULE-EXCEPTION`.
3. Report the [match] violations fixed and the functions they moved from `MATCH-PENDING` to matched, the fakematches
   found, the exceptions recorded, and what is still open.

## Changing the rules

A game or the studio may tighten or relax a rule in its `AGENTS.md`, with the reason. A rule moves into [match] only
if it can be checked mechanically, and the checker changes in the same commit. Rule numbers never change.
