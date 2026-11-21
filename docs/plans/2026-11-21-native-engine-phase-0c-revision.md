---
type: task
tags: [native-engine, cpp, duckdb, sqlearn, migration]
summary: "Implementation plan revising ADRs, CLAUDE.md, architecture pages and plan 0b so sqlearn becomes a C++ library embedding DuckDB, with Python as thin bindings."
related: [docs/specs/native-engine.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/adr/0063-the-engines-compute-libraries.md, docs/adr/0065-safety-rules-for-the-cpp.md, docs/adr/0067-how-computation-moves-to-the-engine.md, docs/adr/0068-sqlearns-own-models.md, docs/adr/index.md]
mdindex: [type=edb465, tags=e2bb43, summary=551698, related=771647]
---
# Native engine, Phase 0c: the revision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** bring the ADRs, `CLAUDE.md`, the architecture pages, plan 0b and
the phase issues into line with the revised spec: sqlearn becomes a C++
library embedding DuckDB, and Python becomes its thin bindings.

**Architecture:** documentation only. ADRs 0060 and 0067 are rewritten in
place (neither has reached `main`); ADRs 0061, 0065 and 0068 gain what the
revision added; the pages that cite them follow; plan 0b's remaining tasks
are revised before they run; three GitHub issues are retitled.

**Tech Stack:** Markdown (MyST on Sphinx), `just`, `gh`.

**Spec:** `docs/specs/native-engine.md`, revised and approved by Tomas on
2026-11-21: §1, §2, §3.1, §3.2 ("One DuckDB in the process"), §3.4 (Mojo),
§3.6 (C++ tests), §3.8, §4, §5.2, §5.3, §5.5. Phase 0's issue is #78. Plans
0a (done) and 0b (Tasks 1 and 2 under way) run on the same branch.

## Global Constraints

- Plan 0a's Global Constraints hold, except where this list says otherwise:
  the branch `engine-phase-0` in `.worktrees/engine-phase-0`; `just` and
  `uv run`; British English in prose, American spelling in identifiers; the
  ADRs' house style (`# NNNN: Title`, `Status:`, `## Context`,
  `## Decision`, `## Consequences`); an ADR records what the spec decided
  and nothing more, every Decision bullet tracing to the spec, "the agent's
  call" kept marked so; no reason the spec does not give; Conventional
  Commits with `(#78)`, no scope, lines at most 72 characters, no AI
  attribution, never `--no-verify`, never a bare `git stash`; stage only the
  task's files and read `git diff --cached` first; the docs tagger's edits
  to existing files stay out of commits.
- **ADRs 0060, 0061, 0063, 0065, 0067 and 0068 are not on `main`,** so this plan
  edits their bodies, which 0a's rule for accepted ADRs forbids. Each keeps
  its file name (links stay whole) and gets one sentence at the end of its
  Status paragraph: `Revised before merging (2026-11-21), with the spec's
  revision: <clause>.`
- `CLAUDE.md`'s rules change in the same commit as the ADR behind them, with
  the exact wording given here.
- Before every commit: `just fmt`, `just check`, `just test` (once, in the
  foreground; no background runs, no wait loops, no kills), and
  `just build-docs`. Name every failure.
- Tomas's words are paraphrased in house style and credited "(Tomas,
  2026-11-21)", as the spec does; never quoted from chat, except the spec's
  own quotations.

## Review Focus

1. **A stale sentence left behind.** "Python stays the API", "Python reaches
   it only through SQL", "No pybind11 or nanobind layer", "the pipeline
   compiler in C++ ... only when a non-Python client needs it", "how
   computation moves", "moves / stays / later", or models "in Phase 4",
   surviving anywhere outside the spec's Considered lists and the plans of
   0a. Each task greps its own files for these.
2. **A decision the spec does not make**, written into an ADR: for example
   choosing one package over two, a C++ test framework, or a port order the
   inventory has not set.
3. **A broken link** from a retitled ADR: file names do not change, but
   `docs/adr/index.md`'s titles do.
4. **The GitHub issues and the spec disagreeing** on phase numbers.
5. **`CLAUDE.md` rules contradicting each other** after the edit (the
   computation rule, the DuckDB-build rule and the port rule).

### Task 0: Commit the spec and this plan

- [ ] The controller commits `docs/specs/native-engine.md` (revised) and this
  plan, after `just fmt`, `just check`, `just test`, `just build-docs`:
  `docs: revise the native engine: all of sqlearn in C++ (#78)`.

---

### Task 1: ADR 0060, sqlearn is a C++ library

