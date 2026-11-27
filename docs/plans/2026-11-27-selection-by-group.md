---
type: plan
tags: [checks, selection, tests, validation, benchmarks, groups, plan]
summary: "Plan for selecting by group: a CMake manifest of the C++ groups and what they claim, comment-free per-group fingerprints of the module, per-group records for the validation runners and the Python test sets, the module fingerprint in the other checks, the coverage audit, and the benchmarks' due list."
related: [docs/specs/selection-by-group.md, validation/_checks.py, validation/_ctest.py, validation/_record.py, engine/cmake/groups.cmake]
---
# Selecting by group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Python test, validation runner and benchmark reruns only when
a comment-free fingerprint of the C++ groups it uses, or its own files,
changed since it passed.

**Architecture:** CMake writes a manifest of the groups and what each claims
(`sq_groups.json` in each build directory). `validation/_groups.py` turns the
wheel build's compile entries into one fingerprint per group (sources and the
headers they read, comments stripped, line numbers kept, flags normalised,
closed over `DEPENDS`) and a shared part. The validation's records, a new
per-set pytest runner, the other checks' configuration, the audit and the
benchmarks' due list all take their identities from it.

**Tech Stack:** Python 3.12 (`validation/`), CMake 3.29, Ninja, Apple clang
and Homebrew LLVM (`clang -fpreprocessed`, `llvm-profdata`, `llvm-cov`),
pytest, `just`.

**Spec:** `docs/specs/selection-by-group.md` (approved by Tomas, 2026-11-27).

## Global Constraints

- uv only: `uv run --locked`, never pip or a bare `python` (ADR 0001).
- Every task runs through `just` (ADR 0008).
- British English in prose, American spelling in identifiers (ADR 0010).
- Nothing needs the network (ADR 0006).
- No check runs a benchmark; a benchmark runs only on Tomas's go-ahead
  (ADR 0072). Tests of the benchmark tooling use a stand-in program, never a
  real benchmark.
- Unknown means affected: anything the fingerprint cannot read reruns what
  it could affect, with a line saying why (spec §5.6).
- A comment that adds or removes a line in a C++ file changes its group's
  fingerprint; one edited within its lines does not (spec §5.1).
