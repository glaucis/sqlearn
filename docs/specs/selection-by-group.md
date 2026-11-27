---
type: spec
tags: [checks, selection, tests, validation, benchmarks, groups, speed]
summary: "Spec for selecting by group: every Python test, validation runner and benchmark belongs to a group, and reruns only when a fingerprint of what its group is built from changes, comments and docs excluded, so the checks stop repeating work whose code did not change."
related: [docs/specs/native-engine-phase-1.md, docs/architecture/testing.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md, validation/_checks.py, validation/_ctest.py, validation/_record.py]
---
# Selecting by group

Status: draft for Tomas's approval, from the design talk of 2026-11-27. Where
this spec makes a call of its own, it says "(spec's call)".

## 1. Why

Tomas: "not to run all these long tests, validations, and etc… as now we
are spending lots of time on running scripts than writing actual code… and
they run just to run, even when nothing in that function or group of
functions changed."

Today a comment in a CMake file, or any edit of the engine's sources,
reruns every validation runner (about 47 minutes on this machine) and the
whole Python suite (about 5 minutes), because the module Python loads is
fingerprinted as one thing. The rewrite (ADR 0070) will change `engine/`
every day, so this must land before its first group.

## 2. Goals, non-goals, anti-goals

**Goals**

- A test, a validation runner or a benchmark reruns only when something it
  depends on changed since it last passed.
- A comment, whitespace, a docs edit or a CMake comment reruns nothing that
  compiles: what is fingerprinted is code and the flags it is built with,
  not text.
