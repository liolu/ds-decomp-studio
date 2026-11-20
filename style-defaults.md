# Default style tables

Use these only when the project has **no evidence** of the original's own style: no surviving source, SDK or
sibling code from the same studio. Evidence always wins (R7, R8). Copy the table that fits the dialect into the
project profile, change what the evidence contradicts, and record the choice.

Both tables come from id Software's released engines. These are long-lived, widely read codebases whose
conventions held over many years and many programmers:
- **Table 1**, the C style, is Quake III Arena's, with classic DOOM noted where it differs.
- **Table 2**, the C++ style, is DOOM 3 BFG's (id Tech 4).

Each convention is one that a reader of 1990s and 2000s game code will recognise.

Every entry below is [free] when applied to a name that doesn't reach the bytes. A name reaches the bytes through
exports, RTTI, mangled names, stringizing macros such as `assert`, `__FUNCTION__` or debug information. Such
names keep their recorded spelling (R7).

## Table 1: C engine (Quake III style)

| entity | style | examples |
|---|---|---|
| unit | `prefix_topic.c` | `g_combat.c`, `tr_main.c`, `cl_parse.c` |
| module headers | `prefix_public.h` between modules, `prefix_local.h` inside one | `g_public.h`, `g_local.h`, `tr_local.h` |
| global function | `Prefix_VerbNoun` | `G_Damage`, `FS_ReadFile`, `Cvar_Get`, `R_AddDrawSurf` |
| static function | as global, or plain `VerbNoun` | `PM_Friction`, `SetFarClip` |
| command handler | `Prefix_Verb_f` | `Cmd_Wait_f`, `CL_Record_f` |
| callback | role prefix or suffix | `Think_SpawnNewDoorTrigger`, `Touch_Item`, `player_die` |
| struct type | `lowerCamel_t`, tag `lowerCamel_s` when self-referencing | `gentity_t` / `struct gentity_s`, `trace_t` |
| enum type | `typedef enum { ... } lowerCamel_t;` | `gametype_t`, `moverState_t` |
| enum value | `PREFIX_NAME`, count last | `GT_FFA` … `GT_MAX_GAME_TYPE`, `MOVER_POS1` |
| constant | `UPPER_SNAKE` `#define` or enum (in C a `const int` is an object, not a constant: R11) | `MAX_GENTITIES`, `FRAMETIME`, `ENTITYNUM_NONE` |
| flag group | owner prefix, hex, one block under `// owner->field` | `FL_GODMODE 0x00000010`, `SVF_NOCLIENT` |
| function-like macro | function style if it stands in for a function, else upper | `VectorCopy`, `ANGLE2SHORT` |
| boolean | `qboolean` (`qtrue`/`qfalse`), named for the state | `inuse`, `spawning`, `readyToExit` |
| struct member | `lowerCamel` | `nextthink`, `takedamage`, `startTime` |
| local, parameter | short `lowerCamel`; conventional names | `i`, `j`, `ent`, `self`, `other`, `cl`, `ps`, `tr`, `dir` |
| subsystem state | one struct, one short global, lifetime in a comment | `level` (cleared each map), `cls` (persists), `tr` |
| console variable | variable named as its console string | `vmCvar_t g_gravity;` for `"g_gravity"` |
| debug counter | `c_` prefix | `c_pmove`, `c_gridVerts` |

Layout:

| item | style |
|---|---|
| unit opening | `// prefix_topic.c -- purpose` (`/* */` under a strict C89 compiler such as IDO) |
| function banner | `/*` `=====` `Name` *description* `=====` `*/` |
| section banner | the same box with an upper-case title (`COMMAND BUFFER`) |
| braces | K&R, `if ( cond ) {` with spaces inside the parentheses |
| local declarations | C89, at the top of the block, aligned in columns |
| error handling | `Com_Error( ERR_DROP, "FuncName: what failed" )`; the message starts with the function name |

**Classic DOOM differs:**
- one-letter prefixes (`P_SpawnMobj`, `R_`, `S_`, `Z_Malloc`);
- `// P_SpawnMobj` line-comment banners;
- lower-case run-together names (`floorz`, `reactiontime`);
- `#define` constants such as `FRACUNIT`;
- the return type on its own line above the name.

## Table 2: C++ engine (id Tech 4 style)

| entity | style | examples |
|---|---|---|
| unit | `ClassName.cpp` / `ClassName.h`, one main class each | `Entity.cpp`, `Weapon.h` |
| interface and implementation | `idFoo` (pure virtual, in `Foo.h`) and `idFooLocal` (in `Foo_local.h`) | `idCommon` / `idCommonLocal` |
| singleton | concrete object plus an interface pointer, both `lowerCamel` | `idGameLocal gameLocal; idGame *game = &gameLocal;` |
| class | `idPascalCase` (the project's class marker) | `idEntity`, `idPlayer`, `idStr` |
| plain-data struct | `lowerCamel_t` | `drawSurf_t`, `renderView_t` |
| method | `PascalCase`, verb first | `Think`, `BecomeActive`, `UpdateVisuals` |
| accessor | `Get`/`Set`, `Is`/`Has`, `Num` | `GetEntityNumber`, `IsHidden`, `Num` |
| event handler | `Event_Name` (private, last in the class) | `Event_Hide`, `Event_Activate` |
| internal helper | `Internal` or `Parse` prefix | `InternalSetString`, `ParseStage` |
| member | `lowerCamel`, no `m_` prefix | `entityNumber`, `spawnArgs`, `teamMaster` |
| boolean flags | bitfield struct `fl` | `fl.hidden`, `fl.neverDormant` |
| enum type | `lowerCamel_t` | `moveType_t`, `cvarFlags_t` |
| enum value | `PREFIX_NAME`, count last | `MOVETYPE_ANIM` … `NUM_MOVETYPES` |
| constant | `UPPER_SNAKE` `const` at the top of the unit or in the header, with a comment | `const int WEAPON_DROP_TIME = 20 * 1000;` |
| global | `lowerCamel`, no prefix | `common`, `cvarSystem`, `gameLocal` |
| console variable | `idCVar` object named as its string | `idCVar g_muzzleFlash( "g_muzzleFlash", ... );` |
| parameter shadowing a member | trailing underscore | `SetMemTag( memTag_t tag_ )` |

Layout:
- Function banner: `/*` `=====` `Class::Method` *description* `=====` `*/`.
- A header puts trivial accessors in the class and longer inline methods after the class.
- Class sections: `public:` first, with methods grouped under `// thinking`, `// rendering` comments; then
  `protected:`, then `private:`.

## Picking between them, and what not to borrow

- **Pick by dialect.** Choose by the original's language and era, not by taste.
- **One prefix scheme per module.** A C++ codebase with C modules (id Tech 4 kept classic DOOM as C-style code)
  keeps each module's own table (R8).
- **Modern style guides** are useful for layout and hygiene, but much of their content conflicts with matching or
  with the old dialects:
  - a two-return limit, a `default` in every switch, null checks before every dereference, nulling pointers after
    `free`, and init functions instead of global initializers all add or reshape code;
  - `for`-loop declarations, `stdint.h` and `stdbool.h` don't exist before C99. Designated initializers and
    compound literals work only on some old compilers (GCC 2.95 yes, VC6 no): see the profile.

  Borrow the layout and hygiene; never borrow a rule that changes what the code does.
