---
type: architecture
tags: [setup, git-hooks, just, uv, commitlint]
summary: "Explains setting up a clone, the just recipes, and what the pre-commit, pre-merge-commit and commit-msg git hooks check."
related: [docs/adr/0001-uv-for-python-packaging.md, docs/adr/0008-just-task-runner.md, docs/adr/0062-apple-silicon-first.md, docs/specs/foundation.md, testing.md, commitlint.config.mjs, ADR 0001, ADR 0008]
mdindex: [type=4ca303, tags=191ee2, summary=b6ec20, related=1e9903]
---
# Setting up

How to get a working clone, the recipes it gives you, and what the git
hooks do.

## A new laptop

```sh
brew install uv just commitlint libomp
brew install llvm cmake ninja ccache include-what-you-use gitleaks
just setup
```

`just setup` points git's `core.hooksPath` at `.githooks`, runs `just doctor`,
fetches the submodules (`git submodule update --init --recursive`) and runs
`uv sync --locked`, which installs the locked environment into `.venv` on the
Python floor, 3.12. Nothing else installs the hooks, so run it once after every
clone. A missing tool is reported and the rest still runs; `just setup` then
exits 1.

`just doctor` checks the C++ toolchain: each tool's version, and
`Fix: brew install <tool>` for one that is missing. Apple clang (the Command
Line Tools) builds the wheel and the everyday presets; Homebrew LLVM, which is
keg-only and stays off `PATH`, runs clang-tidy, clang-format, clangd, the
sanitizers Apple clang lacks, fuzzing, coverage and Mull. gitleaks is the
pre-commit hook's secret check.

`uv sync` builds the package from source: DuckDB, its Python module and
sqlearn's C++ in one binary, from the submodules under `engine/`. The first
build took 3 min 36 s here (2026-11-23), and `just setup` on a fresh clone
about 10 minutes with the submodules' fetch. ccache keeps the compiled objects
(`engine/cmake/ccache.cmake`). `uv run` builds the module again when a commit
or a file of the engine changes (`[tool.uv] cache-keys` in `pyproject.toml`);
after a commit that took about 24 s. A compiler update rebuilds it too: `just
setup`, `just done` and `just verify` first run `just compiler-stamp`, which
writes the compiler's and the SDK's versions to `engine/.compiler-stamp`
(git-ignored, one of the cache keys) when they changed, and only then, since uv
keys a file on its modification time. A build without the submodules fails at
configure with the line that fixes it.

`libomp` is for LightGBM, a dev dependency whose macOS wheel needs the
system's OpenMP library; uv cannot provide it. uv is the only package tool
([ADR 0001](../adr/0001-uv-for-python-packaging.md)); `just` runs the recipes
([ADR 0008](../adr/0008-just-task-runner.md)).

## The recipes

`just --list` names every recipe, by group.

| Group | Recipes |
|---|---|
| setup | `compiler-stamp`, `doctor`, `fetch-mull`, `setup` |
| format | `fmt`, `fmt-engine`, `fmt-markdown`, `fmt-python` |
| check | `check`, `check-docstring-args`, `check-docstrings`, `check-licences`, `check-lockfile`, `check-mirror`, `check-no-devdata`, `check-secrets`, `check-spelling`, `check-stubs`, `check-types`, `check-types-mypy`, `checkable-tree`, `docstrings`, `done`, `format`, `full`, `headers-alone`, `iwyu-engine`, `lint`, `lint-markdown`, `lint-python`, `place`, `pre-commit`, `remember-tree`, `tidy`, `tidy-engine`, `types`, `verify` |
| test | `bench-engine`, `coverage-engine`, `fuzz`, `leaks-engine`, `mutate-engine`, `sanitize`, `sql`, `test`, `test-all`, `test-engine`, `test-engine-changed`, `test-hooks`, `test-python-versions`, `test-sql`, `validate`, `validate-all` |
| docs | `build-docs`, `docs`, `fetch-inventories`, `fetch-mathjax` |
| build | `api-snapshot`, `build-engine`, `build-package`, `stubs` |
| maintain | `clean`, `probe-cxx26`, `upgrade-dependencies` |

The C++ builds run under `just` (ADR 0008): `just build-engine <preset>`
configures and builds `engine/` with a CMake preset (`engine/CMakePresets.json`:
`dev`, `debug`, `release`, `profile`, `llvm-dev`, and the sanitizer, fuzzing,
coverage, mutation and SQL-test presets) into `engine/build/<preset>`, and
`just test-engine <preset>` runs its C++ tests with CTest. `just probe-cxx26`
prints which C++26 features each compiler here has; rerun it after an Xcode or
compiler update.

Which recipe runs when (a commit, a merge, work done, a release) is in
[the tiers' table](testing.md). The checks `just done` runs (`format`, `lint`,
`docstrings`, `types`, `tidy`, `test`, `sql`, `validate`, `docs`) each run on
what changed since they passed, and `just full <task>` runs one all through:
[testing](testing.md), "How each check finds what changed". The other `check-*`,
`lint-*` and `test-*` recipes run on everything, unrecorded. `just fmt` and its
three parts are the only recipes that reformat your files.

When a composite recipe fails, `just` names the recipe that failed: run that
one alone.

## The pre-commit hook

`.githooks/pre-commit` exports the files going into the commit, the index git
hands it, to a temporary directory, and runs `just pre-commit` there against the
repository's own `.venv`. That is `just check`, `just check-lockfile` and
`just check-secrets` (gitleaks: a key, a token or a password in the files
committed). A failure refuses the commit, and the message names the recipe and
the cure: `just fmt` for formatting, `uv lock` for the lockfile, `uv sync` for a
missing tool. It checks the files in the commit, not the files on disk, so
another agent's unfinished file in the same working tree refuses nothing. It
runs no tests; `just test` is yours to run before a commit. A failure HEAD
already carries refuses every commit on its branch but the one that mends it.
Where `just` is not found, the commit is refused with the cure,
`brew install just uv`. A checkout with no `.venv` is refused too, since the
hook would have nothing to run the checks with; the cure is `just setup` in that
checkout.

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

## The editor tools

clangd, Homebrew LLVM's, is the language server for the C++. The root
`.clangd` points it at the `llvm-dev` preset's compile database
(`engine/build/llvm-dev/compile_commands.json`), which
`just build-engine llvm-dev` writes. CodeGraph indexes sqlearn's own code,
`engine/` included; the root `codegraph.json` leaves out the submodules
(`engine/duckdb-python/`, `engine/third_party/`).

## Where work runs

Work is on the laptop for now. No CI runs by itself before `1.0.0`: the
workflows arrive with the native engine's Phase 1, step 3, and are started by
hand ([the Phase 1 spec](../specs/native-engine-phase-1.md), §3.5;
[ADR 0062](../adr/0062-apple-silicon-first.md)). There is no
bootstrap for Claude Code web sessions; the hooks, the reviewer and
`just verify` are the net, and Linux and Windows are a known gap. See [the
spec's out-of-scope list](../specs/foundation.md).
