---
type: spec
tags: [native-engine, phase-1, checks, duckdb-build, ci]
summary: "Spec for the native engine's Phase 1: faster checks, sqlearn's DuckDB build with the C++ skeleton and bindings in one package, the C++ safety tools, workflows started by hand, the site on Pages, and the tool review."
related: [docs/specs/native-engine.md, docs/architecture/workflow.md, ADR 0008, ADR 0060, ADR 0061, ADR 0062, ADR 0065, ADR 0067]
---
# Native engine, Phase 1: the checks, the build, the tools

Phase 1 of [the native engine](native-engine.md) (§4), issue
[#79](https://github.com/glaucis/sqlearn/issues/79). It lays the ground the
port stands on: checks fast enough for two languages, sqlearn's own DuckDB
with the C++ library's skeleton and its Python bindings inside it, the tools
that hold the C++ to its rules, and the site on GitHub Pages. No library
logic moves to C++ yet; Phase 2 starts that.

Status: brainstormed with Tomas and approved by him on 2026-11-21. Calls
marked "(the agent's call)" stay open to his correction.

## 1. Why

- **The port runs thousands of test runs.** Today `just test` runs all
  3,190 tests one after another, 3 to 4 minutes on one of eight cores, and
  `just verify` takes about an hour: the tests on three Pythons, again inside
  `validate`, then the 47-minute validation and the docs (measured
  2026-11-21 at load 11). `just check` is not the problem (about 2 s).
  Tomas: "code changed? test, otherwise what is the point?"
- **The engine needs its build before any of its code** (ADR 0060, 0061):
  one DuckDB in the process, the user's connection reaching the C++, and the
  start-up check.
- **The C++ is held to the safety rules from its first commit** (ADR 0065),
  so the tools that enforce them exist before the code does.
- **The code is to be of the highest standard** (Tomas): anyone reading it
  finds every function documented and every rule checked.
- **The site is where users learn sqlearn** (Tomas): how to use it, the API,
  and later examples, tutorials and benchmarks.

## 2. Goals, non-goals, anti-goals

**Goals**

- A test reruns only when something it depends on changed (§3.1).
- `sq.version()` answered from C++, one DuckDB in the process, a user's
  connection passed through to C++, the start-up check, on this Mac.
- Every tool of §3.2 in place, the C++ ones on the skeleton's code.
- The CI workflows written and started by hand (§3.5), the site deployed
  to GitHub Pages on each push to `main`.
- The tools sqlearn and its development use reviewed.

**Non-goals**

- Porting any library logic (Phase 2 onward).
- A release before `1.0.0`; PyPI; GPU code; the C layer; a published C++
  API or C++ docs site.
- Changing any public behaviour of `sq.`, beyond adding `sq.version()`.

**Anti-goals** (failures even if everything runs)

- A selection that silently skips a test whose dependency changed: speed
  never bought by testing less than the rule says.
- Two DuckDBs in one process.
- A full suite on every push (Tomas: "if I make lots of commits, and push
  every time... it will be a nightmare").

## 3. Decisions

### 3.1 When a test runs (Tomas, 2026-11-21)

A test that passed reruns only when something it depends on changed:

1. **its code**;
2. **a change it now meets**: a merge to `main` combining two changes each
   tested alone;
3. **a declared dependency** the selection cannot see: the native module,
   `uv.lock`, `devdata/`'s data, the test settings in `pyproject.toml` and
   `conftest.py`;
4. **a new place to run**: another Python, platform or DuckDB build.

Otherwise a run repeats one already passed and is skipped. So:

| When | What runs |
|---|---|
| A commit | the hook's `just check` (about 2 s, plus clang-format and clang-tidy on changed C++); `just test`, the affected tests in parallel, run by the developer before committing as today (none for a docs-only commit) |
| A push | nothing (the site's deploy aside, §3.6) |
| A merge to `main` | nothing, when it is a fast-forward to a tree that passed; else the affected tests on the merged tree |
| Work is done | `just check`, the affected tests and the affected validation runners pass |
| A release | everything (§3.5) |

The passed-tree record and testmon's map are local to each clone (the
agent's call): a fresh clone runs everything once, then only what changes.
A forgotten dependency shows at the release at the latest; the fix is to
declare it. This replaces native-engine.md §4's "the full suite and `just
verify` run in CI on every push" (changed there on 2026-11-21).

### 3.2 The tools (the agent's proposals; Tomas: "add all tools")

**For the checks**

- **Python test selection:** `pytest-testmon` (MIT), which maps each test to
  the lines it runs. The declared dependencies of §3.1 widen its selection:
  the tests that touch them, or every test where that cannot be narrowed.
- **Parallel tests:** `pytest-xdist` (MIT), on every core.
- **Validation recorded:** each runner's verdicts are kept with a digest of
  the code they covered (its sqlearn modules, its references' versions, its
  data); a runner reruns only when the digest changes, as glaucis records an
  engine's answers. A release reruns every runner.
- **The passed tree:** the check that passes records the git tree it
  passed (as glaucis's `check.sh` does).
- **`just` stays the one entry point** (ADR 0008), for Python and C++ alike.
  Under it, **CMake** builds the C++ (DuckDB, its Python package and
  scikit-build-core are CMake already), with **Ninja**, **ccache**, and
  **CMake presets** naming the variants (dev, sanitizers, fuzzing, release).
  Considered: Meson, Bazel, xmake, none of which DuckDB builds with.

**For the C++** (on sqlearn's sources; DuckDB's are never edited, §3.3)

| Job | Tool |
|---|---|
| Prevent leaks by design | RAII, `unique_ptr`, no raw `new` or `delete` (ADR 0065); ownership is a tree, and a pointer back up is `weak_ptr` or plainly non-owning, so no `shared_ptr` cycle keeps objects alive (added to ADR 0065) |
| Compiler | `-Wall -Wextra -Wconversion -Wshadow -Wold-style-cast -Wnon-virtual-dtor -Wdocumentation -Werror`, and MSVC's equivalents |
| Static analysis | clang-tidy (`bugprone-*`, `cppcoreguidelines-*`, `performance-*`, more each with its reason), the Clang static analyser, CodeQL, include-what-you-use |
| Memory and undefined behaviour | AddressSanitizer with UndefinedBehaviorSanitizer; ThreadSanitizer as a separate run |
| Leaks | LeakSanitizer on Linux and on macOS with Homebrew LLVM (Apple clang's refuses `detect_leaks` on Apple silicon; LLVM 23's found a test leak, 2026-11-21); `leaks --atExit` on macOS for the Apple clang build; the MSVC debug heap's leak report on Windows; nanobind's leak report clean for sqlearn's own types |
| Logical leaks (memory still referenced that should not be: the store, the queued registrations) | a steady-memory test: learn and apply many times in a loop, memory must level off |
| Hardening | the hardened standard library (ADR 0065); the release flags of the OpenSSF compiler hardening guide (`_FORTIFY_SOURCE=3`, `-fstack-protector-strong` and the like), each benchmarked |
| Fuzzing | libFuzzer on each function's pure core, its corpus kept in the repository so found cases stay tested; built with Homebrew LLVM, since Apple clang ships no fuzzer runtime (§3.8) |
| Tests | Catch2 (BSL-1.0; DuckDB's own tests use Catch) under CTest; RapidCheck (BSD) for property tests; DuckDB's sqllogictest for SQL |
| Do the tests bite | coverage with llvm-cov, with a gate; Mull (Apache-2.0) mutation testing, in the release tier |
| Format | clang-format; gersemi for the CMake files |
| Benchmarks inside C++ | nanobench (MIT) |
| Documentation | a Doxygen-format comment on every function, checked by `-Wdocumentation`; no site, since the C++ API is internal (ADR 0060). MrDocs or Doxygen with Breathe are for the day it is published |
| Debugging, not CI | Heaptrack (Linux) for chasing a leak, named in the contributor docs |

Left out: Valgrind (not on Apple silicon; AddressSanitizer finds the same
far faster), MemorySanitizer (every library, DuckDB's and the standard
library included, rebuilt with it), cppcheck and SonarQube (overlap
clang-tidy and CodeQL), Deleaker and Visual Studio's snapshots (interactive,
Windows only).

The strict flags and clang-tidy apply to sqlearn's sources only. The
sanitizer builds instrument DuckDB too, since a sanitizer that sees half the
code misses errors and reports false ones (the agent's call). The raw memory
layer of ADR 0065 is `engine/src/raw/`, the one place clang-tidy's
`cppcoreguidelines` bans on raw pointers are relaxed, reviewed hardest (the
agent's call).

**For the Python:** today's rules (ruff with its docstring and annotation
rules, ty, strict mypy, numpydoc) and `pydoclint`, which checks each
docstring against its function's signature.

### 3.3 One package (Tomas, 2026-11-21; settles native-engine.md §3.2's open choice)

- sqlearn's C++ library and its nanobind bindings are compiled into the
  DuckDB Python package's own native module, so there is one binary and one
  DuckDB by construction. The two-package default of ADR 0061 lapses, as
  that ADR foresaw: `uv add sqlearn` installs one wheel per platform holding
  `sqlearn/` and `duckdb/`.
- DuckDB and its Python package are git submodules under `engine/` at
  `v2.0.1` (released 2026-11-20), never edited. A CMake layer of ours adds
  our sources to their build (the agent's call); if that proves impossible
  without changing their files, the builder stops and asks Tomas.
- A fresh clone compiles DuckDB once (about 10 to 20 minutes on the M3, to
  be measured); ccache keeps the result (the agent's call).
- `import sqlearn` asks the native module for its build identity and
  refuses the official `duckdb` with `Why:` and `Fix:` lines.
- `sq.version()` answers from C++ with sqlearn's version and its DuckDB
  build; `sq.__version__` stays (the agent's call). A test passes a user's
  connection through to C++ and back.
- Considered: two packages linking one shared DuckDB library (rpath, the
  Windows DLL search and wheel repair on three systems: fragile, for no gain
  but the separate release of a pure-Python change).

### 3.4 Versions and releases (Tomas, 2026-11-21)

- sqlearn has never been released; its version comes from git (hatch-vcs),
  now `0.1.dev597`. Nothing is restarted.
- **No release before `1.0.0`.** Until then versions stay development
  numbers (the agent's call, from "the first release where we will run the
  full test suite will be 1.0.0").
- **A release is a major or minor version tag** (`v1.0.0`, `v1.1.0`); a
  patch (`v1.0.1`) is not, and runs no release tier.

### 3.5 CI and the release tier (Tomas, 2026-11-21)

- **No CI runs automatically before `1.0.0`.** The workflows are written in
  Phase 1 and started only by hand from the Actions tab, as glaucis's are.
  Accepted cost: Linux and Windows first build sqlearn's C++ when someone
  starts the workflow; MSVC's differences surface then, in a batch.
- **The release tier**, `just verify` renamed or kept (the agent's call):
  the whole suite on Python 3.12, 3.13 and 3.14 on macOS, and on one Python
  on every other platform of ADR 0062 (the agent's call); the sanitizers,
  the fuzzers, the static analyser and CodeQL, Mull, the steady-memory test;
  the docs and their doctests; every validation runner; the ready-made
  builds, attached to the GitHub Release. A test whose reference library has
  no build for a platform is skipped there, and the skip is recorded (the
  agent's call).
- Before `1.0.0`, the tier's local part (macOS) can be run by hand at any
  time; it is not a gate for merges.

### 3.6 The site (Tomas, 2026-11-21)

- The documentation site deploys to GitHub Pages on each push to `main`: one
  small workflow builds the Sphinx site with its doctests and publishes it.
  It runs no library tests.
- It holds how to use sqlearn and the API reference; examples, tutorials and
  benchmarks follow later.
- Before `1.0.0` it shows one version, "dev"; the version switcher (#6)
  gets real entries from `1.0.0`. The README's relative link (#4) becomes an
  absolute one to the site.

### 3.7 The order (Tomas, 2026-11-21)

One spec, four steps, each with its own plan and merge:

1. **The checks** on today's Python (§3.1, the Python tools of §3.2).
2. **The build:** `engine/`, the one package, the skeleton and bindings
   (§3.3), the standard, compilers and editor tools (§3.8), the C++ tools
   of §3.2 on the skeleton, the third-party file and
   `NOTICE` (ADR 0066), no automatic downloads (ADR 0061), DuckDB's official
   extensions tested to load.
3. **The workflows and the site:** the release tier's workflows, started by
   hand (§3.5); the site's deploy (§3.6), closing #4 and #6.
4. **The review and the measurements:** the libraries sqlearn and its tools
   use, each kept or replaced with its reason, small swaps done in Phase 1
   and larger ones made issues (the agent's call); our build benchmarked
   against the official one on sqlearn's benchmarks; the hardened standard
   library's cost measured, for Tomas to rule on (ADR 0065).

Considered: the build first (its many test runs under today's slow
checks); everything on one branch (nothing usable until the end).

### 3.8 The C++ standard and the compilers (Tomas, 2026-11-21)

- **C++23**, on every compiler: `std::expected`, `std::mdspan`, `std::print`,
  `flat_map`, deducing `this`. Tomas: "23 for now".
- **C++26 waits.** Its mode is unfinished on every compiler (`__cplusplus` is
  `202400`), and the features worth moving for are missing from the compiler
  that builds the macOS release. A probe of the feature macros on 2026-11-21
  (macOS 27.2.1):

  | | Apple clang 21.0.0 | LLVM 23.1.6 | GCC 16.2.0 |
  |---|---|---|---|
  | Reflection | no | no (`-Xclang -freflection` parses `^^int`, cannot evaluate it) | yes, experimental (`-freflection`) |
  | Contracts | no | no | yes, experimental (`-fcontracts`) |
  | `std::linalg` | no | no | no |

  An ADR moves to C++26 once Apple clang has reflection and contracts;
  `std::linalg` is not needed, since the engine calls BLAS (ADR 0063). The probe
  is kept as a `just` recipe, rerun after each Xcode update (the agent's call).
- **Moving later stays cheap.** C++26 keeps C++23 code working; the flag
  changes in one place, and warnings as errors point to what it deprecates.
  Two habits keep adopting its features small: preconditions go through one
  engine macro (`SQ_EXPECTS` or similar), which later becomes `pre(...)`;
  and a struct's field list, where code needs one (saving, bindings,
  validation output), is written in one place, which reflection later
  generates (the agent's call).
- **Each compiler has its job:**

  | Compiler | Job |
  |---|---|
  | Apple clang | the macOS release build and the everyday build on this Mac (ADR 0062: Accelerate, Metal) |
  | Homebrew LLVM | clang-tidy, the static analyser, clangd, clang-format, the sanitizer and fuzzing builds on macOS (Apple clang has no fuzzer runtime and no LeakSanitizer on Apple silicon) |
  | GCC | the Linux release build, in the hand-started workflow (manylinux builds with it) |
  | MSVC | the Windows release build, in the hand-started workflow (Python on Windows is built with it) |

  So the C++ compiles on three compilers, which catches code only one accepts.
  GCC 16 stays installed on this Mac for reproducing a GCC error locally;
  nothing requires it there.
- **The agent's editor tools:** clangd as the agent's language server, from
  the `compile_commands.json` that CMake writes (the agent's call).
  CodeGraph indexes sqlearn's own sources, `engine/` included, never the
  DuckDB submodules (Tomas, 2026-11-21): step 2 adds a `codegraph.json`
  at the root, for this project only, whose `exclude` lists the
  submodules' paths, and maps `.h` to C++ if headers are named so.

## 4. What changes elsewhere

- `CLAUDE.md`'s checks section and `docs/architecture/workflow.md`: the
  tiers of §3.1, in the step 1 commit that brings them. Until then
  `just verify` stays the full check.
- ADR 0061 gets an "Amended by" line for the one package; ADR 0065 one for
  the ownership rule, the extra warnings and the CI that starts by hand; ADR
  0008 one for CMake under `just`, if the builder judges it a change.
- ADR 0062's ready-made builds come from the hand-started workflow until
  `1.0.0`.
- The layout page, for `engine/`.

## 5. Left to the builder

- The recipes' names, the presets' names, the native submodule's name
  (`duckdb._sqlearn` or similar).
- How the passed tree is recorded, and the validation digest's exact inputs.
- How testmon's selection is widened for each declared dependency.
- The clang-tidy checks beyond those named, each with its reason; the
  coverage gate's level.
- Which libraries the review covers beyond the tools named here.

## 6. Done when

- Step 1: a one-line change to one module runs only its tests; a docs-only
  commit runs none; a fast-forward merge of a passed tree runs nothing; the
  validation reruns only what changed; the release tier runs everything.
- Step 2: `sq.version()` answers from C++ on this Mac; one DuckDB in the
  process; the start-up check refuses the official `duckdb`; every existing
  test passes unchanged on our build; every C++ tool of §3.2 runs on the
  skeleton and passes; the skeleton builds as C++23 with Apple clang and
  Homebrew LLVM, and the C++26 probe runs (§3.8).
- Step 3: the hand-started workflow passes on every platform of ADR 0062
  and produces each platform's wheel; the site is live on GitHub Pages.
- Step 4: the review is recorded, the benchmarks published, and Tomas has
  ruled on the hardened library.
- `HANDOFF.md` updated with each merge, and #79 closed after step 4.
