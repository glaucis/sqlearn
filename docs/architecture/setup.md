# Setting up

How to get a working clone, the recipes it gives you, and what the two git
hooks do.

## A new laptop

```sh
brew install uv just commitlint
just setup
```

`just setup` points git's `core.hooksPath` at `.githooks` and runs
`uv sync --locked`, which installs the locked environment into `.venv` on the
Python floor, 3.12. Nothing else installs the hooks, so run it once after
every clone. uv is the only package tool
([ADR 0001](../adr/0001-uv-for-python-packaging.md)); `just` runs the recipes
([ADR 0008](../adr/0008-just-task-runner.md)).

## The recipes

`just --list` names every recipe, by group.

| Group | Recipes |
|---|---|
| setup | `setup` |
| format | `fmt`, `fmt-markdown`, `fmt-python` |
| check | `check`, `check-docstrings`, `check-lockfile`, `check-spelling`, `check-types`, `check-types-mypy`, `lint-markdown`, `lint-python`, `pre-commit`, `verify` |
| test | `test`, `test-all`, `test-hooks`, `test-python-versions` |
| docs | `build-docs`, `fetch-inventories`, `fetch-mathjax` |
| build | `build-package` |
| maintain | `clean`, `upgrade-dependencies` |

Two rhythms:

- **Every commit.** `just fmt`, then `just check` and `just test`. `just fmt`
  and its two parts are the only recipes that edit files.
- **Review, merge and release.** `just verify` runs `check`, mypy, the tests
  on every Python in the matrix, the hook tests, the docstring validation and
  the docs build.

When a composite recipe fails, `just` names the recipe that failed: run that
one alone.

## The pre-commit hook

`.githooks/pre-commit` exports the files going into the commit, the index
git hands it, to a temporary directory, and runs `just pre-commit` there
against the repository's own `.venv`. That is `just check` and
`just check-lockfile`. A failure refuses the commit, and the message names the
recipe and the cure: `just fmt` for formatting, `uv lock` for the lockfile,
`uv sync` for a missing tool. It checks the files in the commit, not the files
on disk, so another agent's unfinished file in the same working tree refuses
nothing. It runs no tests; `just test` is yours to run before a commit. A
failure HEAD already carries refuses every commit on its branch but the one
that mends it. Where `just` is not found, the commit is refused.

## The commit-message hook

`.githooks/commit-msg` checks the message with commitlint against
`commitlint.config.mjs` at the root, the one place the rules are kept. A
message that follows Conventional Commits passes; a warning is shown and never
refuses a commit; a broken rule refuses it. A merge, revert, cherry-pick or
rebase in progress passes, since git wrote that message. Where commitlint is
not found, the commit is refused with the cure, `brew install commitlint`.

Never skip either hook with `--no-verify`.

## Where work runs

Work is on the laptop for now. There is no CI and no bootstrap for Claude Code
web sessions, since the repository is private; the hooks, the reviewer and
`just verify` are the net, and Linux and Windows are a known gap. See [the
spec's out-of-scope list](../specs/foundation.md).
