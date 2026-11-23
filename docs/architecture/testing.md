---
type: guide
tags: [testing, pytest, coverage, hooks, tiers, checks]
summary: "Explains how tests are written, split into fast and slow tiers, how each check finds what changed and keeps its records, the hook tests, and coverage reporting in this project."
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
  `just check` and `just docstrings`) compares each docstring under `src/` with
  its signature: every argument written, a Returns section where the function
  returns. Types are written in the docstring, numpydoc's own style, so the
  recipe lets code DOC111 pass (no option drops it) and fails on any other. Its
  options are in `[tool.pydoclint]`.
- Warnings are errors (`filterwarnings = ["error"]`), so a deprecation is found
  the day it appears.

Where a test goes is in [the layout](layout.md): `tests/` mirrors the root.

## Two tiers

A test marked `slow` is the larger-than-memory tier. A plain `pytest` run
deselects it (`-m "not slow"`), and `--strict-markers` rejects a marker that is
not declared.

| Recipe | What it runs |
|---|---|
| `just test` | the tests, when what they read changed since a passed run: a parallel pass, the `serial` ones alone, the slow tier alone, then the hook tests in parallel; without coverage |
| `just test-all` | every test, the slow ones included, with coverage and the floor |
| `just test-python-versions` | the tests, slow ones included, on each Python in the matrix |
| `just test-hooks` | the hook tests alone |

`just test` is every agent's to run before a commit; `just done` is the check
before work is done, and `just verify` is the release tier.

| When | Recipe |
|---|---|
| A commit | the pre-commit hook: `just pre-commit` over the files committed |
| A push | none: a push runs no suite |
| A merge to `main` | the pre-merge-commit hook runs what the pre-commit hook runs; `just done` on `main` runs nothing for a tree that passed |
| Work is done | `just done`: `check-lockfile`, `check-mirror`, `check-no-devdata`, then each check on what changed (`format`, `lint`, `docstrings`, `types`, `test`, `validate`, `docs`), then the tree is remembered |
| A release | `just verify`: the same three, each check with `just full` (`validate` as `validate-all`), then `test-all` (coverage) and `test-python-versions`, by hand before `1.0.0` |

`just done` remembers each tree that passed in `sqlearn-passed`, in the git
common directory (the 50 newest, shared by worktrees), with the place it passed
in: `just place`, a hash of the Python, the platform and the machine, as each
task's digest starts with. The same tree after an OS update, on a new Python or
on another machine runs again. Only a tree with
nothing uncommitted counts, so a fast-forward or a `--no-ff` merge of a passed
tree runs nothing. Markdown is an input like any file (`format`, `lint` and
`docs` read it): edited and not committed, it leaves no checkable tree, and
`just done` runs; each task still skips what its records show passed, so that
costs seconds. `just done` runs every check even when one fails, as a task
runs every step, so one failure hides no other's findings; it exits with the
first failure's code, and nothing is remembered.

`just checkable-tree` ignores only the files the checks write:
`validation/**/*.results.json`, `validation/tests.json` and
`validation/environment.json`. They are outputs of `validate` and `test`, not
inputs, so a run that rewrites them leaves the tree it checked still HEAD's.

### When `just test` runs

`just test` runs the tests when anything they read changed since a passed run,
and nothing otherwise; `just full test` runs them whatever the record says.
What they read, and how a change is found, is in
"How each check finds what changed", below.

### The passes

