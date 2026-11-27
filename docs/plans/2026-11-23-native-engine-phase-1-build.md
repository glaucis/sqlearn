---
type: plan
tags: [native-engine, phase-1, build, cmake, cpp, plan]
summary: "Phase 1 step 2: DuckDB 2.0.1 and its Python package as submodules under engine/, sqlearn's C++ skeleton and nanobind module compiled into DuckDB's own binary, one wheel, sq.version() from C++, the start-up check, and every C++ tool of spec §3.2 and §3.9 on the skeleton."
related: [docs/specs/native-engine-phase-1.md, docs/specs/native-engine.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/adr/0062-apple-silicon-first.md, docs/adr/0063-the-engines-compute-libraries.md, docs/adr/0065-safety-rules-for-the-cpp.md, docs/adr/0066-permissive-licences-never-copyleft.md, docs/adr/0067-how-computation-moves-to-the-engine.md]
---
# Phase 1 step 2: the build, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** sqlearn installs as one package holding its own DuckDB 2.0.1,
with its C++ library compiled into DuckDB's own native module. `sq.version()`
answers from C++, and every C++ tool of spec §3.2 and §3.9 runs on the
skeleton and passes.

**Architecture:** `engine/` holds the submodules (`duckdb-python` at
v2.0.1 with DuckDB v2.0.1 nested in it, and the C++ test and crash
libraries) and a CMake layer of ours that `add_subdirectory()`s
duckdb-python and adds our object libraries to its `_duckdb` target. Their
files are never edited. The same `_duckdb` binary carries a second nanobind
module, `_native`, which Python loads from `_duckdb.__file__`, so there is
one DuckDB by construction. sqlearn's `pyproject.toml` builds the wheel with
scikit-build-core from `engine/CMakeLists.txt`. The C++ itself is built and
tested under `just` through CMake presets, one Catch2 program per group.

**Tech Stack:** C++23 (Apple clang 21, Homebrew LLVM 23), CMake ≥ 3.29,
Ninja, ccache, scikit-build-core, nanobind, Catch2, RapidCheck, nanobench,
cpptrace, libFuzzer, llvm-cov, Mull, clang-tidy, include-what-you-use,
clang-format, gersemi, gitleaks, uv, just.

**Spec:** `docs/specs/native-engine-phase-1.md` §3.2 ("For the C++"),
§3.3, §3.7 step 2, §3.8, §3.9, §4, §5, §6 step 2 (approved by Tomas,
2026-11-21 and 2026-11-22). Background: `docs/specs/native-engine.md`
§3.1, §3.2. Build mechanisms checked by a spike on 2026-11-23 (see
"Spike results" below).

## Global Constraints

- Every task runs through `just`; Python through `uv run --locked`, never pip
  or a bare `python` (ADR 0001, 0008). CMake runs under `just` (spec §3.2).
- DuckDB's and duckdb-python's files are never edited (spec §3.3). If a step
  cannot be done without editing them, stop and ask Tomas.
- Submodules pinned: duckdb-python `v2.0.1`
  (`de8eed775826e6c515af3656a6a88e00559a903b`), its `external/duckdb` at DuckDB
  `v2.0.1` (`8d78114e90a53823803660bf821f6073ac87da8c`).
- Runtime: the wheel holds `sqlearn/` and `duckdb/`; runtime dependencies stay
  numpy alone beside the compiled-in code (ADR 0005, 0057). Compiled-in
  libraries carry only OSI-approved permissive licences, each in the
  third-party file (ADR 0066). Test-only libraries (Catch2, RapidCheck,
  nanobench) never ship.
- No download by default: DuckDB 2.0 has no build switch for it, so the
  `sqlearn` extension sets `autoinstall_known_extensions` to false at load,
  never overriding a user who set it. An extension the user installs still
  loads (ADR 0006, 0061). Submodules are fetched by `git`, never by CMake
  `FetchContent` at configure time.
- One package: the wheel `sqlearn` holds `sqlearn/`, `duckdb/` (with a
  generated `_version.py`, spec §3.3) and the `_duckdb` binary with
  sqlearn's C++ inside (Tomas, 2026-11-23).
- Toolchain from Homebrew: `cmake`, `ninja`, `ccache`, `llvm`,
  `include-what-you-use`, `gitleaks`; `just doctor` checks each and prints a
  `Fix:` line for a missing one (Task 1).
- C++23 on every compiler, `-std=c++23`; feature tests by `__cpp_*` macros,
  never by the flag (HANDOFF trap). Our sources only get the strict flags and
  clang-tidy (spec §3.2).
- Warnings for our sources: `-Wall -Wextra -Wconversion -Wsign-conversion
  -Wshadow -Wold-style-cast -Wnon-virtual-dtor -Wdocumentation
  -Wimplicit-fallthrough -Wswitch-enum -Wdouble-promotion -Wthread-safety
  -Wunsafe-buffer-usage -Werror` (`-Wunsafe-buffer-usage` off in
  `engine/src/raw/` only).
- Never `-ffast-math`; `-ffp-contract=off` on our sources (spec §3.9; the
  FMA ADR is Tomas's to write before Phase 2's kernels, so this line may
  change then).
- No raw `new`/`delete`, no C arrays, ownership a tree; raw memory only in
  `engine/src/raw/` (ADR 0065).
- Every function has a Doxygen comment (`///`), checked by
  `-Wdocumentation` for form (spec §3.2).
- Preconditions go through one macro, `SQ_EXPECTS(cond)` (spec §3.8).
- sqlearn's own C++ errors reach Python as `sq.errors.InternalError` with
  `Why:` and `Fix:` lines. Errors DuckDB raises stay DuckDB's own
  exceptions, as users know them. Nothing crashes the interpreter (ADR
  0065).
- Public API: only `sq.version()` is added (spec §2); no other public test
  changes (ADR 0067).
- SQL functions start with `sqlearn_` (native-engine.md §3.1).
- British English in prose, American spelling in identifiers (ADR 0010).
- commitlint: no scope but `hooks`, `site`, `deps`; lower-case subject;
  lines at most 72 characters; no AI or tool attribution.
- Waiting rule for every agent: each long command once, in the foreground,
  output to a log with `; echo EXIT=$? >> log`; never the Monitor tool, never
  `tail -F`, `until`, `while` or `pgrep` loops, never a second copy, never
  kill a process it did not start; while a build, the tests or the
  validation run, no other `uv run`, `just` or `cmake --build` in the tree.

