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
- Warnings are errors (`filterwarnings = ["error"]`), so a deprecation is found
  the day it appears.

Where a test goes is in [the layout](layout.md): `tests/` mirrors the root.

## Two tiers

A test marked `slow` is the larger-than-memory tier. A plain `pytest` run
deselects it (`-m "not slow"`), and `--strict-markers` rejects a marker that is
not declared.

| Recipe | What it runs |
|---|---|
| `just test` | the fast tests, with coverage, without `tests/githooks` |
| `just test-all` | every test, the slow ones included, with coverage |
| `just test-python-versions` | the tests, slow ones included, on each Python in the matrix |
| `just test-hooks` | the hook tests alone |

`just test` is every agent's to run before a commit; `just verify` runs the
rest.

## The hook tests

`tests/githooks/test_pre_commit.py`, `tests/githooks/test_pre_merge_commit.py`
and `tests/githooks/test_commit_msg.py` make real commits and merges in scratch
repositories that carry a copy of the hook. The pre-commit and pre-merge-commit
tests put a stand-in `just` first on `PATH`, which notes its arguments and
exits as it is told. The commit-message tests run the real
commitlint and are skipped, with a reason, where it is not installed.
`just test-hooks` runs them, and `just verify` includes it.

## Coverage

Coverage is reported, with missing lines shown and branches measured over
`sqlearn`. There is no floor yet: the core spec sets it, measured on the full
suite.
