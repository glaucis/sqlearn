---
type: plan
tags: [native-engine, phase-1, checks, testmon, xdist, validation, plan]
summary: "Implementation plan for Phase 1 step 1: affected tests in parallel with testmon and xdist, validation runners recorded by a digest of what they import, the passed-tree record, the done and release tiers, and pydoclint."
related: [docs/specs/native-engine-phase-1.md, docs/architecture/testing.md, docs/architecture/workflow.md, docs/adr/0008-just-task-runner.md, docs/adr/0016-validation-method.md, docs/adr/0043-repeatable-within-rounding.md]
---
# Phase 1 step 1: the checks, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** a test or a validation runner reruns only when something it
depends on changed, tests run on every core, a tree that passed is
remembered, and a release still runs everything (spec §3.1).

**Architecture:** `just test` runs pytest with pytest-testmon (selection)
and pytest-xdist (parallel), without coverage, widened by a digest of the
declared dependencies passed as testmon's environment. `python -m
validation` runs each runner in its own process, records the repository
files it imported with their hashes in the git common directory, and skips
a runner whose last passed record still matches. `just done` is the
work-is-done tier and `just verify` the release tier; both remember the
git tree they passed, as glaucis's `scripts/check.sh` does.

**Tech Stack:** Python 3.12, uv, just, pytest 9, pytest-testmon,
pytest-xdist, pydoclint, bash in the justfile, git.

**Spec:** `docs/specs/native-engine-phase-1.md` (approved 2026-11-21),
§3.1, the "For the checks" and "For the Python" parts of §3.2, §3.7 step
1, §4 and §6 step 1. Read it beside this plan.

## Global Constraints

- Every task runs through `just`; Python through `uv run --locked`, never
  pip or a bare `python` (ADR 0001, 0008).
- New tools are development dependencies only (`uv add --group test` or
  `--group lint`); the runtime stays `duckdb` and `numpy` (ADR 0005).
- Nothing needs the network at run time (ADR 0006).
- A selection never skips a test whose dependency changed (spec §2,
  anti-goal): when in doubt, a declared dependency reruns everything.
- No full suite on every push; nothing runs automatically on GitHub (spec
  §2, §3.5).
- The pre-commit hook keeps running `just pre-commit`, unchanged.
- A test of the public API does not change (ADR 0067); only checks change.
- British English in prose, American spelling in identifiers (ADR 0010).
- commitlint: no scope but `hooks`, `site`, `deps`; lines at most 72
  characters.

## Facts this plan rests on (checked 2026-11-22)

- testmon refuses to run beside pytest-cov when branch coverage is on
  ("testmon doesn't support simultaneous run with pytest-cov when branch
  coverage is on"), and `[tool.coverage.run]` has `branch = true`. So the
  affected run has no coverage; the floor (`fail_under = 95`, measured on
  the full suite) moves to the release tier, where it belongs anyway: a
  subset of the tests can never reach it.
- testmon turns its selection off when `-m` is given unless
  `--testmon-forceselect` is passed; `addopts` holds `-m "not slow"`.
- `--testmon-env` takes a Python expression; its value names a separate
  set of records in `.testmondata`, so a new value reruns everything.
- pydoclint 0.12 on `src/` with the numpydoc options below finds 9 real
  problems (missing arguments or return sections in
  `Pipeline._prepare_fold`, `Pipeline._fold_query`, `Metric.__call__`,
  `EncodeGroup.__call__`) and about 330 lines of one code (DOC108 or
  DOC111, about where types are written) that no option removes; it runs
  in 0.4 s.

## Review Focus

1. **A test that passes alone and fails beside others in parallel:**
   shared module state (`STORE`, the default connection), temporary
   files with fixed names, the working directory, wall-clock ratios under
   load. Expected: it runs in the serial pass, never flakes. Task 2.
2. **A dependency testmon cannot see:** a change to `uv.lock`,
   `pyproject.toml`, the `justfile`, a `conftest.py`, `.python-version` or
   a file under `devdata/data/`. Expected: every test reruns. Task 1.
3. **`validation/tests.json` after an affected run:** a run of a few
   tests must not drop the others' entries. Expected: entries of tests not
   run keep their outcome; entries of tests that no longer exist go.
   Task 2.
4. **A validation record that should not be trusted:** one written by a
   failed run, one whose environment (versions, OS release, BLAS)
   differs, one whose file was deleted. Expected: the runner reruns.
   Task 3.
5. **A dirty tree remembered as passed:** files other than Markdown
   changed, or a commit made, while the checks ran. Expected: nothing is
   remembered, and the message says to commit and run again. Task 4.

---

### Task 1: affected tests in `just test`

**Files:**

- Modify: `pyproject.toml` (test group), `uv.lock`, `.gitignore`
  (`.testmondata*`), `justfile` (`test`, new `test-env`, new variable
  `affected`)
- Create: `tests/checks/__init__.py` (only if the layout needs it),
  `tests/checks/test_affected.py`
- Modify: `docs/architecture/testing.md` (the recipe table, coverage)

**Interfaces:**

- Produces: the justfile variable `affected` holding `--testmon
  --testmon-forceselect -n auto`; the recipe `test-env root="."`, which
  prints 16 hex digits, the SHA-256 of the declared files under `root`:
  `uv.lock`, `.python-version`, `pyproject.toml`, `justfile`, every
  `conftest.py`, every file under `devdata/data/`, each read as bytes
  in sorted path order, a missing one counted as empty.
- Produces: `just test` = `uv run --locked pytest {{affected}}
  --testmon-env="'$(just test-env)'" --ignore=tests/githooks`, exit code 5
  (nothing selected) counted as success.

- [ ] **Step 1: Add the tools.** `uv add --group test pytest-testmon
  pytest-xdist`; add `.testmondata*` to `.gitignore`. Run `just check`:
  passes.
- [ ] **Step 2: Write the failing tests** in `tests/checks/test_affected.py`,
  each on a scratch project in `tmp_path` (two modules `a.py`, `b.py`, a
  test file for each, a `conftest.py`, a `uv.lock` stand-in), run with
  the repository environment's pytest (`sys.executable -m pytest`,
  `--rootdir` the scratch project) and the flags `just --evaluate affected`
  prints, and the environment `just --justfile <repo>/justfile
  test-env <tmp_path>` prints:
  - `test_a_one_line_change_reruns_only_its_tests`: first run runs 2;
    after editing one line of `a.py`, the run reports `1 passed`.
  - `test_nothing_changed_runs_nothing_and_succeeds`: second run selects
    none; the recipe's exit-code handling returns 0.
  - `test_a_markdown_change_runs_nothing`: a new `README.md` selects none.
  - `test_a_declared_dependency_reruns_every_test`: for each of
    `uv.lock`, `conftest.py` and a file under `devdata/data/`, a change
    gives a new `test-env` value and the run reports `2 passed`.
  - `test_test_env_is_the_same_twice`: two calls print the same 16 hex
    digits.
- [ ] **Step 3: Run them:** `uv run --locked pytest tests/checks -q`.
  Expected: FAIL, `test-env` is not a recipe.
- [ ] **Step 4: Write the recipes** `test-env` and the new `test`; keep
      `test-all` with `--cov -m ""` (the coverage floor's run);
      `test-python-versions` unchanged.
- [ ] **Step 5: Run** `uv run --locked pytest tests/checks -q`: PASS. Then
  `just test` twice: the first runs every fast test, the second selects
  none and exits 0. Note both wall times for Task 2.
- [ ] **Step 6: Docs.** `docs/architecture/testing.md`: the recipe table
  (`just test` is the affected fast tests in parallel, no coverage;
  `just test-all` every test with coverage and the floor), the declared
  dependencies and why each is declared, the coverage section.
- [ ] **Step 7: Commit:** `just fmt`, `just check`, `just test`, then
  `git commit -m "test: just test runs only the tests a change affects"`.

### Task 2: tests on every core, and `tests.json` from any run

**Files:**

- Modify: `pyproject.toml` (marker `serial`), `justfile` (`test`: a
  parallel pass, then `-m serial` with `-p no:xdist`), the tests found
  in Step 1, `validation/_tests_report.py`
- Test: `tests/validation/test__tests_report.py`

**Interfaces:**

- Consumes: Task 1's `affected` and `test-env`.
- Produces: the marker `serial` ("runs alone, after the parallel pass:
  it fails beside other tests"); `_tests_report` writes `tests.json` by
  merging: entries of every file collected are rebuilt from that file's
  collected tests (a deselected test keeps its old outcome, a test no
  longer in its file is dropped), entries of files not collected are
  kept unless the file no longer exists.

- [ ] **Step 1: Find the tests that fail in parallel.** Run `uv run
  --locked pytest -n auto --ignore=tests/githooks -q`
  three times, recording `uptime` before and after; list each test that
  fails in any run and passes alone.
- [ ] **Step 2: Fix or mark each.** A shared fixed path becomes
  `tmp_path`; shared state gets the reset the serial run relied on;
  what remains load-bound (a wall-clock ratio, a memory probe) gets
  `@pytest.mark.serial` with a one-line reason in its docstring. Register
  the marker in `pyproject.toml`.
- [ ] **Step 3: Measure memory.** Record peak resident memory summed over
  the workers for one full parallel run (`/usr/bin/time -l` on the
  pytest process, plus `ps` sampling of the workers). If it passes half
  of physical memory, cap the workers (`-n` a fixed number, stated with
  its measurement in `testing.md`); otherwise keep `auto`.
- [ ] **Step 4: Write the failing tests** in
  `tests/validation/test__tests_report.py` (pytester or a scratch
  project, as the file's existing tests do):
  - `test_a_partial_run_keeps_the_entries_of_tests_not_run`: a
    `tests.json` with entries for files `x` and `y`; a run collecting
    only `x` keeps `y`'s entries unchanged.
  - `test_a_deselected_test_keeps_its_outcome`
  - `test_a_test_removed_from_its_file_loses_its_entry`
  - `test_a_parallel_run_writes_the_same_entries_as_a_serial_one`: one
    scratch suite with a `slow` test and a failing test, run with and
    without `-n 2`, writes equal files.
- [ ] **Step 5: Run them:** FAIL on the partial-run tests (today the file
  is rewritten from what ran).
- [ ] **Step 6: Implement the merge** in `_tests_report.py`: record the
  collected node ids before deselection (`pytest_collection_modifyitems`,
  `tryfirst=True`), merge in `pytest_sessionfinish` (on the xdist
  controller only: skip when `workerinput` is set on the config).
- [ ] **Step 7: Wire it in.** `just test` loads `-p
  validation._tests_report` in both passes; `validate` no longer runs
  the tests (Task 3 rewrites it).
- [ ] **Step 8: Run** the new tests: PASS; `just test` twice on a clean
  tree: `tests.json` unchanged by the second run.
- [ ] **Step 9: Docs.** `testing.md`: the serial pass and the marker's
  rule (a reason in the docstring, never to hide a bug), the worker
  count and its measurement, where `tests.json` comes from now.
- [ ] **Step 10: Commit:** checks as in Task 1, `git commit -m "test:
  tests run on every core, tests.json from any run"`.

