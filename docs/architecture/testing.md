---
type: guide
tags: [testing, pytest, coverage, hooks, tiers]
summary: "Explains how tests are written, split into fast and slow tiers, the hook tests, and coverage reporting in this project."
related: [docs/architecture/layout.md, tests/githooks/test_pre_commit.py, tests/githooks/test_pre_merge_commit.py, tests/githooks/test_commit_msg.py, pyproject.toml]
mdindex: [type=83ca68, tags=683dc4, summary=ca8286, related=ec2e81]
---
# Testing

How the tests are written and run. The settings are in `pyproject.toml`.

## Writing a test

- **One docstring per test**, one line saying what it checks and why. ruff
  holds every test to one; its form is otherwise free.
- **No annotations.** ruff's `ANN` rules apply to `src/` only.
- **No numpydoc validation.** `just check-docstrings` reads `src/`, not
  `tests/`.
- **pydoclint checks `src/` only.** `just check-docstring-args` (part of
  `just check`) compares each docstring under `src/` with its signature: every
  argument written, a Returns section where the function returns. Types are
  written in the docstring, numpydoc's own style, so the recipe lets code
  DOC111 pass (no option drops it) and fails on any other. Its options are in
  `[tool.pydoclint]`.
- Warnings are errors (`filterwarnings = ["error"]`), so a deprecation is found
  the day it appears.

Where a test goes is in [the layout](layout.md): `tests/` mirrors the root.

## Two tiers

A test marked `slow` is the larger-than-memory tier. A plain `pytest` run
deselects it (`-m "not slow"`), and `--strict-markers` rejects a marker that is
not declared.

| Recipe | What it runs |
|---|---|
| `just test` | the fast tests a change affects: a parallel pass, then the `serial` ones alone, without coverage, without `tests/githooks` |
| `just test-rest` | the affected tests `just test` leaves out: the slow tier alone, then the hook tests in parallel |
| `just test-all` | every test, the slow ones included, with coverage and the floor |
| `just test-env` | 16 hex digits naming the declared dependencies and the module-level code below |
| `just test-python-versions` | the tests, slow ones included, on each Python in the matrix |
| `just test-hooks` | the hook tests alone |

`just test` is every agent's to run before a commit; `just done` is the check
before work is done, and `just verify` is the release tier.

| When | Recipe |
|---|---|
| A commit | the pre-commit hook: `just pre-commit` over the files committed |
| A push | none: a push runs no suite |
| A merge to `main` | the pre-merge-commit hook runs what the pre-commit hook runs; `just done` on `main` runs nothing for a tree that passed |
| Work is done | `just done`: `check`, `test`, `test-rest`, `validate`, then the tree is remembered |
| A release | `just verify`: `done`'s checks in full (`test-all`, `validate-all`, every Python, the docs), by hand before `1.0.0` |

`just done` remembers each tree that passed in `sqlearn-passed`, in the git
common directory (the 50 newest, shared by worktrees). A tree that differs
from `HEAD` only in Markdown still counts, so a fast-forward or a `--no-ff`
merge of a passed tree runs nothing. A declared Markdown file (below) is an
input, not prose: edited and not committed, it leaves no checkable tree.
A tier that fails stops `just done`, and nothing is remembered.

`just checkable-tree` also ignores the files the checks write:
`validation/**/*.results.json`, `validation/tests.json` and
`validation/environment.json`. They are outputs of `validate` and `test`, not
inputs, so a run that rewrites them leaves the tree it checked still HEAD's.

### Affected tests

`just test` uses pytest-testmon: it records which lines each test runs, and
reruns only the tests whose lines changed. pytest-xdist runs them in parallel
(`-n auto`). A run that selects nothing succeeds. The data is in
`.testmondata*`, which git ignores.

testmon sees only the lines it traces while a test runs, so `just test-env`
hashes what changes a result without being traced, and testmon reruns every
test when the hash changes. It hashes each declared file's path, then its
bytes, so a new empty file counts. The list is `declared` in the `justfile`,
the one place `test-env` and `checkable-tree` read it from:

- `uv.lock`, `.python-version`: the installed libraries and the interpreter.
- `pyproject.toml`, `justfile`: the test settings and the flags.
- every `conftest.py` (found, not listed): fixtures reach every test beneath
  them.
- every file under `devdata/data/`, and
  `docs/architecture/engine-inventory.md`: tests read them as data.
- every file under `.githooks/`, and `commitlint.config.mjs`: the hook tests
  run them in a subprocess.

sqlearn's own version is left out of testmon's environment
(`testmon_ignore_dependencies`) because it changes with every commit.

### What testmon cannot see, and how each is declared

Each input testmon cannot trace is declared by one of four rules, so a new
one (the native module, in step 2) joins by its rule, not by chance:

- **Import-time code.** testmon starts tracing at the first test, after
  collection has imported every module, so a module's constants, imports,
  class bases and bodies, decorators, signatures and `__all__` belong to no
  test. `test-env` hashes them: `validation/_env.py` reads every `.py` file
  under `src/`, `tests/`, `validation/` and `devdata/`, empties each function
  and method body, and hashes what is left (the syntax tree, so comments and
  blank lines do not count) with the sorted paths, and the path of every
  file under `src/`. A module-level edit, or a new or deleted module, reruns
  every test. An edit inside a function leaves the selection to testmon,
  unless the function may run at import: then its body is hashed too, since
  no test would see the edit. Those are the dunders Python calls when an
  instance or a class is made (`__init__`, `__new__`, `__post_init__`,
  `__init_subclass__`, `__set_name__`, `__class_getitem__`), and every
  function, or every method of a class, whose name a statement outside any
  function body calls or applies as a decorator, in any of those files: a
  module-level `gamma = Metric(2.0)` keeps `Metric`'s methods. The match is
  by name alone, across files, so it reruns more than it must; it does not
  follow a kept body's calls into other functions. A file that does not
  parse counts by its bytes.
