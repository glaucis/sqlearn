---
type: task
tags: [tooling, checks, build, ccache, uv, test-selection, cleanup]
summary: "Plan for the small tooling fixes before the rewrite: the SQL tests' data files, the 24 s rebuild, just done's order, the compiler stamp, and the follow-ups of issues #85 and #86."
related: [HANDOFF.md, justfile, pyproject.toml, engine/sqllogic/CMakeLists.txt, engine/cmake/sql_tests.cmake, validation/_groups.py, validation/_checks.py, docs/architecture/setup.md, docs/architecture/testing.md]
---
# The small tooling fixes: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the small tooling fixes from `HANDOFF.md`'s "Next up". That
covers four of its items, the follow-ups of #86 (selecting by group) and the
ones of #85 (Phase 1 step 2's reviews) that need no decision. The
benchmark queue and Phase 1 step 3 then start from a clean slate.

**Architecture:** One task per area, each its own commit with its test. The
first four tasks are `HANDOFF.md`'s items. Tasks 5 to 8 are #86, grouped by
kind. Tasks 9 to 12 are the #85 items that are small and need no decision.
Task 13 closes the work. The #85 items that need Tomas's choice are listed
under "Decisions for Tomas" below. They are not built here until he answers;
a yes adds a task.

**Tech Stack:** `just`, uv, pytest, CMake, ccache, Python 3.12, C++23 (two
small C++ edits).

**Spec:** `HANDOFF.md`'s "Next up" items 1 (the list of small fixes), the
`compiler-stamp`, `done`'s order, the SQL tests' data files, the rebuild,
the record helpers and the `test` record's `files`. Issue #86 (its whole
body). Issue #85, its items not marked for steps 3 and 4.

## Global Constraints

- Python packaging uses uv: `uv add`, `uv run`. Never pip or a bare
  `python` (ADR 0001). Every task runs through `just` (ADR 0008).
- Before each commit, `just fmt`, `just check` and `just test` pass; name
  every failure. Never `--no-verify`. Before the work is called done,
  `just done` passes.
- TDD: watch each new test fail for the right reason, then pass.
- No benchmark runs (ADR 0072). Task 4 counts ccache hits and misses,
  which is not a timing; it times nothing.
- British English in prose, American spelling in identifiers (ADR 0010).
- Commits: Conventional Commits, scopes only `hooks`, `site`, `deps`,
  lines at most 72 characters, no body line starting `word:`, no AI or tool
  attribution, no trailers.
- A check that fails tells the user how to fix it with a `Fix:` line, never a
  traceback (ADR 0065: no crash reaching the user).