## Review Focus

1. **The official `duckdb` wins the folder** (another package reinstalls
   it). Expected: `import sqlearn` refuses with `Why:` and `Fix:`, never a
   crash or a silent second DuckDB. Test in Task 3.
2. **A fresh clone without `git submodule update`.** Expected: `just setup`
   fetches them; a build without them fails at configure with a `Fix:` line
   naming the command, never a CMake trace. Test in Task 1.
3. **A submodule bump or a C++ edit.** Expected: the checks rerun (the
   gitlink and every `engine/` source are digest inputs), and `uv run`
   rebuilds the module. Tests in Tasks 1 and 6.
4. **A user's connection crossing into C++** while the user still holds an
   unfinished result on it, or after closing it. Expected: DuckDB's own
   error for what DuckDB refuses, `sq.errors.InternalError` with
   `Why:`/`Fix:` for sqlearn's, never a crash. Tests in Task 3.
5. **An extension the user installed by hand** (`INSTALL x` then `LOAD x`
   with a local file) still works, nothing downloads by itself, and a user
   who turns downloads on keeps them. Tests in Task 3.

## Status

Ready for Tomas's review (2026-11-23). Tasks 2 and 3 are written for one
package with DuckDB inside (Tomas, 2026-11-23; spec §3.3), and Task 12 adds
the SQL tests.

## Spike results

A spike on 2026-11-23 built duckdb-python v2.0.1 with DuckDB v2.0.1 under a
scratch CMake project, editing none of their files:

- **Our objects join their module.** After `add_subdirectory(duckdb-python)`,
  `target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:ours>)` builds, and
  `import duckdb` works. Our object library:
  - links their `_duckdb_dependencies` INTERFACE target (headers, nanobind,
    `NB_DOMAIN=duckdb`);
  - sets `CXX_STANDARD 23` and `CXX_VISIBILITY_PRESET hidden`;
  - gets `-std=c++23`, while theirs and DuckDB's get `-std=c++17`;
  - compiles their headers cleanly under C++23.

  `CMAKE_EXPORT_COMPILE_COMMANDS` must be set at our top level.
- **A second module in the same binary.** `NB_MODULE(_native, m)` exports
  `PyInit__native` beside `PyInit__duckdb`.
  `importlib.machinery.ExtensionFileLoader("sqlearn._native",
  _duckdb.__file__)` loads it, through `spec_from_file_location`,
  `module_from_spec` and `exec_module`. The module's name must end in
  `_native`, and `_duckdb` must be imported first.
  - It takes the user's connection as `duckdb::DuckDBPyConnection&`, under
    `ConnectionLockGuard`, through `con.con.GetConnection()`:
    `count_rows(con, "t") == 5`, and `roundtrip(con) is con`.
  - A closed connection raises their `duckdb.ConnectionException`.
  - A `duckdb::Exception` reaches Python through their translators, which
    the shared domain gives us.
  - A file without `PyInit__native` raises `ImportError: dynamic module does
    not define module export function (PyInit__native)`. The official
    `_duckdb` fails the same way, which is what the start-up check catches.
- **SQL functions as a statically linked DuckDB extension.**
  - Before `add_subdirectory`, set `DUCKDB_EXTENSION_CONFIGS` to our config
    (`duckdb_extension_load(sqlearn SOURCE_DIR ...)`).
  - Also set `LINK_EXTENSIONS` to `core_functions;parquet;icu;json;sqlearn`.
    It replaces the default list, so the four must be repeated.
  - `build_static_extension`, then `DUCKDB_CPP_EXTENSION_ENTRY(sqlearn,
    loader)`.
  - Every database answers `SELECT sqlearn_version()` with no `LOAD`, and
    `duckdb_extensions()` lists it as `STATICALLY_LINKED`.
  - DuckDB's sqllogictest runner exists only in its `unittest` program
    (`BUILD_UNITTESTS`).
- **Costs.**
  - The first full build took 227 s on 8 cores, without ccache.
  - Touching one of our files costs one compile and the link, 2 s.
  - The module is 51 MiB.
  - Homebrew had no `cmake`, `ninja` or `ccache`.
  - The stable ABI (`abi3`) comes only through scikit-build-core
    (`SKBUILD_SABI_COMPONENT`).
- **No download switch at build time any more.** DuckDB 2.0's CMake prints
  "ENABLE_EXTENSION_AUTOINSTALL has no effect: autoload_known_extensions and
  autoinstall_known_extensions default to true, change them at runtime
  instead".
- **`duckdb/_version.py` runs `importlib.metadata.version("duckdb")`**, so
  `import duckdb` fails when no distribution named `duckdb` is installed.
  That is why `_version.py` is generated (Status above).
- **Risks.**
  - Objects compiled as C++17 and C++23 in one binary: the ABI is stable,
    but inline code that differs by standard is an ODR risk. nanobind adds a
    `u8string` caster only under C++20 and later.
  - DuckDB internals that are not public API (`DuckDBPyConnection::con`,
    `ConnectionLockGuard`) are pinned with the submodules; the tests rerun at
    every bump.
  - Their Release build silences nanobind's leak warnings for the whole
    shared domain.
  - The module exports about 31,000 of DuckDB's symbols, so ours are built
    hidden.

## Rulings for this step (the agent's calls, open to Tomas)

- **The module name** is `sqlearn._native`, an `NB_MODULE(_native, m)` in
  the `_duckdb` binary, loaded with `importlib.machinery.ExtensionFileLoader`
  from `_duckdb.__file__` (spec §5 leaves the name to the builder).
- **C++ errors:** sqlearn's own become the existing
  `sq.errors.InternalError`; DuckDB's stay DuckDB's (the spike: its
  translators already serve our module); the start-up refusal is an
  `ImportError`, what Python raises for a failed import. No new public
  class.
- **Test libraries and cpptrace are git submodules** under
  `engine/third_party/`, pinned to tags; no configure-time downloads.
- **The C++ test programs of step 2 do not link DuckDB** (no group uses it
  yet), so the sanitizer presets do not rebuild DuckDB. The first group that
  needs it (Phase 2) brings the instrumented DuckDB build (spec §3.2).
- **Python tests run on the release-flag build** installed by `uv sync`
  (what users get); the sanitized `dev` preset runs the C++ tests. The Python
  suite under AddressSanitizer is left to Phase 2, when the bindings carry
  logic.