- **Files read as data.** A test that opens a file, rather than running it,
  depends on its bytes: the file, or its folder, goes in `declared`. A test
  that globs for files depends on their paths, which the module-level digest
  covers for Python files and for everything under `src/`.
- **Code in a subprocess.** testmon traces its own process only. A test that
  runs a script, a hook or a tool depends on that file: it goes in
  `declared`, as `.githooks/` does.
- **Installed packages.** testmon records each installed package's version
  and reruns every test when one changes; `uv.lock` is declared besides.
  `testmon_ignore_dependencies` lists the two that change with every commit.

One test reads source text inside function bodies:
`test_the_package_holds_no_datasets` scans every module of the package for
`devdata`, which `just test` does not rerun after a function body edit, so
`just check-no-devdata`, part of `just check`, applies its rule on every
commit.

`--testmon-forceselect` keeps the selection on despite `-m "not slow"`.

### The serial pass

`just test` runs two passes: every fast test on all cores (`-n auto`), then
the tests marked `serial` alone, without xdist (`-p no:xdist`). A test marked
`@pytest.mark.serial` fails beside other tests; its docstring says why, in
one line (a wall-clock ratio, a memory probe). The marker is never a way to
hide a bug: a test that fails in parallel is first understood, and fixed
when its cause is shared state (a fixed path becomes `tmp_path`, a learned
store is cleared). Both passes keep testmon, and each treats "nothing
selected" as success. Today no test is marked: three parallel runs of the
whole fast suite, one of them with the machine at a load of 50 on 8 cores,
passed every test.

Each pass (`fast`, `serial`, and `test-rest`'s `slow` and `hooks`) keeps its
own testmon environment: `test-env`'s digest followed by the pass's name.
Under xdist, testmon records only the tests a pass selects, so a test the
parallel pass deselects by marker is never recorded there; a pass sharing
that record would find the test's file unchanged and skip it, even after
its code changed. In an environment of its own, each pass records every
test it runs.

### The worker count

`-n auto` starts one worker per core (8 on the M-series machine measured).
One full parallel run of the fast suite peaked at 4.6 GB resident summed over
the pytest process and its workers, on a machine with 16 GB: under half of
physical memory, so the count stays `auto`. It was measured by sampling `ps
-axo rss,command` every second for the processes running from the project's
`.venv` and taking the largest sum, because macOS's `/usr/bin/time -l`
reports the parent's peak only. Rerun the measurement when the suite grows
a large fixture; cap `-n` at a fixed number if the peak passes half of
memory.

### `validation/tests.json`

The `validation._tests_report` plugin, loaded by both passes, writes
`validation/tests.json` and merges rather than rewrites. A file collected in
the run has its entries rebuilt from its collected tests: a test that ran
takes its new outcome, a test collected but deselected (testmon, `-k`, `-m`)
keeps its old one, and a test no longer in its file is dropped. The entries
of a file not collected stay unless the file is gone. Under xdist the
controller writes, from the reports and from the lists the workers sent, so a
parallel run writes the same bytes as a serial one.

## The validation runners

`just validate` (`python -m validation`) reruns a runner only when a file it
depends on changed since it last passed. Each runner runs in its own process,
writes its `*.results.json` as before, and then saves a record: the SHA-256 of
every module it imported from the repository (outside `.venv`), of `uv.lock` and
of every file under `devdata/data/`, with the environment (`environment.json`'s
fields: library versions, OS release, BLAS), the count of each result and
whether every sqlearn case passed. The next run skips a runner, printing
`unchanged since a passed run` and leaving its results file alone, when the
newest record with the same environment and every file it names present with the
same hash passed. A run with a failing case reruns every time, and it cancels
any earlier pass of the same inputs. `environment.json` is written when any
runner ran. The code is `validation/_record.py`.

The records live in `sqlearn-validation/` in git's common directory (`git
rev-parse --git-common-dir`), one JSON file per runner holding its 20 newest.
Every worktree shares them: a record stands only while its hashes match, so
one worktree's passed run spares another the hour, and a new worktree starts
with them. Deleting the directory makes the next run rerun everything.

`just validate-all` (`--all`) reruns every runner whatever its record says. At a
release, run it, so the release's results come from one full run. ADR 0016
holds either way: a failing case fails the run and blocks the merge.

## The hook tests

`tests/githooks/test_pre_commit.py`, `tests/githooks/test_pre_merge_commit.py`
and `tests/githooks/test_commit_msg.py` make real commits and merges in scratch
repositories that carry a copy of the hook. The pre-commit and pre-merge-commit
tests put a stand-in `just` first on `PATH`, which notes its arguments and
exits as it is told. The commit-message tests run the real
commitlint and are skipped, with a reason, where it is not installed.
`just test-rest` runs the affected ones, in parallel, from `just done`;
`just test-hooks` runs them all, and `just verify` includes it.

## Coverage

Coverage is reported, with missing lines shown and branches measured over
`sqlearn`. The floor, `fail_under = 95` in `pyproject.toml`, is enforced by the
full run, `just test-all`. `just test` measures no coverage, because testmon
cannot run beside branch coverage.