**Files:**
- Modify: `docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md`,
  `docs/adr/index.md` (0060's title), `CLAUDE.md` (the computation rule),
  `GLOSSARY.md` (the engine's entries, lines 50 to 70)

- [ ] **Step 1: Rewrite ADR 0060** from spec §3.1 and §1, keeping the file
  name and the Status paragraph, with the revision sentence's clause:
  "sqlearn becomes a C++ library embedding DuckDB, and Python its
  bindings". The title becomes `# 0060: sqlearn is a C++ library, and
  Python its bindings`. Context: today's size (74 modules, about 31,500
  lines, 27,400 lines of tests) and Tomas's three reasons. Decision: every
  bullet of §3.1 (the C++ library and its kernels, nanobind and why, the
  seam to Python steps and users' own steps, other languages through a C
  layer when wanted, the internal C++ API, `sqlearn_` names, `engine/`,
  speed first with plain-SQL twins, the 0002 amendment). Considered: §3.1's
  list. Consequences: the port (ADR 0067), one DuckDB in the process (ADR
  0061), Phase 1 builds the bindings.
- [ ] **Step 2: `docs/adr/index.md`:** 0060's line reads `- [0060: sqlearn
  is a C++ library, and Python its
  bindings](0060-a-native-engine-in-cpp-inside-duckdb.md)`.
- [ ] **Step 3: `CLAUDE.md`.** Replace the rule beginning "Computation runs
  inside DuckDB: SQL, and the native engine's C++ functions" with these two:

  ```markdown
  - sqlearn is a C++ library embedding DuckDB. Python is thin nanobind
    bindings with no logic of their own; users' own steps stay writable in
    Python. Other languages bind later, through a C layer when they need
    one. The C++ API is internal: only `sq.` is public (0060).
  - Computation runs inside DuckDB: the SQL the library builds, and
    sqlearn's C++ functions (`sqlearn_*`) registered in it (0002, 0060).
    Apply SQL may call them where a benchmark shows it faster; each keeps a
    plain-SQL twin where one exists. Until the engine's Phase 2, a Gram
    step's learn sums XᵀX in numpy from batches DuckDB streams (0058, 0067).
  ```
- [ ] **Step 4: `GLOSSARY.md`.** The engine's entry no longer says "the
  `sqlearn` extension": the engine is sqlearn's C++ library with its
  kernels. Add **sqlearn's C++ library** and **the bindings**, defined as in
  spec §3.1, citing ADR 0060.
- [ ] **Step 5: Grep** these four files for Review Focus 1's phrases; none
  remains outside a Considered list. `just fmt`, `just check`, `just test`,
  `just build-docs` pass. Commit `docs: ADR 0060 makes sqlearn a C++ library
  (#78)`.

### Task 2: ADR 0067, the port

**Files:**
- Modify: `docs/adr/0067-how-computation-moves-to-the-engine.md`,
  `docs/adr/index.md` (0067's title), `CLAUDE.md` (the migration rule)

- [ ] **Step 1: Rewrite ADR 0067** from spec §3.8 and §4's "order of work",
  keeping the file name and Status, with the revision clause "the whole
  library is ported, not only its computation". Title: `# 0067: The library
  is ported to C++ piece by piece`. Decision: every bullet of §3.8 (bindings
  from the start with `main` green, Tomas's choice over bindings at the end;
  the public tests and the validation as the contract; tests of internals,
  the agent's call; a piece is an inventory group, the agent's call, with
  the "not slower" rule; saving kept exactly, with its security review; the
  order from the inventory; what stays Python; measuring honestly) and the
  order of work (the port before any new area; the three small fixes
  first). Considered: bindings at the end.
- [ ] **Step 2: `docs/adr/index.md`:** 0067's line reads `- [0067: The
  library is ported to C++ piece by
  piece](0067-how-computation-moves-to-the-engine.md)`.
- [ ] **Step 3: `CLAUDE.md`.** Replace the rule beginning "Computation moves
  to the engine piece by piece" with:

  ```markdown
  - The library is ported to C++ one inventory group at a time, with `main`
    green: the Python package calls the C++ for each group ported and its
    own Python for the rest. A group merges when the public API's tests and
    the validation pass unchanged against the C++ and its benchmark is not
    slower; then its Python is deleted, and the tests of its internals are
    rewritten against `sq.` or in C++. A test of the public API changes
    only with an ADR (0067).
  ```
- [ ] **Step 4: Grep** the three files for Review Focus 1's phrases. Checks
  as in Task 1. Commit `docs: ADR 0067 ports the whole library to C++
  (#78)`.

### Task 3: ADRs 0061, 0063, 0065, 0068 and the architecture pages

**Files:**
- Modify: `docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md`,
  `docs/adr/0063-the-engines-compute-libraries.md`,
  `docs/adr/0065-safety-rules-for-the-cpp.md`,
  `docs/adr/0068-sqlearns-own-models.md`, `CLAUDE.md` (the DuckDB-build
  rule), `docs/architecture/overview.md`, `docs/architecture/layout.md`

- [ ] **Step 1: ADR 0061** gains spec §3.2's "One DuckDB in the process"
  as a Decision bullet, and its second-package bullet's reason becomes the
  spec's ("a change to sqlearn then ships without rebuilding DuckDB"), with
  two packages as the default that Phase 1 may make one. Revision clause:
  "one DuckDB in the process, shared with the C++ library".
- [ ] **Step 1b: ADR 0063** gains spec §3.4's Mojo bullet as written there
  (tried beside Metal in Phase 6; the language of the GPU kernels if it
  matches Metal, with its five conditions). Clause: "Mojo
  tried beside Metal".
- [ ] **Step 2: ADR 0065** gains spec §3.6's "C++ tests" bullet. Clause:
  "the C++ library's own tests".
- [ ] **Step 3: ADR 0068:** sqlearn's own models are Phase 5, not 4. Clause:
  "the models' phase is now 5".
- [ ] **Step 4: `CLAUDE.md`.** In the rule beginning "From the engine's
  Phase 1, sqlearn runs on its own DuckDB build", replace "with the engine
  compiled in, shipped as a second package beside sqlearn" with "the same
  DuckDB the C++ library runs in, shipped by default as a second package
  beside sqlearn", and add `0060` to its ADR list.
- [ ] **Step 5: The overview.** §2's first constraint: computation inside
  DuckDB, as SQL the C++ library builds and its `sqlearn_*` functions; the
  library is C++, Python its bindings (ADR 0060, 0002); the Gram exception
  unchanged. Part 3.10: the library becomes C++ and Python its bindings,
  ported piece by piece (ADR 0067); "done when": every test passes
  unchanged against the C++ and no logic is left in Python (Phases 1 to
  4). §3.3's models: Phase 5. §4's "Now": Phase 0, revised.
- [ ] **Step 6: `layout.md`:** `engine/` holds sqlearn's C++ library, its
  kernels and its bindings (ADR 0060), and sqlearn's DuckDB build (ADR
  0061).
- [ ] **Step 7: Grep** the six files for Review Focus 1's phrases. Checks as
  in Task 1. Commit `docs: the ADRs and pages follow the C++ library (#78)`.

### Task 4: Plan 0b and the phase issues

**Files:**
- Modify: `docs/plans/2026-11-21-native-engine-phase-0b-inventory.md`
  (Task 3, Task 4, the Goal line)
- GitHub: issues #79, #82, #83

- [ ] **Step 1: Plan 0b's Goal:** "the inventory that puts every module of
  `src/sqlearn` in one of three groups" becomes "the inventory that gives
  every module of `src/sqlearn` its phase in the port".
- [ ] **Step 2: Plan 0b's Task 3.** Its Interfaces: each row starts `| `,
  then the module path in backticks relative to `src/sqlearn/`, then a
  phase column that is exactly one of `2`, `3`, `4`; further columns, in
  this order: the C++ that replaces it, what stays in the bindings, what it
  depends on, the evidence (spec §5.3). Its test becomes
  `test_the_inventory_gives_every_module_its_phase`: the same set
  comparison both ways, no path twice, every phase one of `2`, `3`, `4`.
  Its page: the groups of Phase 4 named, each with its modules and its
  place in the order, the order argued from the dependencies and the
  profiling page; "What the numbers change" compares with spec §5.3's draft
  order.
- [ ] **Step 3: Plan 0b's Task 4.** `CLAUDE.md`'s added sentence reads:
  "The native engine (part 3.10: sqlearn as a C++ library embedding DuckDB,
  Python its bindings): spec `docs/specs/native-engine.md`, ADRs 0060–0068,
  the port's inventory `docs/architecture/engine-inventory.md`, milestone
  "Native engine" (#78 to #84). Phase 0 is done; the port comes before any
  new area." `HANDOFF.md`: "Waiting on the user" keeps the benchmarks item
  and drops the backup push (done); "Next up" adds Phase 1's spec topics
  from spec §4 (the checks redesign, the library review, the C++ docs);
  the DuckDB-profiling trap says profiles go to stderr, not stdout; the
  three cosmetic leftovers of 0a are fixed in this task.
- [ ] **Step 4: The issues**, with `gh issue edit`:
  - #79's title: `Native engine, phase 1: sqlearn's DuckDB build, the C++
    library's skeleton and its Python bindings`;
  - #82's title: `Native engine, phase 4: the rest of the library ported to
    C++`, its body rewritten from spec §4's Phase 4;
  - #83's title: `Native engine, phase 5: sqlearn's own models`, its body
    from the old #82's;
  - a comment on #78 linking the revised spec and naming the change.

  Then `gh-board status` and check all three show on the board.
- [ ] **Step 5:** Checks as in Task 1. Commit `docs: plan 0b follows the
  revised spec (#78)`.