- The grain is the **group** (Phase 1 spec §3.1: "the build decides, not
  coverage"), and a group's dependencies come from what the build and the
  imports know, never from a list kept by hand that nothing checks.
- When the selection cannot tell, it reruns: unknown means affected.

**Non-goals**

- Selecting single tests inside a group by the code each ran (approach B,
  §4): left for later, on top of this.
- Changing the full tiers: `just full <task>`, `just validate-all` and
  `just verify` still run everything.
- CI: there is none yet (Phase 1 step 3).

**Anti-goals** (a failure even if it runs fast)

- A change that can alter a result, and no check reruns for it.
- A list of dependencies that can drift from the code without a test or a
  check failing.
- A benchmark started by a check (ADR 0072).

## 3. How it works today

- **C++ tests** (`validation/_ctest.py`): each CTest label is a group (`core`,
  `raw`, `crash`, `canary`, `must_not_compile`). A group's identity hashes
  its tests' commands, their programs' bytes and the libraries they load,
  their `REQUIRED_FILES`, and the compile entries of the targets behind
  them. A group whose identity a passed record holds is skipped.
- **Python tests** (`TEST_INPUTS` in `validation/_checks.py`): one digest of
  `src/`, `tests/`, `validation/`, `devdata/`, the whole of `engine/` and a
  few files; any change reruns all of them (2,922 library tests under
  `tests/src/`, about 650 tooling tests elsewhere).
- **Validation runners** (`validation/_record.py`): each runner records the
  repository files it imported, `uv.lock` and devdata's files, plus one
  `engine` digest of `ENGINE_BUILD`'s files and pins, the build tables and
  the compiler. Every runner imports `sqlearn`, which imports the whole
  package, so any change under `src/` or any input of the module reruns all
  24 runners.
- **Benchmarks**: none runs in a check; `just bench-engine` and the pages'
  scripts run by hand (ADR 0072).

## 4. Approaches

- **A. Groups everywhere** (chosen by Tomas, 2026-11-27): every Python test,
  runner and benchmark belongs to a group; a group reruns when the
  fingerprint of what it is built from changes. It cannot miss a dependency
  the build or the imports know.
- **B. Groups, plus exact selection while working**: A, and `just test` runs
  only the tests whose recorded coverage touched the change, `just done` the
  whole groups. Faster inside a group, but it needs a coverage-instrumented
  build and a record per test; left for later, on top of A.
- **C. Exact selection only**: dropped. It misses code run at start-up,
  files read as data, and new code that changes which function is called
  (testmon's holes, Phase 1 spec §3.1).

## 5. The design

### 5.1 The module's fingerprint, per C++ group

The wheel's binary holds every C++ group. Instead of one digest of
`ENGINE_BUILD`'s text, the module gets **one fingerprint per C++ group**,
and a **shared part**:

- **A C++ group's fingerprint** covers its own sources and headers
  (`engine/src/<group>/`), each with its **comments removed but its line
  numbers kept** (for example `clang -fpreprocessed -dD -E` without `-P`,
  which strips comments without expanding macros or includes and keeps the
  line markers; the builder's choice of tool). A line number reaches users:
  a `PreconditionError` names its file and line (`core/error.cpp`), so a
  comment that adds or removes lines changes the fingerprint and reruns its
  group, while one edited within its lines does not (Tomas, 2026-11-27:
  "yes, rerun it"). Then the **compile entries**
  of those sources as the wheel's build has them (`compile_commands.json`,
  normalised as `_ctest` already does), so a flag that changes reruns it and
  a CMake comment does not. It includes the fingerprints of the C++ groups
  it links or includes (CMake's link graph and the compiler's depfiles),
  so a change in `core` reaches every group built on it.
- **The shared part** covers what every group runs with: the bindings
  (`engine/src/bindings/`) and the extension (`engine/extension/`) as code
  without comments, the pins of every submodule under `engine/`, the build
  tables of `pyproject.toml`, the compiler's identity (as `_ctest`'s
  `compiler`), and every compile flag that is not per source. A change here
  reruns everything that uses the module.

What the CMake files say reaches the fingerprint only through what they
make the build do: the compile entries, the link graph and the generated
headers (for example `build_identity.hpp`, hashed as a source of
`core`). Today's `engine` digest in `validation/_record.py` is replaced by
this.

### 5.2 Which C++ groups a Python test or runner uses

- **Declared beside the C++ group** (spec's call): `sq_add_group` takes the
  Python tests and the validation runners that exercise it, for example
  `PYTHON_TESTS tests/src/sqlearn/decomposition` and
  `VALIDATION validate_pca`. A Python test or runner **no group claims
  depends on every C++ group** (unknown means affected), so today, with only
  `core`, `raw` and `crash` in C++, every Python test depends on all of
  them, as it truly does: the module loads `core` and installs the crash
  handler at import.
- **The audit** (spec's call): `just verify` runs the Python tests and the
  runners once on a coverage-instrumented module (sqlearn's C++ instrumented
  with source-based coverage, DuckDB not; a wheel flavour that does not exist
  yet), one process per declared test set, and fails when a test or runner ran
  code of a C++ group outside its declared groups and their links, naming the
  group to add. Code that runs when the module loads (`core`'s start-up, the
  `crash` handler) belongs to the shared part, not to any declaration. A wrong
  declaration is caught at the release tier, never silently kept. Between
  releases a declaration can be wrong only by naming too few groups for a new
  call path; each group's spec names its declarations and runs
  `just audit-groups` (the audit alone) before its merge.

### 5.3 The Python side

The Python library is frozen (ADR 0070), so its changes are rare (spec's
call):

- **Library tests** (`tests/src/`) and **validation runners**: their Python
  part stays as today, any change under `src/` reruns all of them, since
  `import sqlearn` loads the whole package. Their C++ part is the
  fingerprints of their declared groups (§5.2) and the shared part. As each
  group's Python is deleted with its tests, this coarse part shrinks with
  it.
- **Tooling tests** (`tests/checks`, `tests/githooks`, `tests/validation`,
  `tests/engine`, `tests/docs`, `tests/devdata`, `tests/test_environment.py`):
  one group whose inputs are every file they read as text: today's
  `TEST_INPUTS` with only `src/sqlearn` of `src/` (the docs tests check its
  modules against the inventory), the whole of `engine/` (presets,
  `mull.yml`, the fuzz corpus, CMake files, and the C++ itself, comments
  included, which the engine tests scan line by line) and `.clangd`, plus
  the module's whole fingerprint, since some load the module. They take
  seconds to a minute, so they rerun on any engine or `src/` edit, a C++
  comment included: the price of no silent skip (the ruling at Task 4's
  review, replacing the spec's first call, which left `src/` and the C++
  sources out).
- **Python tests are split into these groups** in `validation/_checks.py`:
  the `test` task becomes the C++ groups (as now), the tooling group, and
  **one library group per declared test set** (each C++ group's
  `PYTHON_TESTS`, plus one set of the tests no group claims), each with its
  own record and its own pytest call (spec's call). A change under `src/`
  reruns every library set; a C++ change reruns the sets whose declared
  groups it reaches.
- **The tooling group reads CMake files as text** (some of its tests parse
  them), so a CMake comment reruns it, about a minute (spec's call: it is
  cheap, and stripping them could hide a change a test checks).

### 5.4 Benchmarks

Each benchmark (each `engine/bench/` program, and each page's script under
`validation/benchmarks/`, which names the page it writes) gets the same kind of
identity: the C++ groups it measures (declared as for runners, unknown meaning
all), its own files, and the shared part. `just benchmarks-due` lists the
benchmarks whose identity has no recorded run, each with its expected time and
weight from its last run (wall time, cores used, peak memory), and runs nothing.
`just bench <name>` runs one, after Tomas's go-ahead (ADR 0072), and records its
identity, its numbers and the load; the agent then writes the numbers into the
page by hand, as today (spec's call: no page is generated).

### 5.5 The other checks

`docs` (its doctests run on the module), `types` and `docstrings` (they read
the module's stubs) and `sql` (the extension links `core`) take the same
fingerprints in place of `ENGINE_BUILD`'s text: the shared part and the
groups they use (`sql`: the extension and `core`). `tidy`, `format` and
`lint` read the source text, comments included (`NOLINT` is a comment),
and stay as today (spec's call).

The compile entries come from the wheel's build (`build/cpython-312`, which
exports `compile_commands.json`). Every check runs through `uv run`, which
rebuilds the module first when its inputs changed, so the entries are
current; when they are missing (a fresh clone, a failed build) everything
reruns, and a fresh clone runs everything once anyway (spec's call).

### 5.6 Fail-safe rules

- A file, flag or pin the fingerprint cannot read (no `compile_commands.json`,
  a tool missing, a parse error) reruns everything it could affect, with a
  line saying why.
- A Python test or runner that no group claims depends on every C++ group.
- A record from another place (Python, platform, machine, compiler) never
  matches (as today).
- A run whose inputs changed while it ran records nothing (as today).

### 5.7 What it changes, by example

| Change | Reruns today | Reruns after |
|---|---|---|
| A comment in `engine/cmake/warnings.cmake` | the C++ groups, every Python test, all 24 runners | the tooling group (about a minute) |
| A comment edited within its line in `engine/src/core/error.cpp` | the same | nothing |
| A comment line added to `engine/src/core/error.cpp` | the same | `core`'s C++ tests and every Python test and runner (all use `core`) |
| A real change in `core` | the same | `core`'s C++ tests, every Python test and runner (all use `core`) |
| A real change in a future `decomposition` C++ group | the same | its C++ tests, `tests/src/sqlearn/decomposition`, `validate_pca`, the tooling group |
| `-ffp-contract` changed | the same | everything that uses the module |
| `mull.yml` edited | every Python test | the tooling group |
| A docs page edited | the docs build | the docs build |

Today all of the engine's C++ is foundational, so a real C++ change still
reruns every Python test and runner; the saving now is comments, docs and
CMake text, and it grows with each group the rewrite adds.

### 5.8 Tests of the selection

Each in `tests/validation/` or `tests/checks/`, on scratch repositories as
today's are:

- a comment edited within its lines in a C++ source, a header or the
  bindings changes no fingerprint, and a CMake comment changes none of the
  module's;
- a comment that adds or removes a line in a C++ source changes that
  group's fingerprint (its line numbers reach `PreconditionError`'s
  message);
- a code change in a group changes that group's fingerprint and those of the
  groups built on it, and no other;
- a changed compile flag, pin, build table or compiler changes the shared
  part;
- an unclaimed Python test or runner depends on every group;
- the audit fails on a test that runs a group it does not declare;
- a tooling input (`mull.yml`, a preset) reruns the tooling group alone;
- `just benchmarks-due` runs no benchmark.

## 6. Left to the builder

- The tool that strips comments, and how a header's fingerprint is shared
  between the groups that include it.
- Where the declarations live in CMake and how `validation/_checks.py` reads
  them (CTest properties, a generated file, `cmake --graphviz`).
- The record format, kept compatible with `_checks.Record` where it can be.
- How `just audit-groups` maps coverage to groups (by source path under
  `engine/src/<group>/`).

## 7. Done when

- The tests of §5.8 pass.
- On this machine, a comment added to `engine/cmake/warnings.cmake`, and a
  comment edited within its line in a `core` source, each committed alone,
  make `just done` run no library test, no validation runner, no doctest and
  no SQL test.
- `docs/architecture/testing.md` describes the groups, the fingerprints, the
  audit and `just benchmarks-due`; `HANDOFF.md`'s item moves to "Just
  finished".