`just test` runs four passes: every fast test on all cores (`-n auto`), the
tests marked `serial` alone without xdist (`-p no:xdist`), the slow tier
alone, and the hook tests in parallel. A test marked `@pytest.mark.serial`
fails beside other tests; its docstring says why, in one line (a wall-clock
ratio, a memory probe). The marker is never a way to hide a bug: a test that
fails in parallel is first understood, and fixed when its cause is shared
state (a fixed path becomes `tmp_path`, a learned store is cleared). Only the
serial pass may select nothing (pytest's exit 5): today no test is marked, so
the serial pass always collects nothing, and it is kept for a test that must
run alone; an empty fast, slow or hook pass is a broken marker or path, so it
fails.

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

The `validation._tests_report` plugin, loaded by every pass, writes
`validation/tests.json` and merges rather than rewrites. A file collected in
the run has its entries rebuilt from its collected tests: a test that ran
takes its new outcome, a test collected but deselected (`-k`, `-m`)
keeps its old one, and a test no longer in its file is dropped. The entries
of a file not collected stay unless the file is gone. Under xdist the
controller writes, from the reports and from the lists the workers sent, so a
parallel run writes the same bytes as a serial one.

## How each check finds what changed

Each check is a task in `validation/_checks.py` (`TASKS`), run by
`just <task>`. Before it runs, the task takes a digest of its inputs and
settings; when it passes, it records that digest. The next run skips what a
passed run already checked.

| Task | Its inputs | Runs on |
|---|---|---|
| `format` | every `*.py`, `*.pyi` and `*.md` file | each changed file: `ruff format --check`, `rumdl fmt --check` |
| `lint` | every file | each changed file: `ruff check` (Python), `typos` (every file), `rumdl check` (Markdown) |
| `docstrings` | the Python files under `src/` | each changed file: `numpydoc lint`, `just check-docstring-args` |
| `types` | every `*.py` and `*.pyi` file | the whole program: `ty check`, then `mypy` |
| `test` | `src/`, `tests/`, `validation/`, `devdata/`, `engine/` (with its submodules' commits), every `conftest.py`, `docs/conf.py`, `docs/architecture/engine-inventory.md`, `.githooks/`, `commitlint.config.mjs` | the C++ groups whose program changed (below), then every test: the four passes (above) |
| `docs` | `docs/`, `src/`, `examples/` | the whole site: `just build-docs` |
| `validate` | each runner's imported modules, `uv.lock`, `devdata/data/` | each changed runner, by its own records (below) |

Every task also reads the settings: `pyproject.toml`, `uv.lock`,
`.python-version` and the `justfile`, and each tool's own configuration file at
any depth (`pyproject.toml`, `ruff.toml`, `.ruff.toml`, `typos.toml`,
`_typos.toml`, `.typos.toml`, `rumdl.toml`, `.rumdl.toml`, `mypy.ini`,
`.mypy.ini`, `ty.toml`), so one added reruns every file it governs.

- **Per file** (`format`, `lint`, `docstrings`): a file is checked again
  unless a kept record passed it, with the same digest, under today's
  settings. A change to the settings checks every file. `lint` also counts
  which Python files exist, since ruff's import sorting depends on it: a
  Python file added or removed reruns every `lint` step on every file, the
  Markdown and the spelling included.
- **Whole** (`types`, `test`, `docs`): the task runs all of it when its digest
  matches no kept record, and nothing otherwise.
- Every step runs even when one before it fails, so one tool's failure hides
  no other's findings. A run that fails records nothing, so the next run
  checks the same again.

**What a digest covers.** Each file's path, its executable bit and its bytes,
for the tracked files and the untracked ones git does not ignore. A deleted
file drops out, which changes the digest; a new one adds to it. The place a
task runs in leads every digest: the Python version, the platform and the
machine, so another Python reruns every task. The checks' own outputs
(`validation/tests.json`, `validation/environment.json`,
`validation/**/*.results.json`) are never inputs. The digest is taken before
the run and only that one is recorded, and only when the inputs are the same
after the run: a file edited while a check runs is checked again.

**The records** live in `sqlearn-checks/` in git's common directory (`git
rev-parse --git-common-dir`), one JSON file per task holding its 20 newest.
Every worktree shares them. Two worktrees recording at once can lose a record,
which costs a rerun, never a skip; a file that cannot be read counts as
absent. Deleting the directory makes the next run of each task check
everything.

**`just full <task>`** runs one task all through, whatever its records say,
and records the pass. `just full validate` is `just validate-all`. `just
verify` runs every task this way.

**`validate`** is not in the table of `validation/_checks.py`: it keeps a
record for each runner (the validation runners, below).

**The C++ groups.** The `test` task's first step, `just test-engine-changed
dev` (`validation/_ctest.py`), builds the `dev` preset (Ninja rebuilds only
what changed) and runs, with `ctest -L ^<group>$`, each group whose identity
no kept record passed, printing `<group>: unchanged since a passed run` for
the rest. Each CTest label is one unit: a group's (its program `test_<group>`)
or `must_not_compile`, which every must-not-compile test carries. A group's
identity is the hash of its program's bytes, with its CTest entry (command,
properties) and the place: the checks' place and the preset's compiler id and
version. Ninja relinks a program only when one of its objects changed, and
`sq_stable_link` (`engine/cmake/groups.cmake`) sets `ZERO_AR_DATE` for the
link on macOS, so a relink of the same objects gives the same bytes (Apple's
linker otherwise writes each object's modification time into the debug map).
A must-not-compile test has no program: its identity is the compile commands
of the target it builds (from `compile_commands.json`), its source and every
header under the directories those commands include with `-I`. The records
are `ctest-<preset>.json` in `sqlearn-checks/`, under the same rules as the
tasks'; a record names every group passed or found unchanged in a run, a
failed group is not in it, and a build that fails runs and records nothing. A
test with no label is refused with a `Fix:` line, since no group would run
it. The step runs even when the `test` task is unchanged since a passed run,
before it prints so: what its records name and no input of the task does (the
compiler) still reruns a group. `just full test` passes `--all`, which runs
every group.

## The validation runners

`just validate` (`python -m validation`) reruns a runner only when a file it
depends on changed since it last passed. Each runner runs in its own process,
writes its `*.results.json` as before, and then saves a record: the SHA-256 of
every module it imported from the repository (outside `.venv`), of `uv.lock` and
of every file under `devdata/data/`, with the environment (`environment.json`'s
fields: library versions, Python, the OS and its release, the machine, BLAS),
the count of each result and whether every sqlearn case passed. The hashes are
taken before the runner is imported: a file it loaded that changed while it ran,
or was not there before, saves no passed record, printing `not recorded` and the
files, so results of the old code are never recorded as the new code's. A record
file that cannot be read or parsed counts as absent. The next run skips a
runner, printing `unchanged since a passed run` and leaving its results file
alone, when the newest record with the same environment and every file it names
present with the same hash passed. A run with a failing case reruns every time,
and it cancels any earlier pass of the same inputs. `environment.json` is
written when any runner ran. The code is `validation/_record.py`.

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
`just test` runs them as its last pass, and so do `just done` and `just
verify`; `just test-hooks` runs them alone.

## Coverage

Coverage is reported, with missing lines shown and branches measured over
`sqlearn`. The floor, `fail_under = 95` in `pyproject.toml`, is enforced by the
full run, `just test-all`. `just test` measures no coverage.
