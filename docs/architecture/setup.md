---
type: architecture
tags: [setup, git-hooks, just, uv, commitlint]
summary: "Explains how to set up a clone, the just recipes by group, and what the pre-commit, pre-merge-commit and commit-msg hooks check."
related: [docs/adr/0001-uv-for-python-packaging.md, docs/adr/0008-just-task-runner.md, docs/adr/0062-apple-silicon-first.md, docs/specs/foundation.md, commitlint.config.mjs, ADR 0062]
mdindex: [type=4ca303, tags=191ee2, summary=74a9d4, related=58b62f]
---
# Setting up

How to get a working clone, the recipes it gives you, and what the two git
hooks do.

## A new laptop

```sh
brew install uv just commitlint libomp
just setup
```

`just setup` points git's `core.hooksPath` at `.githooks` and runs
`uv sync --locked`, which installs the locked environment into `.venv` on the
Python floor, 3.12. Nothing else installs the hooks, so run it once after every
clone. `libomp` is for LightGBM, a dev dependency whose macOS wheel needs the
system's OpenMP library; uv cannot provide it. uv is the only package tool
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
  and its two parts are the only recipes that reformat your files.
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
that mends it. Where `just` is not found, the commit is refused with the cure,
`brew install just uv`. A checkout with no `.venv` is refused too, since the
hook would have nothing to run the checks with; the cure is `just setup` in
that checkout.

A merge that completes without conflicts runs git's `pre-merge-commit` hook
instead of `pre-commit`. `.githooks/pre-merge-commit` hands over to
`.githooks/pre-commit`, so a merge commit gets the same checks on the merge's
result. A merge that stops on a conflict is committed with `git commit`, which
runs `pre-commit` itself.

## The commit-message hook

`.githooks/commit-msg` checks the message with commitlint against
`commitlint.config.mjs` at the root, the one place the rules are kept. A message
that follows Conventional Commits passes; a warning is shown and never refuses a
commit; a broken rule refuses it. A merge, revert, cherry-pick or rebase in
progress passes, since git wrote that message, or it was checked when it was
written. In an interactive rebase the hook reads the step being run, the last
line of `rebase-merge/done`: a `reword`, and any commit made at an `edit`
stop, is a message written now and is checked; every other step passes. Where
commitlint is not found, the commit is refused with the cure,
`brew install commitlint`. A `fixup!` or `squash!` subject is refused by design,
since the rules ignore nothing; reword it, or fold it in before committing.

Never skip either hook with `--no-verify`.

## Where work runs

Work is on the laptop for now. There is no CI yet: it arrives with the native
engine's Phase 1 ([ADR 0062](../adr/0062-apple-silicon-first.md)). There is no
bootstrap for Claude Code web sessions; the hooks, the reviewer and
`just verify` are the net, and Linux and Windows are a known gap. See [the
spec's out-of-scope list](../specs/foundation.md).
