---
type: plan
tags: [native-engine, phase-1, checks, selection, plan]
summary: "Rework of Phase 1 step 1's checks: drop pytest-testmon, run each check (format, lint, docstrings, types, test, validate, docs) only when its inputs changed, `just full <task>` to run one in full, keep the validation records and the passed tree."
related: [docs/specs/native-engine-phase-1.md, docs/plans/2026-11-22-native-engine-phase-1-checks.md, docs/architecture/testing.md, docs/adr/0008-just-task-runner.md, docs/adr/0016-validation-method.md, docs/adr/0043-repeatable-within-rounding.md]
---
# Phase 1 step 1: per-check selection, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** each check runs only when its inputs changed, in full on request,
with no test skipped whose input changed (spec §3.1, as amended
2026-11-22).

**Architecture:** one Python helper, `validation/_checks.py`, holds a table
of tasks (name, input globs, configuration files, command, kind: per-file or
whole) and records, per task, the digest of its inputs when it passes, in
the git common directory (`sqlearn-checks/`, shared by worktrees, as the
validation records are). A whole task runs when its digest has no passed
record; a per-file task runs its tool on the files whose digest changed,
and on every file when a configuration file changed. `just <task>` runs by
default; `just full <task>` runs everything and records. pytest-testmon,
`validation/_env.py` and the digest of module-level code go; pytest-xdist,
the `tests.json` merge, the validation records and the passed tree stay.

**Tech Stack:** Python 3.12, uv, just, pytest, pytest-xdist, ruff, ty,
mypy, rumdl, typos, numpydoc, pydoclint, Sphinx, git.