### Task 3: validation runners recorded

**Files:**

- Create: `validation/_record.py`
- Modify: `validation/__main__.py`, `justfile` (`validate`, new
  `validate-all`)
- Test: `tests/validation/test__record.py`,
  `tests/validation/test___main__.py`
- Modify: `docs/architecture/testing.md` (or the validation page it
  links). ADR 0016 ("validation runs in the checks; a failure blocks the
  merge") still holds and is not amended.

**Interfaces:**

- Produces, in `validation/_record.py`:
  - `Record` (a `TypedDict`): `runner: str`, `depends: dict[str, str]`
    (repo-relative path to SHA-256 hex), `environment: dict[str, str]`
    (`_cases.environment()`), `counts: dict[str, int]`, `passed: bool`.
  - `loaded_files(root: Path) -> list[Path]`: the `__file__` of every
    module in `sys.modules` under `root` and outside `.venv`, plus
    `uv.lock` and every file under `devdata/data/`.
  - `digest(paths: Iterable[Path], root: Path) -> dict[str, str]`.
  - `record_dir(root: Path) -> Path`: `$(git rev-parse
    --git-common-dir)/sqlearn-validation`, shared by every worktree
    (the agent's call: a record is valid only while its hashes match, so
    sharing is safe, and a new worktree need not rerun the hour).
  - `matching(records: Sequence[Record], root: Path, environment:
    dict[str, str]) -> Record | None`: the newest record that passed,
    with an equal environment and every file of `depends` present with
    the same hash.
  - `load(directory: Path, runner: str) -> list[Record]` and
    `save(directory: Path, record: Record) -> None`: one JSON file per
    runner, the 20 newest records kept, written to a temporary file and
    moved into place with `os.replace`.
- Produces, in `validation/__main__.py`: `main(runners: Sequence[str],
  root: Path, *, everything: bool = False) -> int`. Each runner whose
  record matches is reported `name: unchanged since a passed run` and
  its results file is left alone; every other runner runs in a child
  `sys.executable -m validation --one <module>`, which writes
  the results as today, then saves its record. `environment.json` is
  written when any runner ran. Exit 1 when any sqlearn case failed, as
  today. CLI: `python -m validation [--all]`.

- [ ] **Step 1: Write the failing tests** in `test__record.py`:
  - `test_a_record_matches_while_its_files_are_unchanged`
  - `test_a_changed_file_breaks_the_match`
  - `test_a_deleted_file_breaks_the_match`
  - `test_a_changed_environment_breaks_the_match` (for example
    `os_release` 27.2.1 then 27.3)
  - `test_a_failed_run_is_never_matched`
  - `test_save_keeps_the_twenty_newest`
  - `test_loaded_files_names_repo_modules_and_declared_data_only`: after
    importing a module from a scratch root, it is listed; numpy's files
    are not; `devdata/data/*.csv` and `uv.lock` are.
- [ ] **Step 2: Run them:** FAIL, no module `validation._record`.
- [ ] **Step 3: Implement `_record.py`** with the interfaces above.
- [ ] **Step 4: Run them:** PASS.
- [ ] **Step 5: Write the failing tests** in `test___main__.py`, with two
  tiny stand-in runner modules on `sys.path` (one passing, one with a
  failing case) and `tmp_path` as root and record directory:
  - `test_an_unchanged_runner_is_skipped_and_its_results_kept`: the
    second `main` call leaves the results file's bytes unchanged and
    prints `unchanged since a passed run`.
  - `test_a_changed_runner_reruns`: touching the stand-in's source
    reruns it alone.
  - `test_everything_reruns_every_runner`
  - `test_a_failing_runner_reruns_each_time_and_exits_1`
- [ ] **Step 6: Run them:** FAIL.
- [ ] **Step 7: Implement** `main`, `--one` and `--all` in `__main__.py`;
  `just validate` = `uv run --locked python -m validation`; `just
  validate-all` = the same with `--all`.
- [ ] **Step 8: Run** the tests: PASS. Then `just validate` twice on the
  real repository: the first runs every runner (about 47 minutes; let it
  finish, never start a second), the second reports every runner
  unchanged in seconds. Edit one line of `src/sqlearn/metrics/regression.py`
  (a comment): only the runners that import it rerun; revert.
- [ ] **Step 9: Docs:** how runners are recorded, where the records live,
  `--all`, and that a release reruns every runner.
- [ ] **Step 10: Commit:** `git commit -m "test: a validation runner
  reruns only when what it imports changed"`. Results files: commit only
  those whose verdicts changed; discard last-digit changes (ADR 0043).

### Task 4: the passed tree, `just done` and the release tier

**Files:**

- Modify: `justfile` (new `checkable-tree`, `remember-tree`, `done`;
  `verify` becomes the release tier)
- Create: `tests/checks/test_passed_tree.py`
- Modify: `CLAUDE.md` (the checks section), `docs/architecture/workflow.md`,
  `docs/architecture/testing.md`, `docs/specs/native-engine.md` only if a
  line still says otherwise

**Interfaces:**

- Consumes: Tasks 1 to 3's `test`, `validate`, `validate-all`.
- Produces:
  - `checkable-tree`: prints `git rev-parse 'HEAD^{tree}'` when no file
    other than Markdown differs from `HEAD` and none is untracked;
    prints nothing otherwise (glaucis's `checkable_tree`).
  - `remember-tree tree`: appends the tree to `$(git rev-parse
    --git-common-dir)/sqlearn-passed` (the 50 newest kept) when it still
    equals `checkable-tree`; else prints "Not remembered: a file other
    than Markdown differed from the last commit, or the commit changed,
    while the checks ran. Commit, then run this again." Exit 0 either
    way.
  - `done`: if `checkable-tree` is in `sqlearn-passed`, prints "Tree
    <tree> already passed: nothing to run." and exits 0; else runs
    `check`, `test`, `validate`, then `remember-tree`.
  - `verify` (the release tier, name kept, the agent's call): `check
    check-types-mypy test-all test-python-versions test-hooks
    check-docstrings validate-all build-docs`, then `remember-tree`.

- [ ] **Step 1: Write the failing tests** in `test_passed_tree.py`, each
  in a scratch git repository with a copy of the repository's `justfile`
  and stand-in `check`, `test` and `validate` recipes (a stand-in `just`
  first on `PATH`, as `tests/githooks` does, or an overriding justfile
  that imports the real one; the implementer picks):
  - `test_a_clean_tree_that_passed_is_remembered`
  - `test_a_remembered_tree_runs_nothing`: second `done` prints `already
    passed` and the stand-ins record no call.
  - `test_a_markdown_change_keeps_the_tree_checkable`
  - `test_a_dirty_tree_is_not_remembered`: an untracked `x.py` makes
    `checkable-tree` print nothing and `remember-tree` print `Not
    remembered`.
  - `test_a_commit_during_the_checks_is_not_remembered`
  - `test_a_fast_forward_to_a_passed_tree_runs_nothing`: a branch
    passes `done`, `main` fast-forwards (and, separately, merges with
    `--no-ff` while `main` has not moved) to it; `done` on `main` runs
    nothing.
- [ ] **Step 2: Run them:** FAIL, no recipe `checkable-tree`.
- [ ] **Step 3: Write the recipes.**
- [ ] **Step 4: Run** the tests: PASS. `tests/checks` joins `just test`
  (they take seconds); the `justfile` is a declared dependency (Task 1),
  so a change to it reruns them.
- [ ] **Step 5: Docs.** `CLAUDE.md`'s checks: before you say work is
  done, `just done` passes (it runs what changed and remembers the
  tree); `just verify` is the release tier, run by hand before `1.0.0`;
  a reviewer's verdict says which ran. `workflow.md` and `testing.md`:
  the table of spec §3.1 (a commit, a push, a merge to `main`, work is
  done, a release) with the recipe for each.
- [ ] **Step 6: Commit:** `git commit -m "test: just done remembers the
  tree it passed, just verify is the release"`.

### Task 5: pydoclint

**Files:**

- Modify: `pyproject.toml` (lint group, `[tool.pydoclint]`), `uv.lock`,
  `justfile` (new `check-docstring-args`, added to `check`)
- Modify: `src/sqlearn/_pipeline.py` (`_prepare_fold`, `_fold_query`),
  the file of `Metric.__call__`, `src/sqlearn/preprocessing/_encode.py`
  (`EncodeGroup.__call__`)

**Interfaces:**

- Produces: `check-docstring-args` runs `uv run --locked pydoclint src`
  with `[tool.pydoclint]`: `style = "numpy"`,
  `arg-type-hints-in-docstring = false`, `check-return-types = false`,
  `check-yield-types = false`, `check-class-attributes = false`,
  `skip-checking-raises = true`; it fails on any line whose code is not
  DOC111 (types in the docstring are numpydoc's style, and no option
  drops that code), and prints those lines.

- [ ] **Step 1:** `uv add --group lint pydoclint`; write the config and
  the recipe; add it to `check`.
- [ ] **Step 2: Run** `just check-docstring-args`. Expected: FAIL with
  the 9 findings named under "Facts".
- [ ] **Step 3: Fix the docstrings:** each missing argument and return
  section written, in the file's numpydoc style.
- [ ] **Step 4: Run** `just check`: PASS, and `just check-docstrings`
  (numpydoc) still passes.
- [ ] **Step 5: Docs:** the docstring rules page (`writing.md` or
  `testing.md`, wherever numpydoc's check is described) names pydoclint,
  what it checks, and the DOC111 filter with its reason.
- [ ] **Step 6: Commit:** `git commit -m "test: pydoclint checks each
  docstring against its signature"`.

### Task 6: the step's done-when, shown

**Files:**

- Modify: `HANDOFF.md`; a comment on #79

- [ ] **Step 1:** On a clean tree after Task 5, run each scenario of spec
  §6 step 1 and keep its output: a one-line change to one module (only
  its tests and its runners run); a docs-only commit (`just done` runs no
  test and no runner); a fast-forward merge of a passed tree (`just done`
  prints `already passed`); `just verify` (every test on every Python,
  every runner, with `--all`).
- [ ] **Step 2:** Post the results on #79 (github-pm), update
  `HANDOFF.md` (step 1 to "Just finished", step 2 next), commit with the
  work's last commit or alone: `git commit -m "docs: Phase 1 step 1 in
  the handoff"`.