- **The static analyser** is clang-tidy's `clang-analyzer-*` checks;
  `scan-build` is not added.
- **CodeQL** runs in step 3's workflows (it is a GitHub workflow), not here.
- **Deferred to the step that needs them** (spec §3.9 lines with nothing to
  act on in a skeleton): PGO, BOLT, `just tune`, Highway and
  `target_clones` (Phase 2 kernels); RealtimeSanitizer (no non-blocking
  kernels yet); observability, `sq.explain`, fault tests, SQL snapshots
  (library logic, Phase 2 on); `just bench` as a gate and `just profile`
  (step 4); SBOM, reproducible and signed wheels (step 3); the hardened
  library's cost (step 4).
- **Also deferred, with their reasons:** fuzzing the SQL builder and the
  `sq.load` reader (neither is C++ yet); ruff complexity limits and an
  example in every public docstring (a pass over existing Python code, its
  own issue); the changelog from commit messages (git-cliff, with the
  releases of step 3); GCC and MSVC builds (step 3's workflows).
- **Free-threaded Python:** no free-threaded wheel in step 2 (nanobind's
  stable ABI excludes it; DuckDB's package is unchecked). The question stays
  open in `docs/questions/free-threaded-python.md` for Tomas.

---

### Task 1: the submodules and their pins

**Files:**

- Create: `.gitmodules`, `engine/duckdb-python` (submodule),
  `engine/third_party/{catch2,rapidcheck,nanobench,cpptrace}` (submodules),
  `engine/cmake/pins.cmake`, `codegraph.json`,
  `tests/engine/test_pins.py`
- Modify: `justfile` (`setup` runs `just doctor`, then
  `git submodule update --init --recursive`; a new `doctor` recipe),
  `.gitignore` (`/engine/build/`, `/build/`, `/compile_commands.json`),
  `validation/_checks.py` (gitlinks in the digest),
  `tests/validation/test__checks.py`

**Interfaces:**

- Produces: `engine/cmake/pins.cmake` setting `SQ_DUCKDB_TAG` (`v2.0.1`),
  `SQ_DUCKDB_COMMIT`, `SQ_DUCKDB_PYTHON_COMMIT` and one
  `SQ_<LIB>_COMMIT` per third-party submodule; a CMake function
  `sq_check_pins()` that compares each pin with the submodule's checked-out
  commit and fails configure with a `Fix: git submodule update --init
  --recursive` line when a submodule is missing or differs.
- Produces: `just doctor` checks each tool of the Global Constraints'
  toolchain line, with its version, and for a missing one prints `Fix: brew
  install <formula>`, then exits non-zero.
- Produces: `_checks.digest` covers each gitlink (mode 160000 entry of `git
  ls-files -s`): path and commit.

Third-party pins (latest release tags on 2026-11-23, each checked for its
licence before adding): Catch2 v3 (BSL-1.0), RapidCheck (BSD-2-Clause, no
tags: pin a commit), nanobench (MIT), cpptrace (MIT). cpptrace's default
symbol backend on macOS and Linux is libdwarf, which is LGPL: configure it
with a permissive backend (`CPPTRACE_GET_SYMBOLS_WITH_LIBBACKTRACE`, BSD, or
`_WITH_ADDR2LINE`/`atos` as an external tool) and record which in the
third-party file (Task 11).

- [ ] **Step 1: Write the failing tests:** `tests/engine/test_pins.py`:
  `test_each_pin_is_the_submodules_commit` (parses `pins.cmake`, compares
  with `git ls-files -s` mode-160000 entries and `git -C engine/duckdb-python
  ls-files -s external/duckdb`); `test_duckdb_python_pins_duckdb_v2_0_1`
  (the nested pin equals `8d78114e90a53823803660bf821f6073ac87da8c`). In
  `test__checks.py`: `test_a_submodule_bump_reruns_a_whole_task` (a scratch
  repository with a submodule; `git -C sub checkout <other>`; `git add`
  the gitlink; the digest changes). In `tests/checks/`:
  `test_a_configure_without_submodules_names_the_fix` (a scratch copy of
  `engine/cmake/` with an empty submodule path; `cmake -P` on a small script
  calling `sq_check_pins()` exits non-zero and prints `Fix: git submodule
  update --init --recursive`).
- [ ] **Step 2: Run them:** FAIL (no pins file, no submodules).
- [ ] **Step 3: Add the submodules** at their pins (`git submodule add`, then
  `git -C <path> checkout <commit>`; `--recursive` for duckdb-python),
  write `pins.cmake` and `sq_check_pins()`, hash gitlinks in
  `_checks._listed`/`_combined` (path, NUL, commit, NUL), and
  `codegraph.json` with `exclude` listing `engine/duckdb-python/**` and
  `engine/third_party/**`.
- [ ] **Step 4: Run them:** PASS; `just setup` on a fresh `git clone` of the
  branch (in the job's tmp dir) checks out every submodule.
- [ ] **Step 5: Commit:** `build: add duckdb 2.0.1 and the c++ libraries as
  submodules`.

### Task 2: one package, sqlearn's DuckDB inside

**Files:**

- Create: `engine/CMakeLists.txt`, `engine/cmake/duckdb_package.cmake`,
  `tests/engine/test_build.py`
- Modify: `pyproject.toml` (the build system, the packages, the defines, the
  cache keys; the `duckdb` dependency removed), `uv.lock`, `justfile`
  (`build-package`), `validation/_checks.py` (`engine/` in the `test`
  inputs; the submodules enter only as their gitlinks, Task 1),
  `validation/_record.py` (the module's build identity in each record's
  environment, so a rebuilt engine reruns every runner)

**Interfaces:**

- Consumes: Task 1's `pins.cmake` and `sq_check_pins()`.
- Produces: `engine/CMakeLists.txt` (C++23 for our targets;
  `CMAKE_EXPORT_COMPILE_COMMANDS ON`). It calls `sq_check_pins()`, then
  `add_subdirectory(duckdb-python)` with `OVERRIDE_GIT_DESCRIBE=v2.0.1` and
  `GIT_COMMIT_HASH` taken from the pins. It then adds our object libraries
  to `_duckdb` (`target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:...>)`, the
  spike's mechanism).
- Produces: `engine/cmake/duckdb_package.cmake`, which installs DuckDB's
  Python packages into the wheel:
  - `engine/duckdb-python/duckdb/` goes to `${SKBUILD_PLATLIB_DIR}/duckdb/`,
    except `_version.py`.
  - A generated `_version.py` takes its place. It is their file with the one
    line `__version__: str = _dist_version("duckdb")` replaced by
    `__version__: str = "2.0.1"` (the pinned tag without `v`). Configure
    fails with the message "duckdb/_version.py changed upstream: review the
    substitution in engine/cmake/duckdb_package.cmake" unless that line
    occurs exactly once.
  - A generated `_build_info.py` carries the same names duckdb-python's
    backend writes: the package and DuckDB versions and commits, from the
    pins.
  - `adbc_driver_duckdb/` and `_duckdb-stubs/` are copied unchanged.
  - Their own install rule places `_duckdb` at `${SKBUILD_PLATLIB_DIR}`.
- Produces: `pyproject.toml`:
  - `build-backend = "scikit_build_core.build"`; `cmake.source-dir =
    "engine"`; `build-dir = "build/{cache_tag}"`; `wheel.py-api = "cp312"`.
  - `wheel.packages = ["src/sqlearn"]`; the `duckdb` packages come from
    CMake's install, above.
  - The version comes from git through
    `scikit_build_core.metadata.setuptools_scm`, the same numbers hatch-vcs
    gives today.
  - `cmake.define`: `BUILD_EXTENSIONS = "core_functions;json;parquet;icu"`
    (Task 3 adds `sqlearn` and `LINK_EXTENSIONS`).
  - `tool.uv.cache-keys`: today's two, plus `engine/CMakeLists.txt`,
    `engine/cmake/**`, `engine/src/**`, `engine/extension/**` and
    `.gitmodules`.
  - The runtime `dependencies` keep numpy and lose `duckdb`.

- [ ] **Step 1: Write the failing tests** in `tests/engine/test_build.py`:
  - `test_duckdb_is_sqlearns_build`: `duckdb.__version__ == "2.0.1"`;
    `duckdb.build_info()["duckdb_commit"]` starts with `8d78114e90`; and
    `importlib.metadata.distribution("sqlearn")` lists `duckdb/__init__.py`
    among its files (no `duckdb` distribution is installed).
  - `test_the_official_extensions_are_compiled_in`:
    - for `core_functions`, `json`, `parquet` and `icu`,
      `duckdb_extensions()` reports `loaded`, with the install mode DuckDB
      2.0 reports for a statically linked extension (`STATICALLY_LINKED` in
      the spike);
    - one query each: `SELECT json_extract('{"a":1}', '$.a')`, a Parquet
      round trip (`COPY ... TO ... (FORMAT parquet)`, then `read_parquet`, in
      `tmp_path`), and `SELECT now() AT TIME ZONE 'Europe/London'`.
  - `test_the_version_substitution_refuses_a_changed_file`: `cmake -P` on
    the substitution with a stand-in `_version.py` that lacks the line fails
    with the message above; with the line twice it fails too.
- [ ] **Step 2: Run them:** FAIL (the official DuckDB 2.0.0 is installed).
- [ ] **Step 3: Write** `engine/CMakeLists.txt`, `duckdb_package.cmake` and
  the `pyproject.toml` changes. Then `uv lock` and `uv sync --locked`, which
  builds the module; time the first build with `time` and put it in the
  report.
- [ ] **Step 4: Run them:** PASS. Then `just full test` once: every
  existing test passes unchanged on our DuckDB 2.0.1, and every failure is
  named. A test that fails only because DuckDB 2.0.0 → 2.0.1 changed an
  answer is reported to the controller, never edited (ADR 0067).
- [ ] **Step 5: Measure** the rebuild after one commit: `git commit
  --allow-empty`, then `uv run --locked python -c 'import sqlearn'`. Put the
  time in the report; above 60 s, report it as a concern.
- [ ] **Step 6: Commit:** `build: build sqlearn with its duckdb inside, one
  package`.

### Task 3: the native module, the `sqlearn` extension, `sq.version()`

**Files:**

- Create:
  - `engine/src/core/version.{hpp,cpp}`, `engine/src/core/expects.hpp`,
    `engine/src/core/error.hpp`;
  - `engine/src/bindings/module.cpp`, `engine/src/bindings/connection.cpp`;
  - `engine/extension/sqlearn_config.cmake`,
    `engine/extension/CMakeLists.txt`,
    `engine/extension/src/sqlearn_extension.cpp`;
  - `src/sqlearn/_native.py`, `src/sqlearn/_native.pyi` (generated);
  - `tests/src/sqlearn/test__native.py`, `tests/engine/test_bindings.py`,
    `tests/engine/test_extension.py`, `tests/public_api.txt`.
- Modify: `engine/CMakeLists.txt` (`DUCKDB_EXTENSION_CONFIGS`,
  `LINK_EXTENSIONS`), `pyproject.toml` (`LINK_EXTENSIONS =
  "core_functions;json;parquet;icu;sqlearn"`), `src/sqlearn/__init__.py`
  (`version`; the start-up check at import), the reference page that lists
  top-level functions, `justfile` (`stubs`, `check-stubs`,
  `api-snapshot`).

**Interfaces:**

- Produces (C++, namespace `sq`):
  - `struct core::BuildIdentity { std::string sqlearn_version,
    duckdb_version, duckdb_commit, compiler, build_type; }`;
  - `core::BuildIdentity core::build_identity() noexcept`;
  - `std::string core::describe(const core::BuildIdentity&)`, the one line
    `sqlearn <version>, DuckDB <duckdb_version> (<commit[:10]>), <compiler>,
    <build_type>`;
  - `SQ_EXPECTS(cond)`, which throws `core::PreconditionError` carrying the
    condition's text and `std::source_location`;
  - `class core::Error : public std::runtime_error`, carrying `why()` and
    `fix()`.
- Produces (the `sqlearn` extension, statically linked, in every
  database):
  - The SQL function `sqlearn_version()` returns `core::describe(...)`.
  - At load, the extension sets `autoinstall_known_extensions` to false
    unless the user set it when opening the database. Find in DuckDB 2.0's
    `DBConfig` how a value the user gave is told from a default (the user's
    options map, or whatever 2.0 has); if no way exists, report
    `NEEDS_CONTEXT` rather than override the user.
- Produces (Python, `sqlearn._native`):
  - `build_identity() -> dict[str, str]`;
  - `count_rows(con: duckdb.DuckDBPyConnection, table: str) -> int`, which
    runs `SELECT count(*)` through DuckDB's C++ API on the connection behind
    `con`, under `ConnectionLockGuard`, with `SQ_EXPECTS(!table.empty())`;
  - `roundtrip(con) -> duckdb.DuckDBPyConnection`, returning the same object;
  - `load(path: str) -> ModuleType`, used at import.
- Errors:
  - Errors DuckDB raises stay DuckDB's own exceptions, through its
    translators: a closed connection is `duckdb.ConnectionException`.
  - `core::Error` and `core::PreconditionError` become
    `sqlearn.errors.InternalError`, with `Why:` and `Fix:` lines.
  - Any other C++ exception becomes an `InternalError` naming it.
  - Nothing crashes the interpreter.
- Produces (public): `sq.version() -> str`, returning `core::describe`'s
  line, with a numpydoc docstring and a doctest example using `...`.
- Produces: the start-up check. `import sqlearn` imports `_duckdb`, then
  calls `_native.load(_duckdb.__file__)`. A file without `PyInit__native`
  raises `ImportError`, chained from the loader's error, whose message has:
  - `Why: the duckdb module is not sqlearn's build (<path>)`;
  - `Fix: uv sync --reinstall-package sqlearn`;
  - the sentence that a package needing the official `duckdb` needs an
    environment of its own (ADR 0061).

- [ ] **Step 1: Write the failing tests:**
  - `test_version_answers_from_cpp`: `sq.version()` contains
    `sq.__version__`, `duckdb.__version__` and the pinned commit's first
    ten digits, and equals `SELECT sqlearn_version()`'s answer on a new
    connection.
  - `test_every_database_has_the_sqlearn_extension`: `duckdb.connect()`,
    `duckdb.connect("<tmp_path>/a.db")` and `duckdb.sql(...)` each answer
    `SELECT sqlearn_version()` with no `LOAD`; `duckdb_extensions()` lists
    `sqlearn` as loaded.
  - `test_nothing_downloads_by_itself`:
    `current_setting('autoinstall_known_extensions')` is false on a new
    connection.
  - `test_a_user_who_asks_for_downloads_keeps_them`:
    `duckdb.connect(config={"autoinstall_known_extensions": True})` reads
    true, and `SET autoinstall_known_extensions = true` on a default
    connection reads true.
  - `test_an_extension_the_user_installed_loads`: with
    `extension_directory` set to `tmp_path`, `LOAD` of a missing extension
    fails with a message naming the local path, not a download attempt.
  - `test_a_users_connection_reaches_cpp_and_back`: `con =
    duckdb.connect(); con.execute("CREATE TABLE t AS SELECT * FROM
    range(5)")`; then `count_rows(con, "t") == 5` (also through a cursor),
    and `roundtrip(con) is con`.
  - `test_a_connection_to_another_database_sees_its_own_tables`:
    `count_rows` on a second `duckdb.connect()` raises DuckDB's catalog
    error for `t`.
  - `test_a_closed_connection_raises_duckdbs_error`: `con.close()`, then
    `count_rows(con, "t")` raises `duckdb.ConnectionException`, and the
    interpreter survives.
  - `test_a_precondition_is_an_internal_error`: `count_rows(con, "")`
    raises `sq.errors.InternalError` whose message contains `Why:`, `Fix:`
    and the condition's text.
  - `test_a_busy_connection_never_crashes`: hold an unfinished
    `con.execute("SELECT * FROM range(10)")`, then call `count_rows(con,
    "t")`. The test pins whichever DuckDB 2.0.1 does, a count or a DuckDB
    error, and it is never a crash.
  - `test_the_official_duckdb_is_refused`: in a subprocess, `import
    sqlearn` with `_duckdb` replaced in `sys.modules` by a module whose
    `__file__` is numpy's `_multiarray_umath` extension. It exits non-zero,
    and stderr has `ImportError`, `Why:` and `Fix:`.
  - `test_the_stubs_match_the_module`: `just check-stubs` (nanobind's
    `stubgen` into a temp file) equals the committed `_native.pyi`.
  - `test_the_public_api_is_the_recorded_one` (spec §3.9): every name in
    `sq.__all__` and in each submodule's `__all__`, with its
    `inspect.signature`, one per line, equals `tests/public_api.txt`.
    `just api-snapshot` writes the file once, before `version` is added,
    and it gains exactly `version()` in this task. A later change fails
    until the file is regenerated and the commit says why (ADR 0003, 0067).
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement:**
  - the C++ version strings from CMake definitions: `SQLEARN_VERSION` from
    `SKBUILD_PROJECT_VERSION_FULL`, the DuckDB ones from the pins, the
    compiler from `CMAKE_CXX_COMPILER_ID` and its version, and the build
    type;
  - the extension, as the spike did: `build_static_extension` and
    `DUCKDB_CPP_EXTENSION_ENTRY(sqlearn, loader)`, with hidden visibility;
  - the bindings: `NB_MODULE(_native, m)` through `_duckdb_dependencies`
    (the same `NB_DOMAIN`);
  - `_native.load`, the start-up check and `sq.version`.
- [ ] **Step 4: Run them:** PASS; then `just full test`: PASS.
- [ ] **Step 5: Commit:** `feat: sq.version answers from the engine`.

### Task 4: presets, compilers and the group targets

**Files:**

- Create: `engine/CMakePresets.json`, `engine/cmake/warnings.cmake`,
  `engine/cmake/hardening.cmake`, `engine/cmake/toolchain-llvm.cmake`,
  `engine/cmake/groups.cmake`, `engine/tests/CMakeLists.txt`,
  `engine/tests/must_not_compile/{conversion,buffer,fallthrough}.cpp`
- Modify: `engine/CMakeLists.txt`, `justfile` (`build-engine preset="dev"`,
  `test-engine preset="dev"`, `probe-cxx26`)

**Interfaces:**

- Produces: presets `dev` (`-O1 -g`, ASan+UBSan,
  `-ftrivial-auto-var-init=pattern`, libc++ hardening `extensive`),
  `debug` (`-O0 -g`), `release` (`-O2`, `-mcpu=apple-m1` on macOS, libc++
  hardening `fast`, `-ftrivial-auto-var-init=zero`, `-gline-tables-only`;
  ThinLTO only if Task 2's measured build allows it), `profile` (`release`
  plus `-g -fno-omit-frame-pointer`), and `llvm-dev` (`dev` with Homebrew
  LLVM through `toolchain-llvm.cmake`: `-isysroot $(xcrun
  --show-sdk-path)`). Tasks 8–10 add `tsan`, `lsan`, `tysan`, `fuzzing`,
  `coverage`. Build dirs `engine/build/<preset>`; each writes
  `compile_commands.json`.
- Produces: `sq_add_group(<name> SOURCES ... TESTS ...)` in `groups.cmake`:
  an object library `sq_<name>`, the strict warnings and hardening on it,
  and one Catch2 test program `test_<name>` registered with CTest under the
  label `<name>`.
- Produces: `just probe-cxx26`: compiles a file printing `__cplusplus`,
  `__cpp_reflection`/`__cpp_impl_reflection`, `__cpp_contracts`,
  `__cpp_lib_linalg` under Apple clang, Homebrew LLVM and GCC (if on PATH),
  as spec §3.8's table.
- Produces: a trial of `-Wlifetime-safety` (experimental, spec §3.9) on
  our sources: kept in the warnings when it builds clean and gives no
  false finding on Tasks 3–5, else left out with the reason in
  `warnings.cmake`.

- [ ] **Step 1: Write the failing tests:** `engine/tests/CMakeLists.txt`
  registers each `must_not_compile/*.cpp` as a CTest that builds it through
  `try_compile`-style `cmake --build` of a one-file target with `WILL_FAIL`:
  an implicit narrowing (`-Wconversion`), pointer arithmetic outside `raw/`
  (`-Wunsafe-buffer-usage`), an unannotated fallthrough. In
  `tests/engine/test_presets.py`: `test_every_preset_named_in_the_spec_exists`
  (`dev`, `debug`, `release`, `profile`, `llvm-dev` in
  `CMakePresets.json`), `test_no_preset_sets_fast_math`.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement** the presets, the flag files and
  `sq_add_group`; move Task 3's `core` sources into `sq_add_group(core
  ...)`.
- [ ] **Step 4: Run:** `just build-engine dev`, `just build-engine
  llvm-dev`, `just test-engine dev`: the three must-not-compile tests pass
  (they fail to compile); `just probe-cxx26` prints the table.
- [ ] **Step 5: Commit:** `build: cmake presets and the group targets`.

### Task 5: the skeleton's groups, their C++ tests and a benchmark

**Files:**

- Create: `engine/src/raw/buffer.hpp` (+ `.cpp` if needed),
  `engine/src/core/parse_version.{hpp,cpp}`,
  `engine/tests/core/test_version.cpp`,
  `engine/tests/core/test_parse_version.cpp`,
  `engine/tests/raw/test_buffer.cpp`, `engine/bench/bench_buffer.cpp`

**Interfaces:**

- Produces: `template <class T> class sq::raw::Buffer` (owning,
  64-byte-aligned, `explicit Buffer(std::size_t n)`, `std::span<T> span()
  noexcept`, `std::size_t size() const noexcept`, move-only, no raw
  `new`); `struct sq::core::Version { int major, minor, patch; std::string
  pre; }`, `std::expected<Version, ParseError>
  sq::core::parse_version(std::string_view text) noexcept`, `std::string
  format(const Version&)` (PEP 440 subset sqlearn's versions use:
  `0.1.dev597`, `1.0.0`, `2.0.1`).

- [ ] **Step 1: Write the failing tests:** Catch2: `parse_version` of
  `"2.0.1"`, `"0.1.dev597"`, `""` (error), `"1..0"` (error), `"99999999999.0.0"`
  (error: overflow); RapidCheck: `parse_version(format(v)) == v` for any
  valid `Version`; `Buffer`: size, alignment (`reinterpret_cast` check lives
  in `raw/` tests), move leaves the source empty, `span()` covers `size()`
  elements.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement** both groups through `sq_add_group(core ...)`
  and `sq_add_group(raw ...)`; `bench_buffer` (nanobench, filling and summing
  a `Buffer<double>` of 1e6) builds in `release` and runs under `just
  bench-engine`.
- [ ] **Step 4: Run:** `just test-engine dev` (ASan+UBSan): PASS;
  `just test-engine llvm-dev`: PASS; `just bench-engine` prints a table.
- [ ] **Step 5: Commit:** `feat: the engine's core and raw groups`.

### Task 6: C++ tests per group in the checks

**Files:**

- Modify: `validation/_checks.py` (the `test` task gains a step running
  `python -m validation._ctest`), `justfile`
- Create: `validation/_ctest.py`, `tests/validation/test__ctest.py`,
  `tests/checks/test_engine_groups.py`

**Interfaces:**

- Consumes: Task 4's CTest labels (one per group), Task 1's digest.
- Produces: `validation._ctest.run(preset: str, root: Path, *, everything:
  bool = False) -> int`: builds the preset (Ninja rebuilds only what
  changed), lists the test programs (`ctest --show-only=json-v1`), hashes
  each program's binary, runs (`ctest -L <group>`) only those whose hash has
  no passed record in `sqlearn-checks/ctest-<preset>.json` (same record
  rules as `_checks`: 20 kept, temporary file then `os.replace`, a failed
  run records nothing), prints `<group>: unchanged since a passed run` for
  the rest.

- [ ] **Step 1: Write the failing tests:**
  `test_a_change_to_one_groups_file_runs_that_group_only` (spec §6 step
  2): on a scratch copy of `engine/` limited to two stand-in groups, edit a
  `raw` source; `run` rebuilds and runs `test_raw`; `test_core` prints
  unchanged. `test_a_failed_group_records_nothing`,
  `test_everything_runs_every_group`.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement** `_ctest.py`; the `test` task's inputs gain
  `engine/` (gitlinks included, Task 1) and its steps run `_ctest` with
  `dev` before the Python passes.
- [ ] **Step 4: Run them:** PASS; `just test` twice: the second prints
  every group and the Python passes unchanged.
- [ ] **Step 5: Commit:** `test: run a group's c++ tests when its binary
  changed`.

### Task 7: clang-tidy, include-what-you-use, headers alone, formatting

**Files:**

- Create: `engine/.clang-tidy`, `engine/src/raw/.clang-tidy`,
  `engine/.clang-format`, `.gersemirc`, `engine/iwyu.imp`,
  `engine/cmake/headers_alone.cmake`, `engine/tests/must_not_pass_tidy/`
- Modify: `validation/_checks.py` (a whole task `tidy`; C++ files in
  `format`), `pyproject.toml` (`gersemi` in the `lint` group), `justfile`

**Interfaces:**

- Produces: `.clang-tidy` with `bugprone-*`, `cppcoreguidelines-*`,
  `performance-*`, `clang-analyzer-*`,
  `readability-function-cognitive-complexity` (threshold 15),
  `modernize-use-nodiscard`, `google-explicit-constructor`,
  `misc-include-cleaner`, and `WarningsAsErrors: '*'`; each disabled check
  listed with its reason as a comment. `raw/.clang-tidy` inherits and relaxes
  only `cppcoreguidelines-pro-bounds-*` and
  `cppcoreguidelines-pro-type-reinterpret-cast`.
- Produces: TASKS entry `tidy` (whole; inputs `engine/src/**`,
  `engine/tests/**`, `engine/.clang-tidy`, `engine/src/raw/.clang-tidy`,
  `engine/iwyu.imp`, `engine/cmake/**`; steps: `clang-tidy -p
  engine/build/llvm-dev` over our sources, `include-what-you-use` through
  `iwyu_tool.py`, the headers-alone target build). `format` gains
  `clang-format --dry-run -Werror` on `engine/**/*.{cpp,hpp}` (submodules
  excluded) and `gersemi --check` on `CMakeLists.txt` and `*.cmake`.

- [ ] **Step 1: Write the failing tests:**
      `test_the_task_table_names_every_check` grows to the eight names;
      `tests/engine/test_tidy.py`: `test_a_raw_new_fails_tidy` and
      `test_pointer_arithmetic_outside_raw_fails_tidy` (clang-tidy on files
      under `must_not_pass_tidy/` exits non-zero naming the check);
      `test_every_header_compiles_alone` (the headers-alone target lists one TU
      per `engine/src/**/*.hpp`).
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement**; fix what tidy and IWYU find in Tasks 3–5's code.
- [ ] **Step 4: Run:** `just full tidy`, `just full format`: PASS.
- [ ] **Step 5: Commit:** `test: clang-tidy, iwyu and formatting for the
  engine`.

### Task 8: the sanitizers and the steady-memory test

**Files:**

- Modify: `engine/CMakePresets.json` (`tsan`, `lsan`, `tysan`; `lsan` and
  `tysan` with Homebrew LLVM), `justfile` (`sanitize`), `pyproject.toml`
  (marker `release`)
- Create: `engine/tests/canary/{asan,ubsan,tsan,lsan,tysan}.cpp`,
  `tests/engine/test_steady_memory.py`

**Interfaces:**

- Produces: `just sanitize` builds each sanitizer preset and runs every
  group's tests under it (`ASAN_OPTIONS=detect_leaks=1` only with Homebrew
  LLVM; HANDOFF trap); a canary per sanitizer, registered with `WILL_FAIL`,
  proving the sanitizer is on (a heap overflow, a signed overflow, a data
  race, a leak, a type-punned store).
- Produces: `test_memory_levels_off` (marked `slow`): 100,000 calls of
  `count_rows` and `build_identity` in a loop of 10 rounds; the resident
  set after round 10 is within 5 % of round 2 (measured twice per round,
  HANDOFF trap on `ru_maxrss`; use `resource`-free RSS from `ps -o rss=`
  of the process, or `psutil` only if already locked — it is not: use `ps`).

- [ ] **Step 1: Write the canaries and the steady-memory test.**
- [ ] **Step 2: Run** `just sanitize`: every canary fails as expected, every
      group passes;
      `uv run --locked pytest -m slow tests/engine/test_steady_memory.py`: PASS.
- [ ] **Step 3: Commit:** `test: the sanitizers and the steady-memory test`.

### Task 9: fuzzing

**Files:**

- Create: `engine/fuzz/fuzz_parse_version.cpp`,
  `engine/fuzz/corpus/parse_version/` (seed files), `engine/fuzz/CMakeLists.txt`
- Modify: `engine/CMakePresets.json` (`fuzzing`: Homebrew LLVM,
  `-fsanitize=fuzzer,address,undefined`), `justfile` (`fuzz seconds="60"`),
  `engine/tests/CMakeLists.txt` (corpus replay)

**Interfaces:**

- Produces: `just fuzz` runs each fuzz target for `seconds` with
  `-max_total_time`, merging new inputs into the corpus (`-merge=1`); a
  crash leaves its input in `engine/fuzz/corpus/<target>/` and fails. A
  CTest `replay_parse_version` (label `core`) runs the corpus through
  `parse_version` in every `dev` run, so found cases stay tested.

- [ ] **Step 1: Write** the target (any bytes into `parse_version`; on
  success, `parse_version(format(v)) == v` else `abort`) and the seeds
  (`2.0.1`, `0.1.dev597`, empty, `1..0`, a 1 MiB string of digits).
- [ ] **Step 2: Run** `just fuzz 60`: no crash; `just test-engine dev`
  runs the replay: PASS.
- [ ] **Step 3: Commit:** `test: fuzz the version parser`.

### Task 10: coverage and mutation testing

**Files:**

- Modify: `engine/CMakePresets.json` (`coverage`: `-fprofile-instr-generate
  -fcoverage-mapping`), `justfile` (`coverage-engine`, `mutate-engine`)
- Create: `engine/mull.yml`

**Interfaces:**

- Produces: `just coverage-engine` runs every group's tests under the
  `coverage` preset and fails below 95 % of lines of `engine/src/` outside
  `bindings/` (the bindings run from Python, uninstrumented; the gate's level
  is the builder's call, spec §5, set to match the Python floor). `just
  mutate-engine` runs Mull on `test_core` and `test_raw` and fails if any
  mutant survives without a recorded reason in `mull.yml`.

- [ ] **Step 1:** Install check: Mull's release for macOS arm64 that supports
  Homebrew LLVM 23 (or Apple clang 21). If none exists, record it, skip the
  Mull half (the coverage gate still lands) and report
  `DONE_WITH_CONCERNS` naming what would be needed.
- [ ] **Step 2: Run** both recipes: PASS (add the tests a surviving mutant
  shows are missing).
- [ ] **Step 3: Commit:** `test: coverage gate and mutation testing for the
  engine`.

### Task 11: crash readiness and the third-party file

**Files:**

- Create: `engine/src/crash/handler.{hpp,cpp}`,
  `engine/tests/crash/test_handler.cpp`, `THIRD_PARTY.md`, `NOTICE`,
  `validation/_licences.py`, `tests/validation/test__licences.py`
- Modify: `engine/src/bindings/module.cpp` (installs the handler),
  `justfile` (`check-licences`; gitleaks in `pre-commit`)

**Interfaces:**

- Produces: `sq::crash::install(std::filesystem::path dir) noexcept`:
  on SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT writes
  `<dir>/sqlearn-crash-<pid>.txt` (sqlearn and DuckDB versions, build
  identity, signal, stack trace through cpptrace's signal-safe API), then
  restores and re-raises the previous handler, so Python's `faulthandler`
  and the user's own handlers still run. Never sends anything (ADR 0006).
  The module installs it at load into `$XDG_STATE_HOME/sqlearn` or
  `~/Library/Logs/sqlearn` (macOS), `~/.local/state/sqlearn` otherwise.
- Produces: `THIRD_PARTY.md`: one row per compiled-in library (DuckDB and
  each library under its `third_party/` that the build compiles,
  duckdb-python, nanobind and robin-map, cpptrace and its symbol backend):
  version, licence (SPDX), licence text or a link to the file in the
  submodule. `NOTICE`: each library's notices.
- Produces: `just check-licences` (`python -m validation._licences`): every
  row's SPDX is in the ADR 0066 list (MIT, BSD-2-Clause, BSD-3-Clause,
  Apache-2.0, PSF-2.0, BSL-1.0, Zlib, Unicode-3.0, ISC); every compiled
  library is listed (the libraries the `_duckdb` target links, from CMake's
  `--graphviz` output); numpy's `License-Expression` from its metadata is in
  the list. `gitleaks dir` runs on the hook's export in `pre-commit`.

- [ ] **Step 1: Write the failing tests:** Catch2 `crash` group, in a child
  process (`fork` on macOS/Linux): a deliberate null write after `install`
  leaves a report naming the signal and `sq::crash` frames, and the parent
  sees the child die by that signal (the previous handler ran);
  `test__licences.py`: a GPL row fails, a missing library fails, the real
  file passes.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement**; write `THIRD_PARTY.md` and `NOTICE` from the
  submodules' licence files.
- [ ] **Step 4: Run them:** PASS; `just check-licences`: PASS; a staged file
  holding a fake AWS key is refused by the hook (`tests/githooks/`).
- [ ] **Step 5: Commit:** `feat: a local crash report and the third-party
  file`.

### Task 12: SQL tests with DuckDB's sqllogictest

**Files:**

- Create: `engine/sqllogic/CMakeLists.txt`,
  `engine/extension/test/sql/sqlearn_version.test`
- Modify: `engine/CMakePresets.json` (preset `sqllogic`),
  `engine/extension/sqlearn_config.cmake` (`LOAD_TESTS`), `validation/_ctest.py`
  (label `sql`), `justfile` (`test-sql`)

**Interfaces:**

- Consumes: Task 3's extension, Task 6's `_ctest.run`.
- Produces: `engine/sqllogic/CMakeLists.txt`, a CMake project of ours that
  `add_subdirectory`s DuckDB itself (`engine/duckdb-python/external/duckdb`,
  not duckdb-python). It sets `BUILD_UNITTESTS=ON` and
  `DUCKDB_EXTENSION_CONFIGS` to our config, as DuckDB's own extension template
  builds an extension's SQL tests. The preset `sqllogic` builds it into
  `engine/build/sqllogic`.
- Produces: DuckDB's `unittest` program, registered with CTest under the label
  `sql` and running `engine/extension/test/sql/*.test`; `_ctest` reruns it
  when its binary changed. `just test-sql` runs it directly.
- Produces: `sqlearn_version.test`:
  - `require sqlearn`;
  - `SELECT sqlearn_version() LIKE 'sqlearn %, DuckDB v2.0.1 (8d78114e90)%'`
    answers `true`;
  - calling it with an argument is a binder error.

- [ ] **Step 1: Write the test file.**
- [ ] **Step 2: Run** `just test-sql`: FAIL (no `sqllogic` preset).
- [ ] **Step 3: Implement** the project and the preset. If DuckDB's `unittest`
  cannot be built this way without editing DuckDB's files, stop and report
  `BLOCKED`; never patch DuckDB. Record the first build's time in the report.
- [ ] **Step 4: Run** `just test-sql`: PASS; `just test` runs it once, then
  reports `sql: unchanged since a passed run`.
- [ ] **Step 5: Commit:** `test: sqllogictest for the sqlearn extension`.

### Task 13: the editor tools, the tiers and the docs

**Files:**

- Create: `.clangd`, `docs/adr/` amendments (lines only)
- Modify: `justfile` (`done`, `verify`), `validation/_checks.py`,
  `CLAUDE.md` (Checks; rules: the toolchain), `docs/architecture/layout.md`
  (`engine/`), `docs/architecture/setup.md` (toolchain: `brew install llvm
  cmake ninja ccache include-what-you-use gitleaks`, the recipes),
  `docs/architecture/testing.md` (C++ tests, groups, sanitizers, fuzzing),
  `docs/adr/0061-*.md`, `docs/adr/0065-*.md`, `docs/adr/0008-*.md`
  ("Amended by" lines, spec §4), `HANDOFF.md`

**Interfaces:**

- Produces: `just done` runs the eight tasks, the C++ groups through
  `test`; `just verify` adds `sanitize`, `fuzz 60`, `coverage-engine`,
  `mutate-engine`, the steady-memory test, `check-licences`, `just full`
  of every task, `test-all`, `test-python-versions`. `.clangd` points at
  `engine/build/llvm-dev/compile_commands.json`.

- [ ] **Step 1:** Update the recipes; `tests/checks` PASS.
- [ ] **Step 2:** Update the docs and the ADR lines (no reason the spec does
  not give, HANDOFF trap); `just fmt`, `just check`.
- [ ] **Step 3:** Run `just done` and then `just verify` once each (logs in
  the job's tmp dir): PASS, and the proof for spec §6 step 2, each line:
  `sq.version()` from C++; one DuckDB (`count_rows`); the start-up check;
  every existing test unchanged; each C++ tool run and passing; Apple clang
  and Homebrew LLVM builds; the C++26 probe; one group's change running that
  group only.
- [ ] **Step 4:** Post the proof table on #79 (`gh issue comment 79 --repo
  glaucis/sqlearn --body-file <file>`; do not close #79); update
  `HANDOFF.md`; commit `docs: Phase 1 step 2, the build, shown`.