- Submodules under `engine/` are never edited.
- Nothing under `old_python/` is edited or run (ADR 0073).
- After the C++ edits of Task 12, run `just sanitize` and `just mutate-engine`
  (`HANDOFF.md`'s traps: after any new group or raw file).
- Subagents: no `tail -f`, `tail -F`, `until` or `pgrep` wait loops; wait on a
  PID or the harness's notification.

## Review Focus

1. **A data file beside a `.test` that is git-ignored** (`.DS_Store`).
   Expect: it may rerun the label, never hide an edit to a tracked file.
   Task 1's test puts a hidden file in the scratch directory and asserts it
   is listed. Listing it over-runs, which is safe.
2. **A fresh clone after Task 4.** Expect: `just setup` still builds from
   nothing, since uv installs the build group before sqlearn. Task 4,
   Step 6 syncs a new environment from empty.
3. **A stale `uv.lock` under `just done`.** Expect: the named check
   `check-lockfile` fails first, with uv's own message, and nothing after it
   runs on a broken environment. Task 3's test pins it.
4. **A runner edited while `validate` runs, after Task 6 stops the
   child's second fingerprint.** Expect: the pass is still not recorded.
   Task 6 keeps `test_a_group_edited_while_the_runner_ran_is_not_recorded`
   green, moved to the parent.
5. **A group name or path with a quote or backslash.** Expect: the
   manifest is valid JSON and loads (Task 7).

## Decisions for Tomas

None of these is built until Tomas answers. Each line gives the choice and
a recommendation. A yes adds a task before Task 13.

| #85 item | The choice | Recommendation |
| --- | --- | --- |
| `engine` whole in `TOOLING_INPUTS` | Narrow it to the files the tooling tests read, or keep the minute of over-running | Keep it: a missed file hides a change, the cost is a minute |
| LLVM path | Detect it (`brew --prefix llvm`, an env override) everywhere, or keep `/opt/homebrew` | Keep it until Linux (step 3); Task 11 fixes `doctor`'s copy |
| A patched submodule | Fail the configure, or warn | Fail with a `Fix:` line: submodules are never edited |
| `just check-stubs` | Bring back a test of `_native.pyi`, or wait for the first group | Wait: the rewrite's first group brings `sq.` back |
| INSTALL then LOAD of a local extension | Build a small test extension, or accept the gap | Accept until a user extension matters (`old_python`'s case is gone) |
| Duplicate flavour flags | Clear CMake's config flags for our targets (keeping `-DNDEBUG` where it is now), or leave | Leave: harmless, and the fix moves `assert` |
| Bindings in headers-alone | Configure duckdb-python in a preset, or accept | Accept: the wheel build covers them |
| Fuzz corpus cap | Pick `-max_len` and a size cap, or none | `-max_len=4096` (today's largest), 1 MB, 500 files |
| Licence column | Pin each licence file's digest beside its row, or trust the column | Pin: a dependency's relicence is caught |
| Per-thread `sigaltstack` | Hook DuckDB's thread start, or main thread only | Main thread only for now, written down in the crash docs |
| Mutation-test the crash group | Add `test_crash` to Mull, or not | Not yet: forking tests under Mull are slow and flaky |
| SQL tests without a build | Configure the sqllogic tree in the test, or keep the skip | Keep the skip: the `sql` task builds it |
| Crash handler's image paths (`images.cpp:48`) and a second thread cutting a report (`handler.cpp:290`) | Fix them now (C++, M each), or with the crash group's rewrite | With the rewrite: the crash group is redesigned then |

#85 items left as they are, with the reason to note on the issue:

- `_gitlinks` ignores `OUTPUTS`: they are JSON files, never gitlinks.
- Redundant exit-code asserts, the stub test's needs, and the
  `validate_probability` flip: all only in `old_python/`, never run.
- `format` reruns on `engine/cmake` edits: gersemi reads the whole directory.
- `-c unused` noise: nothing names it. Ask Tomas where he saw it, or
  drop it.

#86 item left as it is: runner claims match a module's last name part
(item 13). `RUNNERS` is empty, so this waits for the first runner, as
`validate` joining `affected` and `sweep` does.

---

### Task 1: Every file under the SQL tests is part of the label's identity

The `sql` task reruns on any file under `engine/extension/test`
(`SQL_INPUTS`). `_ctest`, though, hashes only the `.test` files
(`REQUIRED_FILES`). So a data file edited beside a `.test` reruns the
task while `_ctest` skips the label.

**Files:**

- Modify: `engine/cmake/sql_tests.cmake` (add a function)
- Modify: `engine/sqllogic/CMakeLists.txt` (the last lines and their comment)
- Test: `tests/engine/test_sqllogic.py`

**Interfaces:**

- Produces: `sq_sql_test_data(out dir)`: every file under `dir` at any
  depth (`GLOB_RECURSE`, `CONFIGURE_DEPENDS` outside script mode,
  `LIST_DIRECTORIES false`), sorted.

- [ ] **Step 1: Write the failing tests**

`test_the_test_data_takes_every_file_under_the_directory(tmp_path)`. It
builds the same tree as
`test_the_test_set_takes_every_file_the_runner_runs` plus `.hidden`. It
runs `sq_sql_test_data` by `cmake -P` and asserts that the listed set
equals every file created.

Change `test_every_sql_test_file_is_part_of_the_labels_identity` to
`test_every_file_under_the_sql_tests_is_part_of_the_labels_identity`:
`required == {p for p in TESTS.rglob("*") if p.is_file()}`.

- [ ] **Step 2: Run them, expect FAIL**

Run: `uv run --locked pytest tests/engine/test_sqllogic.py -v`. The first
fails because `sq_sql_test_data` is unknown. The second is skipped without
a sqllogic build; it runs under `just test-sql`'s build.

- [ ] **Step 3: Add `sq_sql_test_data` and pass its list to `sq_test_data`**

`sq_sql_test_files` still feeds the "No SQL test" guard.

- [ ] **Step 4: Run the tests, then `just test-sql`, expect PASS**
- [ ] **Step 5: Remove the HANDOFF item, commit**
  `fix: hash every file under the SQL tests for their label`

### Task 2: `just test` and `just full` write the compiler stamp first

**Files:**

- Modify: `justfile` (`test:` and `full task:`)
- Test: `tests/checks/test_tasks.py`

- [ ] **Step 1: Widen the test.** Rename
  `test_affected_and_sweep_write_the_compiler_stamp_first` to
  `test_every_recipe_that_runs_checks_writes_the_compiler_stamp_first`,
  parametrised over `["affected", "sweep", "test", "full"]`, with the same
  assertion.
- [ ] **Step 2: Run it, expect FAIL** for `test` and `full`.
- [ ] **Step 3: Make `compiler-stamp` a dependency** of `test` and `full`.
  Add one line to each recipe's comment, as `affected` has.
- [ ] **Step 4: Run it, expect PASS;** then
  `uv run --locked pytest tests/checks -v`.
- [ ] **Step 5: Commit**
  `fix: write the compiler stamp before just test and just full`

### Task 3: `check-lockfile` runs before anything uv runs

`done` and `verify` call `sweep-stale` and `place`, both `uv run --locked`,
before `check-lockfile`. A stale lock therefore fails with uv's error
instead of the named check.

**Files:**

- Modify: `justfile` (`done`, `verify`)
- Test: `tests/checks/test_passed_tree.py`

**Decision:** `check-lockfile` runs right after `compiler-stamp`. When it
fails, `done` and `verify` exit with its code at once: every later check
would fail on uv's error. It leaves `done`'s loop. `calls.log` still
starts with it, so `RUNS` stays as it is. `verify` also runs it alone,
before `checkable-tree`.

- [ ] **Step 1: Write the failing tests.** In `OVERRIDES`, `place` and
  `check-lockfile` also append their name to `order.log`; add `order.log`
  to the scratch `.gitignore`.
  - `test_the_lockfile_is_checked_before_anything_uv_runs`: after `just
    done`, `order.log` starts `["check-lockfile", "place"]`.
  - `test_a_stale_lockfile_stops_done_at_once`: a `check-lockfile`
    override that exits 1. Assert exit 1, `calls(repo) ==
    ["check-lockfile"]` and nothing remembered.
  - The same order test for `verify`:
    `test_verify_checks_the_lockfile_before_anything_uv_runs`.
- [ ] **Step 2: Run them, expect FAIL** (`place` comes first).
- [ ] **Step 3: Reorder `done` and `verify`.** The existing tests' expected
  `calls` stay as they are.
- [ ] **Step 4: Run `uv run --locked pytest tests/checks/test_passed_tree.py
  -v`, expect PASS**
- [ ] **Step 5: Remove the HANDOFF item, commit**
  `fix: check the lockfile before just done runs uv`

### Task 4: sqlearn builds without isolation, so ccache hits after a commit

uv builds sqlearn in a new temporary environment each time. nanobind's
sources and headers then sit at a new path, and every binding object
misses ccache: about 24 s after each commit (`docs/architecture/setup.md`).
The chosen fix is no build isolation for sqlearn, with its build
requirements in a dependency group. uv installs that group before it
builds a `no-build-isolation-package` (its two-phase install). The other
option, ccache path settings, does not help: the path is new on every
build, so no `base_dir` covers it.

**Files:**

- Modify: `pyproject.toml` (`[dependency-groups]`, `[tool.uv]`)
- Modify: `uv.lock` (`uv lock`)
- Modify: `docs/architecture/setup.md:35-45`
- Test: `tests/engine/test_build.py`

**Interfaces:**

- Produces: a dependency group `build`, the exact pins of
  `[build-system].requires`, in `default-groups`; `[tool.uv]
  no-build-isolation-package = ["sqlearn"]`.

- [x] **Step 0: Count the misses today.** Run `ccache -z`, then
  `touch engine/src/core/version.cpp` (a cache key, so uv rebuilds), then
  `uv run --locked python -c "import duckdb"`, then `ccache -s`. Record the
  miss count in the task's report. It counts objects; it times nothing.
- [x] **Step 1: Write the failing test**
  `test_sqlearn_builds_in_the_project_environment_with_its_exact_build_pins`:

```python
config = tomllib.loads((REPO / "pyproject.toml").read_text())
assert sorted(config["dependency-groups"]["build"]) == sorted(
    config["build-system"]["requires"]
)
assert "build" in config["tool"]["uv"]["default-groups"]
assert config["tool"]["uv"]["no-build-isolation-package"] == ["sqlearn"]
```

- [x] **Step 2: Run it, expect FAIL** (`KeyError: 'build'`).
- [x] **Step 3: Add the group and the setting** with a comment saying why
  (the stable path ccache needs) and that the two lists change together.
  Then `uv lock`. The group pins `numpy==2.5.4`, which the `test` group's
  `>=2.5.4` allows.
- [x] **Step 4: Run the test, expect PASS**
- [x] **Step 5: Count the misses again** with Step 0's commands, twice. The
  first rebuild moves into the project environment and may miss. The
  second must miss only the objects whose input changed: the build
  identity's, near zero. If the binding objects still miss, stop and report
  both counts; do not try another fix.
- [x] **Step 6: Sync a new environment from empty.** Run
  `UV_PROJECT_ENVIRONMENT=.venvs/fresh uv sync --locked` (minutes; ccache
  helps), then `rm -rf .venvs/fresh`. If it fails, stop and report: Tomas
  decides between this and leaving the rebuild.
- [x] **Step 7: Update `setup.md`.** The rebuild after a commit now reuses
  the compiled objects. Put the two counts in the commit body. A release's
  `uv build` stays isolated.
- [x] **Step 8: Remove the HANDOFF item, commit**
  `build(deps): build sqlearn in the project environment`

**As built (Tomas chose it, 2026-11-28):** locking without isolation needs
the build group installed, so `just build-tools` (`uv sync --frozen
--inexact --only-group build`) runs before `check-lockfile` and
`upgrade-dependencies`; `uv build` follows the setting too, so
`build-package` passes `--no-config`. The first lock was made once with the
setting off, since the old lockfile had no `build` group. Counts: 56 misses
of 68 before; 54 of 66 on the first rebuild after, 0 of 1 on the second.

### Task 5: #86, the over-running fingerprints (items 1, 4)

**Files:**

- Modify: `validation/_groups.py` (`_Fingerprinter.shared`,
  `Fingerprints`, `fingerprints`)
- Modify: the callers that load the manifest again: `validation/_checks.py`
  (`module_identity`), `_record.py` (`engine`), `_pytest_sets.py`,
  `_bench.py`, `_audit.py`
- Test: `tests/validation/test__groups.py`, `test__checks.py`

**Interfaces:**

- Produces: `Fingerprints.manifest: dict[str, Group]`, the manifest
  `fingerprints()` loaded. Callers read it instead of calling
  `_groups.load` again.

- [ ] **Step 1: Write the failing tests**
  - `test_a_new_object_of_a_group_leaves_the_shared_part(scratch)`: add
    `CMakeFiles/sq_b.dir/b/three.cpp.o` to the link line. Assert
    `_changed(...) == set()`: the group's own fingerprint covers its
    sources.
  - `test_the_fingerprints_carry_the_manifest_they_read(scratch)`:
    `scratch.prints().manifest == _groups.load(build)[0]`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Drop our groups' objects from the link line.** In `shared`,
  leave out every link argument containing `/CMakeFiles/sq_<g>.dir/` for a
  `g` in `self.groups`, the marker `_ctest._target_parts` uses. Set
  `manifest` in `fingerprints()`, and switch each caller to it.
- [ ] **Step 4: Run `uv run --locked pytest tests/validation -v`, expect PASS**
- [ ] **Step 5: Commit**
  `fix: keep group objects out of the link line's fingerprint`

### Task 6: #86, the runners' identities (items 2, 3)

Every runner's `depends` holds the selection machinery (`_groups`,
`_checks`, `_ctest`, `_record`, `_pytest_sets`), because the child imports
it. Those modules decide what runs, not what a runner computes. The child
also fingerprints the build a second time after its run (about 8 s).

**Files:**

- Create: `validation/_version.py` (`release`, moved from `_groups.py`)
- Modify: `validation/_groups.py`, `_cases.py` (import `release` from
  `_version`), `_record.py` (`loaded_files`), `__main__.py` (`run_one`,
  `main`)
- Test: `tests/validation/test__record.py`, `test___main__.py`

**Interfaces:**

- Produces: `validation._version.release(version: str) -> str`, the same
  behaviour as `_groups.release`; `_record.SELECTION: frozenset[str]`, the
  module names `loaded_files` leaves out.
- `run_one` takes no second fingerprint. `main` takes the fingerprints once
  more after all its runners. When a runner's groups moved, `main` drops the
  passes this run saved for it, as `_ctest._forget` does, and keeps its
  failures.

- [ ] **Step 1: Write the failing tests**
  - `test_loaded_files_leave_out_the_selection_machinery`: with
    `validation._groups` imported, `loaded_files` names no file of
    `SELECTION`, and still names `validation/_cases.py`.
  - `test_a_runner_takes_the_fingerprints_once`: patch `_groups.fingerprints`
    with a counter. A `main` run of two stand-in runners calls it twice in
    all: once before, once after.
  - `test_a_group_edited_while_the_runner_ran_is_not_recorded` stays and
    must pass unchanged.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** Move `release` into `_version.py` and point
  `_groups` and `_cases` at it. Add `SELECTION` and filter
  `loaded_files` by it. Move the after-run check from `run_one` into `main`.
- [ ] **Step 4: Run `uv run --locked pytest tests/validation -v`, expect PASS**
- [ ] **Step 5: Commit**
  `fix: keep the selection modules out of a runner's identity`

### Task 7: #86, the latent loud failures (items 5, 6, 7, 8)

**Files:**

- Modify: `engine/cmake/groups.cmake` (`sq_json_list` and the manifest's
  writer)
- Modify: `validation/_audit.py` (`_overlap`, `ran`)
- Modify: `validation/_pytest_sets.py` (`_manifest`, `run`, `due`)
- Test: `tests/engine/test_groups_manifest.py`,
  `tests/validation/test__audit.py`, `test__pytest_sets.py`

- [ ] **Step 1: Write the failing tests**
  - `test_a_name_with_a_quote_or_backslash_writes_valid_json`: by
    `cmake -P`, as the manifest tests do.
  - `test_paths_spelt_differently_overlap`: `_overlap("a/./b", "a//b/")`
    is true.
  - `test_a_covered_file_in_no_group_is_named`: an export covering
    `engine/src/stray.cpp`; the output names it.
  - `test_an_unreadable_manifest_is_named_before_any_fix`: an unreadable
    manifest and a claim outside `tests/src`. The output gives the
    unreadable reason first, not "claim them in a group's PYTHON_TESTS".
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** Build the manifest with `string(JSON ... SET)`
  (CMake 3.29 is the floor). Use `posixpath.normpath` in `_overlap`. Have
  `ran` return the files in no group for `run` to print. Have `_manifest`
  return its reason with the empty dict.
- [ ] **Step 4: Run the three test files, expect PASS**
- [ ] **Step 5: Commit** `fix: name what the group checks could not read`

### Task 8: #86, the latent hidden changes and the tidying

Items 9 to 12 and 14 to 16, with `HANDOFF.md`'s record helpers and the
`test` record's `files`.

**Files:**

- Modify: `validation/_groups.py` (`_pins`, `entry`, `shared`, `_versionless`)
- Modify: `validation/_bench.py` (`run`)
- Modify: `validation/_record.py` (`UNREADABLE`, `environment`)
- Modify: `validation/__main__.py:49`
- Modify: `validation/_ctest.py` → `validation/_checks.py` (`passed`, `reasons`)
- Modify: `validation/_checks.py` (`run`: the `test` record's `files`)
- Test: `tests/validation/test__groups.py`, `test__bench.py`,
  `test__record.py`, `test__ctest.py`, `test__checks.py`;
  `tests/checks/test_tasks.py:476-501`

**Decisions:**

- `_pins` reads each submodule's checked-out `HEAD`, nested ones too
  (`git submodule status --recursive engine`).
- An `@file` argument hashes its file's bytes, as `_ctest._target_parts`
  does.
- `_versionless` cuts only sqlearn's own version, escaped.
- `_bench run` refuses, with a `Fix:` line naming `just bench <name>`,
  when `ninja -n` shows the program out of date. It does not rebuild by
  itself.
- `_record.environment` is deleted and its tests inline it.
- A whole task never asked `why` (today `test`) saves `files={}`.

- [ ] **Step 1: Write the failing tests**, one per decision:
  - `test_a_submodule_checked_out_elsewhere_changes_the_shared_part`
  - `test_a_response_files_contents_change_its_entry`
  - `test_another_packages_dev_version_is_kept`
  - `test_a_stale_bench_program_is_refused_with_a_fix`
  - `test_the_test_tasks_record_keeps_no_files`
  - `test_passed_and_reasons_read_records_from_checks`: imports them from
    `_checks`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** Also: `_record` uses `_checks.UNREADABLE`;
  `__main__.py:49` uses `groups if groups is not None else ...`; the
  stand-in task in `test_tasks.py:476-501` uses `module=("core",)`.
- [ ] **Step 4: Run `uv run --locked pytest tests/validation tests/checks -v`,
  expect PASS**
- [ ] **Step 5: Close #86,** listing item 13 as waiting for the first
  runner. Remove the HANDOFF items. Commit
  `fix: hash what the build reads in the group fingerprints`

### Task 9: #85, the checks' `Fix:` lines (items 17, 18, 19, 26, 34)

**Files:**

- Modify: `validation/_ctest.py` (`_prepared`)
- Modify: `validation/_checks.py` (`_run_steps`, `_run_always`, the `sql`
  task's tools)
- Modify: `validation/_mutate.py:66`
- Test: `tests/validation/test__ctest.py`, `test__checks.py`, `test__mutate.py`

**Decisions:**

- `_run_always` becomes `_run_steps(..., always_only=True)`.
- A step whose program is missing (`OSError`) prints the reason and
  `Fix: just doctor`, counts as failed (exit 127), and the other steps
  still run.
- The `sql` task's compiler tool is `${CXX:-c++}`, as `compiler-stamp` uses.

- [ ] **Step 1: Write the failing tests**
  - `test_corrupt_ctest_output_is_refused_with_a_fix`
  - `test_a_missing_program_is_a_failed_step_with_a_fix`
  - `test_a_mutant_outside_the_engine_is_refused_with_a_fix`
  - `test_the_sql_task_reads_the_compiler_cxx_names`
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run `uv run --locked pytest tests/validation -v`, expect PASS**
- [ ] **Step 5: Commit** `fix: give the checks a Fix line, not a traceback`

### Task 10: #85, the flags' tests read what the build uses (items 11, 12, 13, 16)

**Files:**

- Modify: `tests/engine/test_presets.py`
- Modify: `engine/cmake/hardening.cmake:227` (link options only on linked
  targets)

- [ ] **Step 1: Strengthen the tests**
  - `test_fp_contract_is_off_in_every_target`: strips CMake comments, then
    asserts `-ffp-contract=off` is set and used in `sq_target_warnings`.
  - `test_the_wheel_compiles_with_every_warning`: parses `SQ_WARNINGS` from
    `warnings.cmake` and asserts every flag is in the wheel's compile
    commands.
  - `test_no_fast_math_anywhere`: globs every `CMakeLists.txt` and `*.cmake`
    under `engine/` outside the submodules, plus `pyproject.toml`'s
    `[tool.scikit-build.cmake.define]`.
  - `test_link_options_go_only_on_linked_targets`: by `cmake -P` or text,
    `sq_target_options` adds link options only to `EXECUTABLE`,
    `SHARED_LIBRARY` and `MODULE_LIBRARY`.
- [ ] **Step 2: Run, expect the last to FAIL.** The first three may pass
  today; they guard more than before. Note it.
- [ ] **Step 3: Guard `target_link_options` by `get_target_property(...
  TYPE)`**
- [ ] **Step 4: `uv run --locked pytest tests/engine/test_presets.py -v`,
  then `just test`, expect PASS**
- [ ] **Step 5: Commit** `fix: link options only on targets that link`

### Task 11: #85, the recipes (items 3, 5, 14)

**Files:**

- Modify: `justfile` (`doctor:32`, `setup:79`, `probe-cxx26:437-441`)
- Modify: `engine/cmake/pins.cmake:45,51` (the `Fix:` lines)
- Test: `tests/checks/test_tasks.py`, `tests/checks/test_pins_check.py`

**Decisions:**

- `doctor` uses `{{ llvm }}/clang`.
- `setup` fetches only what the build uses: `git submodule update --init`,
  then `git -C engine/duckdb-python submodule update --init external/duckdb`.
  RapidCheck's `ext/` stays unfetched, as `engine/CMakeLists.txt:161`
  says.
- `probe-cxx26` replaces `|` in an error line with `/`, and finds Apple
  clang by `xcrun --find clang++`.

- [ ] **Step 1: Write the failing tests**
  - `test_doctor_names_llvm_by_the_justfile_variable`: no
    `/opt/homebrew/opt/llvm` literal in the recipe's body.
  - `test_setup_fetches_no_nested_submodule_but_duckdbs`: the recipe, read
    by `just --dump`.
  - `test_the_pins_fix_names_the_same_fetch_as_setup`
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the two test files, expect PASS**
- [ ] **Step 5: Commit** `fix: fetch only the submodules the build uses`

### Task 12: #85, small engine edits (items 6, 7, 22, 23, 24)

**Files:**

- Modify: `engine/src/bindings/guard.hpp:45` (demangle with
  `abi::__cxa_demangle` through a `std::unique_ptr<char, free>` in the raw
  layer's style, falling back to the mangled name)
- Modify: `engine/fuzz/replay_parse_version.cpp:37` (`replay` into the
  anonymous namespace)
- Modify: `engine/tests/canary/tysan.cpp:16`,
  `tests/engine/test_sanitizers.py:4,106` (say "fails the program with its
  report", not "stops")
- Modify: `engine/cmake/hardening.cmake:209-214` (`sq_test_environment`
  refuses an entry without `=`, with a `Fix:` line)
- Test: `tests/engine/test_extension.py`, `tests/engine/test_sanitizers.py`,
  `engine/tests/` for the demangling

- [ ] **Step 1: Write the failing tests**
  - In `test_nothing_downloads_by_itself`, add
    `assert duckdb.sql(AUTOINSTALL).fetchone() == (False,)`. It may pass
    today: it guards the default connection.
  - `test_an_environment_entry_without_equals_is_refused`: by `cmake -P`.
  - A C++ test of the guard's message: a `std::runtime_error` names
    `std::runtime_error`. Put it in the bindings' group test program if one
    exists; if the guard is reachable only from Python, add no test-only
    binding and say so in the report.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run `just test`, then `just sanitize` and `just mutate-engine`**
  (Global Constraints). Name every survivor; record new survivors in
  `engine/mull.yml` only with a reason the source gives.
- [ ] **Step 5: Commit** `fix: name a C++ exception by its demangled type`

### Task 13: Close the work

- [ ] **Step 1: Comment on #85.** Say what Tasks 9 to 12 fixed, the
  "Decisions for Tomas" with his answers, and the items left with their
  reasons. Leave it open for steps 3 and 4.
- [ ] **Step 2: Update `HANDOFF.md`.** Move the finished items to "Just
  finished" with their commits. "Next up" item 1 becomes done; item 2, the
  benchmark queue, is next.
- [ ] **Step 3: Docs.** Update `docs/architecture/testing.md` where it
  describes what Tasks 5 to 9 changed (the link line, runners' `depends`,
  `Fix:` lines). Run `/docs-sync` if more moved.
- [ ] **Step 4: `git mv` this plan to `docs/plans/archived/`**
- [ ] **Step 5: `just done`, expect PASS;** name every failure.
- [ ] **Step 6: Commit** `docs: close the tooling fixes`