- Tests are named in `GLOSSARY.md` terms, through public seams
  (`_groups`' functions, `_checks.run`, `validation.__main__.main`), on
  scratch repositories as `tests/validation/` already builds them.
- Before each commit `just check` and `just test` pass; `just fmt` first;
  commitlint scopes only `hooks`, `site`, `deps`; lines at most 72.
- While a test or validation run is going in a worktree, start no other
  `uv run` there (HANDOFF).

## Review Focus

1. **A new source file in a group that the compile entries do not list yet**
   (added, not rebuilt): expect every Python test and runner to rerun, not a
   stale match. Test in Task 2.
2. **A header of `core` included by `raw`**: a change to it must change both
   `core`'s and `raw`'s fingerprints, through ownership and `DEPENDS`, never
   be counted twice or missed. Test in Task 2.
3. **A Python test file that belongs to no set** (a new `tests/src/sqlearn/x/`
   no group claims): expect it in the unclaimed set, which depends on every
   group; a test file outside `tests/` sets and tooling refuses the run with
   a `Fix:`. Test in Task 4.
4. **A link-only change** (a library linked or a linker flag in a CMake
   file, no compile flag changed): expect the shared part to change, since
   compile entries alone do not show it. Test in Task 2.
5. **Old records from before this change** (runner records with the
   `engine` key): expect one rerun, never a crash or a false match. Test in
   Task 3.

---

### Task 1: The groups' manifest

**Files:**
- Modify: `engine/cmake/groups.cmake` (`sq_add_group`)
- Modify: `engine/CMakeLists.txt` (write the manifest after the groups)
- Test: `tests/engine/test_groups_manifest.py`

**Interfaces:**
- Produces: `sq_add_group(<name> SOURCES … [DEPENDS …] [TESTS …] [DATA …]
  [ARGS …] [PYTHON_TESTS <dir>…] [VALIDATION <runner>…] [BENCH <name>…])`.
- Produces: `<build>/sq_groups.json`, written at configure:
  `{"groups": [{"name": str, "dir": "engine/src/<name>", "depends": [str],
  "python_tests": [str], "validation": [str], "bench": [str]}],
  "shared": ["engine/src/bindings", "engine/extension"]}`, groups in
  definition order, paths relative to the repository.

- [ ] **Step 1: Write the failing tests** in `test_groups_manifest.py`:
  `test_the_manifest_names_every_group` (the wheel build's
  `build/cpython-312/sq_groups.json` lists `core`, `raw`, `crash`, with
  `raw.depends == ["core"]`, `crash.depends == ["core", "raw"]`, every
  claim list empty today); `test_every_source_directory_is_a_group_or_shared`
  (each directory under `engine/src/` is a group's `dir` or in `shared`).
- [ ] **Step 2: Run them:** `uv run --locked pytest
  tests/engine/test_groups_manifest.py -v`. Expected: FAIL, no manifest.
- [ ] **Step 3: Implement** the three keywords as `cmake_parse_arguments`
  multi-values appended to a global property `SQ_GROUPS_JSON`, and one
  `file(CONFIGURE … @ONLY)` or `file(WRITE …)` at the end of
  `engine/CMakeLists.txt` that writes the JSON; refuse with `FATAL_ERROR` and
  a `Fix:` a `PYTHON_TESTS` path that does not exist.
- [ ] **Step 4: Run them:** PASS.
- [ ] **Step 5: Commit:** `feat: a manifest of the C++ groups and their claims`.

### Task 2: The module's fingerprints

**Files:**
- Create: `validation/_groups.py`
- Test: `tests/validation/test__groups.py`

**Interfaces:**
- Consumes: Task 1's manifest; `_ctest._arguments`, `_ctest._DROP`,
  `_ctest._DROP_WITH_VALUE`, `_ctest._read_by_compiler`,
  `_ctest._compile_entries`, `_ctest.compiler`; `_checks._gitlinks`.
- Produces:
  - `@dataclass(frozen=True) class Group: name: str; dir: str;
    depends: tuple[str, ...]; python_tests: tuple[str, ...];
    validation: tuple[str, ...]; bench: tuple[str, ...]`
  - `class Unreadable(Exception)`: its message says what could not be read
    and is printed as the reason everything reruns.
  - `def load(build: Path) -> tuple[dict[str, Group], tuple[str, ...]]`: the
    groups and the shared directories; `Unreadable` without the manifest.
  - `def stripped(path: Path) -> str`: the file with its comments removed
    and its line numbers kept (`clang -fpreprocessed -dD -E`, line markers
    kept; `/opt/homebrew/opt/llvm/bin/clang` or `xcrun clang`); CMake files
    are never passed to it.
  - `@dataclass(frozen=True) class Fingerprints: shared: str;
    groups: dict[str, str]`
  - `def fingerprints(root: Path, build: Path) -> Fingerprints`: raises
    `Unreadable` when the manifest, `compile_commands.json`, the link
    command or a listed file is missing.
  - `def closure(groups: dict[str, Group], names: Iterable[str]) -> set[str]`
  - `def identity(prints: Fingerprints, groups: dict[str, Group],
    uses: Iterable[str] | None) -> str`: SHA-256 of the shared part and the
    fingerprints of `closure(uses)`, every group when `uses` is None.
  - `WHEEL_BUILD = Path("build/cpython-312")`, relative to the root.

A group's fingerprint hashes, sorted: for each compile entry whose source is
under its `dir`, the normalised argv and `stripped()` of the source and of
every file `_read_by_compiler` lists that is under `engine/src/<its dir>` or
inside the build directory (generated headers); then the fingerprints of its
`depends`. A header under another group's `dir` counts for that group only.
The shared part hashes: `stripped()` of every file under the shared
directories, the gitlinks under `engine/`, `pyproject.toml`'s
`[build-system]` and `[tool.scikit-build]` tables, `_ctest.compiler(build)`,
and the module's link command (`ninja -C <build> -t commands _duckdb`, its
last line, normalised as a compile entry). A source file under a group's
`dir` that no compile entry lists raises `Unreadable`.

- [ ] **Step 1: Write the failing tests**, on a scratch repository with two
  groups (`a`, and `b` with `depends=["a"]`), a hand-written manifest and
  `compile_commands.json`, real files and the real clang:
  - `test_a_comment_edited_within_its_line_keeps_every_fingerprint`
    (`// x` → `// y` in `a/one.cpp`: `fingerprints()` equal);
  - `test_a_comment_line_added_changes_its_group_and_those_built_on_it`
    (`a`'s and `b`'s change, the shared part does not);
  - `test_a_code_change_in_b_leaves_a_alone`;
  - `test_a_header_of_a_read_by_b_changes_both_once` (Review Focus 2);
  - `test_a_compile_flag_changes_the_group`,
    `test_the_link_command_changes_the_shared_part` (Review Focus 4),
    `test_a_pin_build_table_or_compiler_changes_the_shared_part`;
  - `test_a_source_no_compile_entry_lists_is_unreadable` (Review Focus 1);
  - `test_closure_follows_depends` and
    `test_identity_of_no_uses_covers_every_group`.
- [ ] **Step 2: Run them:** `uv run --locked pytest
  tests/validation/test__groups.py -v`. Expected: FAIL, no module.
- [ ] **Step 3: Implement** `validation/_groups.py` with the interfaces
  above.
- [ ] **Step 4: Run them:** PASS; also `uv run --locked python -c "from
  pathlib import Path; from validation import _groups;
  print(_groups.fingerprints(Path('.'), Path('build/cpython-312')))"` prints
  three groups and a shared part.
- [ ] **Step 5: Commit:** `feat: comment-free fingerprints of the C++ groups`.

### Task 3: The validation runners' records

**Files:**
- Modify: `validation/_record.py` (`engine`, `environment`)
- Modify: `validation/__main__.py` (`main`)
- Test: `tests/validation/test__record.py`, `tests/validation/test___main__.py`

**Interfaces:**
- Consumes: `_groups.load`, `_groups.fingerprints`, `_groups.identity`,
  `_groups.Unreadable`, `_groups.WHEEL_BUILD`.
- Produces: `def engine(root: Path, runner: str) -> str`: `identity()` of the
  groups whose `validation` names `runner` (its module name's last part,
  `validate_pca`), every group when none does; `"unreadable"` plus a printed
  reason on `Unreadable`, which no record matches.
- Produces: `def environment(base: dict[str, str], root: Path, runner: str)
  -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests:** replace the `engine_repo` tests
  with `test_a_comment_edit_keeps_every_runners_record`,
  `test_a_claimed_runner_reruns_for_its_group_alone` (a manifest where `b`
  claims `GOOD`: a change in `b` reruns `GOOD`, and `ODD`, unclaimed, too; a
  change in `a`, which `b` depends on, reruns both),
  `test_an_unreadable_build_reruns_every_runner`, and
  `test_a_record_from_before_the_groups_is_rerun_once` (a record whose
  environment has the old `engine` key: rerun, then matched; Review
  Focus 5). Rewrite `test_a_changed_engine_reruns_every_runner` on a group
  source.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement**; `main` computes the fingerprints once and passes
  them in; `ENGINE_BUILD` and `engine()`'s file listing go from
  `_record.py`.
- [ ] **Step 4: Run** `uv run --locked pytest tests/validation -q`: PASS.
- [ ] **Step 5: Commit:**
      `feat: rerun a validation runner for its groups alone`.

### Task 4: The Python tests by set

**Files:**
- Create: `validation/_pytest_sets.py`
- Modify: `validation/_checks.py` (the `test` task, `TEST_INPUTS`)
- Test: `tests/validation/test__pytest_sets.py`, `tests/checks/test_tasks.py`

**Interfaces:**
- Consumes: `_groups.*`; `_checks._listed`, `_checks._hashes`,
  `_checks.load`, `_checks.save`, `_checks.Record`, `_checks.record_dir`,
  `_checks.place`; `_PYTEST_PASSES` (moved here from `_checks.py`).
- Produces: `TOOLING = ("tests/checks", "tests/githooks", "tests/validation",
  "tests/engine", "tests/docs", "tests/devdata", "tests/test_environment.py")`
  and `TOOLING_INPUTS`: today's `TEST_INPUTS` without `src` and without
  `engine/src`, `engine/extension` (kept: `engine/cmake`, the CMake files,
  presets, `mull.yml`, `fuzz/`, `bench/`, `sqllogic/`, `tests/`, pins).
- Produces: `def sets(groups: dict[str, Group], root: Path) ->
  dict[str, tuple[tuple[str, ...], set[str] | None]]`: each set's name
  (`tooling`, `group:<name>`, `unclaimed`), its test paths and the groups it
  uses (`None` for every group). `unclaimed` is every path under
  `tests/src/` no group claims; a test file under `tests/` in no set raises
  `ValueError` with a `Fix:` (Review Focus 3).
- Produces: `def run(root: Path, *, everything: bool = False) -> int`: per
  set, identity = `tooling`: SHA-256 of `TOOLING_INPUTS`' files and the
  module's whole identity; a library set: SHA-256 of its own test files,
  `src/`, the shared test files (every `conftest.py`, `tests/public_api.*`)
  and `identity(uses)`. A set
  whose identity a passed record holds prints `<set>: unchanged since a
  passed run`; the others run the three passes of `_PYTEST_PASSES` on their
  paths and record when all pass and nothing changed while they ran. Record
  key `pytest-sets`, `files` holding each set's identity, as `_ctest` does.
- Modifies: the `test` task's steps become `just test-engine-changed dev`
  and `uv run --locked python -m validation._pytest_sets`, both `always`,
  with `everything=("--all",)`; its inputs become `TOOLING_INPUTS`.

- [ ] **Step 1: Write the failing tests:**
      `test_a_change_under_src_reruns_every_library_set`,
      `test_a_group_change_reruns_its_set_and_the_unclaimed_one`,
      `test_an_edited_test_file_reruns_its_set_alone`,
      `test_a_tooling_input_reruns_the_tooling_set_alone` (`mull.yml`),
      `test_a_cmake_comment_reruns_the_tooling_set_alone`,
      `test_a_new_package_under_tests_src_is_unclaimed`,
      `test_a_test_file_in_no_set_is_refused_with_a_fix`,
      `test_all_runs_every_set`; in `test_tasks.py`, the `test` task's steps are
      the two `always` steps.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement** `_pytest_sets.py` and the task change.
- [ ] **Step 4: Run** `uv run --locked pytest tests/validation tests/checks -q`:
  PASS.
- [ ] **Step 5: Commit:**
      `feat: run the Python tests by set, each by its groups`.

### Task 5: The module's fingerprint in the other checks

**Files:**
- Modify: `validation/_checks.py` (`Task`, `digest`, `_config`, the `docs`,
  `types`, `docstrings`, `sql` tasks, `ENGINE_BUILD`)
- Test: `tests/checks/test_tasks.py`, `tests/validation/test__checks.py`

**Interfaces:**
- Consumes: `_groups.load`, `_groups.fingerprints`, `_groups.identity`.
- Produces: `Task.module: tuple[str, ...] | None = ()`: `()` no fingerprint,
  `None` every group, a tuple those groups; `digest` and `_config` add
  `identity()` for it in place of `ENGINE_BUILD`'s text. `docs`, `types`,
  `docstrings`: `module=None`; `sql`: `module=("core",)` (the shared part
  holds the extension); `tidy`, `format`, `lint` unchanged.
- Removes: `ENGINE_BUILD` and `test_the_engine_build_inputs_are_uvs_cache_keys`;
  adds `test_every_cache_key_under_engine_reaches_a_fingerprint` (each
  `tool.uv.cache-keys` path under `engine/` is a group's `dir`, a shared
  directory, or under `engine/cmake`/`CMakeLists.txt`, which reach it through
  the compile entries and the link command).

- [ ] **Step 1: Write the failing tests:**
      `test_a_cpp_comment_edit_keeps_the_docs_record`,
      `test_a_core_change_reruns_sql_and_docs`, the cache-key test above.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run --locked pytest tests/checks tests/validation -q`:
  PASS.
- [ ] **Step 5: Commit:**
      `feat: the other checks read the module's fingerprint`.

### Task 6: The audit

**Files:**
- Create: `validation/_audit.py`
- Modify: `pyproject.toml` (`[[tool.scikit-build.overrides]]` for a coverage
  wheel in `build/coverage-{cache_tag}`, sqlearn's targets instrumented with
  `-fprofile-instr-generate -fcoverage-mapping`, DuckDB not), `justfile`
  (`audit-groups`; `verify` runs it after `validate-all`)
- Test: `tests/validation/test__audit.py`

**Interfaces:**
- Consumes: `_groups.load`, `_pytest_sets.sets`, `validation.__main__.RUNNERS`.
- Produces: `def startup(profile: dict) -> set[str]`: the groups a bare
  `import sqlearn` runs (they belong to the shared part, spec §5.2).
- Produces: `def ran(export: dict, groups: dict[str, Group]) -> set[str]`:
  the groups with any covered region in an `llvm-cov export -summary-only`
  JSON, by source path under each `dir`.
- Produces: `def findings(declared: dict[str, set[str] | None], seen:
  dict[str, set[str]], start: set[str], groups) -> list[str]`: each set or
  runner that ran a group outside `closure(declared) | start`, as `"<set>
  ran <group>: Fix: add it to sq_add_group(<group> PYTHON_TESTS|VALIDATION
  …)"`; `None` declarations never yield one.
- Produces: `just audit-groups`: builds the coverage wheel, runs `startup`'s
  process, then one process per set and per runner with
  `LLVM_PROFILE_FILE`, and exits 1 on any finding.

- [ ] **Step 1: Write the failing tests** on JSON fixtures (no coverage build in
      the fast tests): `test_a_set_running_an_undeclared_group_is_a_finding`,
      `test_startup_groups_are_no_finding`,
      `test_an_unclaimed_set_is_never_a_finding`,
      `test_a_dependency_of_a_declared_group_is_no_finding`.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement**, and the override and recipes.
- [ ] **Step 4: Run** the tests: PASS; then `just audit-groups` once (no
  claims exist yet, so it must report no finding).
- [ ] **Step 5: Commit:** `feat: an audit of the groups' claims by coverage`.

### Task 7: The benchmarks' due list

**Files:**
- Create: `validation/_bench.py`
- Modify: each script in `validation/benchmarks/` (two module constants),
  `engine/CMakeLists.txt` (`BENCH buffer` on `raw`), `justfile`
  (`benchmarks-due`, `bench`)
- Test: `tests/validation/test__bench.py`

**Interfaces:**
- Consumes: `_groups.*`.
- Produces: in each page script, `PAGE: str` (its `docs/benchmarks/*.md`)
  and `GROUPS: tuple[str, ...] | None` (`None` for every group).
- Produces: `def due(root: Path) -> list[Due]`, `Due(name, page, last_seconds:
  float | None, last_cores: float | None, last_peak_mb: float | None)`: every
  benchmark whose identity (its script's or program's bytes, its groups'
  `identity()`) has no record. Runs nothing.
- Produces: `def run(root: Path, name: str) -> int`: runs one, records its
  identity, wall time, cores (`(user + sys) / wall` of the child), peak
  memory (`ru_maxrss`) and `uptime` before and after, under key `bench`.
- Produces: `just benchmarks-due` (prints the list, one line each with time,
  cores and memory) and `just bench <name>` (asks nothing itself: the agent
  asks Tomas before typing it, ADR 0072).

- [ ] **Step 1: Write the failing tests** with a stand-in benchmark script in
  a scratch repository: `test_due_lists_a_benchmark_never_run`,
  `test_a_recorded_benchmark_is_not_due_until_its_group_changes`,
  `test_due_runs_nothing` (the stand-in writes a file when run; it must be
  absent), `test_run_records_time_cores_memory_and_load`.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests: PASS; `just benchmarks-due` lists every page
  script and `bench_buffer`, and runs none of them.
- [ ] **Step 5: Commit:** `feat: list the benchmarks due, run one on request`.

### Task 8: The docs, and the proof on this machine

**Files:**
- Modify: `docs/architecture/testing.md`, `HANDOFF.md`, `CLAUDE.md` (the
  checks paragraph's line on what `just done` reruns)

- [ ] **Step 1:** Describe in `testing.md` the manifest and the claims, the
  fingerprints (comments stripped, line numbers kept), the sets, the other
  checks' `module`, the audit and `just benchmarks-due`; drop the text on
  `ENGINE_BUILD`.
- [ ] **Step 2:** `just done` until it passes and remembers the tree.
- [ ] **Step 3: The proof (spec §7):** commit a comment edited within its
  line in `engine/src/core/error.cpp`; `just done` prints `unchanged since a
  passed run` for every runner, every library set, `docs` and `sql`. Revert
  it in a second commit; the same. Then a comment line added to
  `engine/cmake/warnings.cmake`: only the tooling set runs. Revert. Record
  the four runs' output lines in the commit message of Step 4.
- [ ] **Step 4:** Move HANDOFF's item to "Just finished"; commit
  `docs: selecting by group, and its proof on this machine`.