**Spec:** `docs/specs/native-engine-phase-1.md` §3.1, §3.2 ("Selection by
inputs"), §5, §6 step 1 (amended and approved by Tomas, 2026-11-22). The
previous plan, `docs/plans/2026-11-22-native-engine-phase-1-checks.md`, was
executed on this branch; this plan replaces its selection.

## Global Constraints

- Every task runs through `just`; Python through `uv run --locked`, never
  pip or a bare `python` (ADR 0001, 0008).
- Development dependencies only; the runtime stays `duckdb` and `numpy`.
- A check never skips work whose input changed (spec §2): when in doubt, an
  input is declared and the whole check reruns.
- Nothing runs automatically on GitHub; no full suite on every push.
- The pre-commit hook keeps running `just pre-commit`.
- A test of the public API does not change (ADR 0067).
- British English in prose, American spelling in identifiers (ADR 0010).
- commitlint: no scope but `hooks`, `site`, `deps`; lower-case subject;
  lines at most 72 characters; no AI or tool attribution.
- Waiting rule for every agent: each long command once, in the foreground,
  output to a log in /tmp; never the Monitor tool, never `tail -F`,
  `until`, `while` or `pgrep` loops, never a second copy, never kill a
  process it did not start; while tests or the validation run, no other
  `uv run` or `just` in the worktree.

## Review Focus

1. **A configuration change:** `pyproject.toml`, `uv.lock`, `.python-version`,
   a `conftest.py`, the `justfile`. Expected: every task that reads it
   reruns in full.
2. **A new, deleted or renamed file** under a task's globs. Expected: the
   whole task reruns (per-file tasks: the new file is checked, a deletion
   changes the digest).
3. **Files read as data** (`docs/architecture/engine-inventory.md`,
   `devdata/data/`, `.githooks/`, `commitlint.config.mjs`). Expected:
   declared as inputs of `test`, so a change reruns it.
4. **A failed run.** Expected: nothing recorded; the next run reruns.
5. **Two worktrees** recording at once. Expected: a lost record costs a
   rerun, never a skip (write to a temporary file, then `os.replace`).

---

### Task 1: the task table and its records

**Files:**

- Create: `validation/_checks.py`, `tests/validation/test__checks.py`
- Modify: `justfile` (recipe `full`; a recipe per task calls the helper)

**Interfaces:**

- Produces: `TASKS: dict[str, Task]` with `Task` a frozen dataclass:
  `name: str`, `inputs: tuple[str, ...]` (git pathspecs), `config:
  tuple[str, ...]` (pathspecs whose change reruns everything), `command:
  tuple[str, ...]` (argv; for a per-file task, the files are appended),
  `per_file: bool`.
- Produces: `digest(task: Task, root: Path) -> str` (SHA-256 of each
  tracked and untracked-not-ignored file under `inputs` and `config`: its
  path, a NUL, its bytes, a NUL, sorted); `changed_files(task, root) ->
  list[Path]` (per-file: the files whose own digest differs from the last
  passed record, or all when a `config` file changed); `run(task_name: str,
  root: Path, *, everything: bool = False) -> int` (runs, records on exit 0,
  returns the exit code; prints "<task>: unchanged since a passed run" when
  skipped).
- Produces: the record directory `$(git rev-parse
  --git-common-dir)/sqlearn-checks/`, one JSON file per task, the 20
  newest records kept, written to a temporary file then `os.replace`.

- [ ] **Step 1: Write the failing tests** in `test__checks.py`, each on a
  scratch git repository in `tmp_path` with a stand-in task table:
  `test_a_whole_task_runs_once_then_is_skipped`,
  `test_a_changed_input_reruns_a_whole_task`,
  `test_a_new_file_reruns_a_whole_task`,
  `test_a_deleted_file_reruns_a_whole_task`,
  `test_a_failed_run_records_nothing`,
  `test_a_per_file_task_checks_only_the_changed_files`,
  `test_a_config_change_checks_every_file`,
  `test_everything_runs_the_whole_task_and_records`,
  `test_records_are_kept_twenty_and_replaced_atomically`.
- [ ] **Step 2: Run them:** FAIL, no module `validation._checks`.
- [ ] **Step 3: Implement** `validation/_checks.py` with the interfaces
  above and a CLI: `python -m validation._checks <task> [--all]`.
- [ ] **Step 4: Run them:** PASS.
- [ ] **Step 5: Commit:** `test: record each check's inputs when it
  passes`.

### Task 2: the tasks

**Files:**

- Modify: `validation/_checks.py` (the real `TASKS`), `justfile`
  (`format`, `lint`, `docstrings`, `types`, `test`, `docs`, `full`;
  `check` and `pre-commit` keep working for the hook), `pyproject.toml`
- Test: `tests/validation/test__checks.py`, `tests/checks/`

**Interfaces:**

- Consumes: Task 1's `TASKS`, `run`, `digest`.
- Produces the table (inputs as pathspecs; `config` always includes
  `pyproject.toml`, `uv.lock`, `.python-version`, `justfile`):
  - `format` (per file): `ruff format --check` on `*.py`, `rumdl` on
    `*.md`.
  - `lint` (per file): `ruff check`, `typos`, `rumdl check`.
  - `docstrings` (per file, `src/`): `numpydoc lint`, pydoclint through
    the existing `check-docstring-args` filter.
  - `types` (whole, every tracked `*.py`): `ty check`, then strict
    `mypy`.
  - `test` (whole): inputs `src/`, `tests/`, `validation/`, `devdata/`,
    `docs/architecture/engine-inventory.md`, `.githooks/`,
    `commitlint.config.mjs`, every `conftest.py`; the command runs the
    fast tests in parallel (`-n auto`), then the `serial` pass, then the
    slow tier, then the hook tests, each loading `-p
    validation._tests_report`; one record for the whole task.
  - `docs` (whole): inputs `docs/`, `src/`, `examples/`; `build-docs`.
  - `validate` keeps its own per-runner records (Task 3 of the earlier
    plan); `just validate` and `just validate-all` stay.
- `just full <task>` = the helper with `--all`.

- [ ] **Step 1: Write the failing tests:** in `test__checks.py`,
  `test_the_task_table_names_every_check` (the seven names) and
  `test_every_task_declares_the_settings_files`; in `tests/checks/`,
  through the real `justfile` on a scratch repository as
  `tests/checks/test_passed_tree.py` does:
  `test_a_docs_only_change_runs_no_test`,
  `test_a_change_to_one_python_file_lints_only_that_file`,
  `test_a_data_file_change_reruns_the_tests`.
- [ ] **Step 2: Run them:** FAIL.
- [ ] **Step 3: Implement** the table and the recipes.
- [ ] **Step 4: Run them:** PASS; `just test` twice on a clean tree: the
  first runs, the second prints `test: unchanged since a passed run`.
- [ ] **Step 5: Commit:** `test: each check runs when its inputs changed`.

### Task 3: testmon goes

**Files:**

- Delete: `validation/_env.py`, its tests, the testmon tests in
  `tests/checks/test_affected.py` (keep any that still pin a live
  behaviour, rewritten against Task 2's tasks)
- Modify: `pyproject.toml` (remove `pytest-testmon` and
  `testmon_ignore_dependencies`), `uv.lock`, `.gitignore`
  (`.testmondata*` may stay ignored), `justfile` (`affected`, `test-env`,
  `test-rest` and their helpers go), `validation/tests.json`

- [ ] **Step 1:** `uv remove --group test pytest-testmon`; remove the
  rest; `grep -rn -i testmon` over the repository finds only history
  (plans, the spec's "Considered" line, the handoff's dead ends).
- [ ] **Step 2: Run** `just check` and `just full test`: PASS; the
  coverage run `just test-all` still passes the floor (95 %).
- [ ] **Step 3: Commit:** `test: drop pytest-testmon`.

### Task 4: `done`, `verify` and the docs

**Files:**

- Modify: `justfile` (`done` = every task by default, then
  `remember-tree`; `verify` = every task with `full`, plus
  `check-types-mypy` if not in `types`, `test-all` (coverage),
  `test-python-versions`, `validate-all`, then `remember-tree`),
  `CLAUDE.md` (the checks section only; read `git diff CLAUDE.md`),
  `docs/architecture/testing.md` (replace "What testmon cannot see" with
  "How each check finds what changed": the table, the inputs, the
  records), `docs/architecture/workflow.md`, `docs/architecture/setup.md`
  (the recipe table), `HANDOFF.md`
- Test: `tests/checks/test_passed_tree.py` (keep green)

- [ ] **Step 1:** Update the recipes; `tests/checks` PASS.
- [ ] **Step 2:** Update the docs; `just fmt`, `just check`.
- [ ] **Step 3: Commit:** `docs: the checks run per task when inputs
  changed`.

### Task 5: the done-when, shown

- [ ] **Step 1:** On a clean tree, run and keep the proof lines: `just
  done` twice (second: already passed); a docs-only commit then `just done`
  (no test, no runner; `docs` runs); a one-line change to one `src/` file
  (`lint` and `format` check that file alone; `types` and `test` run;
  every runner reruns — the accepted file grain); a runner's own file (that
  runner alone); a fast-forward merge of a passed tree (`ff-demo` branch,
  local only, deleted after): already passed; `just verify`: passes and
  remembers the tree.
- [ ] **Step 2:** Post the table on #79 (`gh issue comment 79 --repo
  glaucis/sqlearn --body-file <file>`; do not close #79); update
  `HANDOFF.md`; commit `docs: Phase 1 step 1's per-check selection shown`.
