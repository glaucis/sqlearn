# sqlearn

An alternative to the scikit-learn ecosystem whose computation runs as SQL
inside DuckDB, so it works on data larger than memory and a whole pipeline can
execute as one query. Independent of scikit-learn. With it come documentation,
a learning site, and later two local applications (data exploration, a
node-based workflow editor). The foundation (package skeleton, checks, hooks,
site) and the library core (steps, pipeline, learning store, search) are
built.

- **The map:** `docs/architecture/overview.md` (the parts and their order).
  **How work runs:** `docs/architecture/workflow.md`. **Decisions:**
  `docs/adr/`. **Done:** the library core (part 3.2): spec
  `docs/specs/library-core.md`, decisions ADRs 0012–0033, summary and deferred
  findings in issue #8. The library breadth (part 3.3) goes one spec per area.
  Its first area, preprocessing, is built: spec
  `docs/specs/library-preprocessing.md`, plan
  `docs/plans/2026-11-06-library-preprocessing.md`, ADRs 0034–0038, summary in
  issue #30. Its second, model selection, is built: spec
  `docs/specs/library-model-selection.md`, plan
  `docs/plans/2026-11-07-library-model-selection.md`, ADRs 0039–0041, summary in
  issue #33. Its third, metrics (precision, recall, F1), is built: spec
  `docs/specs/library-metrics.md`, plan
  `docs/plans/2026-11-09-library-metrics.md`, ADR 0042, summary in issue #34.
  Its fourth, datasets, was built and then moved out of the package: sqlearn
  ships none, and `devdata/` keeps them for development only (ADR 0053,
  issue #61). Its fifth, saving a pipeline (`sq.save`, `sq.load`), is built:
  spec `docs/specs/library-saving.md`, plan
  `docs/plans/2026-11-11-library-saving.md`, ADR 0047, summary in issue #57. Its
  sixth, more metrics (`fbeta`, `average_precision`, `confusion_matrix`,
  `classification_report`, `roc_curve`, `precision_recall_curve`), is built:
  spec `docs/specs/library-more-metrics.md`, plan
  `docs/plans/2026-11-13-library-more-metrics.md`, ADR 0049, summary in
  issue #58. Its seventh, balanced scores (`balanced_accuracy`, `mcc`, `brier`),
  is built: spec `docs/specs/library-balanced-scores.md`, plan
  `docs/plans/2026-11-19-library-balanced-scores.md`, issue #62. Its eighth,
  regression metrics, is built: spec `docs/specs/library-regression-metrics.md`,
  plan `docs/plans/2026-11-19-library-regression-metrics.md`, ADR 0054, summary
  in issue #63. Its ninth, feature selection (`sq.select.variance`, `best`,
  `percentile`), is built: spec `docs/specs/library-feature-selection.md`, plan
  `docs/plans/2026-11-19-library-feature-selection.md`, ADRs 0055–0056, summary
  in issue #65. Its tenth, decomposition (PCA, `sq.decompose.pca`), is built:
  spec `docs/specs/library-decomposition.md`, plan
  `docs/plans/2026-11-20-library-decomposition.md`, ADRs 0057–0058, summary in
  issue #66. Part 3.6's first piece, the exploration module (`sq.explore`:
  `profile`, `histogram`, `top`, `missing`, `correlations`), is built: spec
  `docs/specs/library-exploration.md`, plan
  `docs/plans/2026-11-20-library-exploration.md`, ADR 0059, issue #74. The
  native engine (part 3.10: sqlearn as a C++ library embedding DuckDB, Python
  its bindings): spec `docs/specs/native-engine.md`, ADRs 0060–0071, the
  rewrite's inventory `docs/architecture/engine-inventory.md`, milestone
  "Native engine" (#78 to #84). Phase 0 is done; Phase 1's steps 1 (the
  checks) and 2 (the build) are merged. The library is rewritten in C++
  (ADR 0070, superseding 0067), and the rewrite comes before any new
  area. sqlearn's
  own models are a goal, built in the engine; outside models stay supported (ADR
  0017, 0068). **Next:** chosen from `HANDOFF.md`'s "Next up".

Rules from the ADRs:

- Python packaging uses **uv**: `uv add`, `uv run`. Never use pip or a bare
  `python` (0001).
- sqlearn is a C++ library embedding DuckDB. Python is thin nanobind
  bindings with no logic of their own, as it will be at the end of the
  rewrite (0070); users' own steps stay writable in
  Python. Other languages bind later, through a C layer when they need
  one. The C++ API is internal: only `sq.` is public (0060).
- Computation runs inside DuckDB: the SQL the library builds, and
  sqlearn's C++ functions (`sqlearn_*`) registered in it (0002, 0060).
  Apply SQL may call them where a benchmark shows it faster; each keeps a
  plain-SQL twin where one exists. Until the engine's Phase 2, a Gram
  step's learn sums XᵀX in numpy from batches DuckDB streams (0058, 0070).
- The API follows scikit-learn conventions; any departure needs its own ADR
  (0003). The verbs are sqlearn's own: `learn`/`apply` for steps,
  `train`/`predict` for models (0013).
- sqlearn runs on its own DuckDB build: the `duckdb` module, built from
  DuckDB's source at a pinned release (git submodules under `engine/`, never
  edited), the same DuckDB the C++ library runs in. One package: the wheel
  `sqlearn` holds `sqlearn/`, `duckdb/` and the one binary with sqlearn's
  C++ inside. With numpy it is the whole runtime; anything else needs a
  written reason (0005, 0057, 0060, 0061).
- The C++ is C++23, built by CMake under `just`: Apple clang for the release
  and everyday builds, Homebrew LLVM for clang-tidy, clangd, the sanitizers
  Apple clang lacks, fuzzing, coverage and Mull (0008, spec §3.8 of
  `docs/specs/native-engine-phase-1.md`).
- Runtime code carries only permissive licences approved by the OSI (MIT,
  BSD, Apache-2.0, PSF, Boost, zlib, Unicode, ISC), never copyleft, each
  listed in the third-party file (0004, 0066).
- Nothing needs the network: no telemetry, no cloud, data never leaves the
  machine. sqlearn's DuckDB never downloads an extension by itself; one the
  user installs works (0006, 0061).
- Apple silicon first: macOS 15 or later gets the tuned build (CPU, matrix
  units, GPU); Linux and Windows get the safe CPU build, with general
  optimisations; no Intel Macs, and no musl for now (0062).
- float64 runs on the CPU: Accelerate on macOS, OpenBLAS elsewhere. No MLX. GPU
  kernels are Metal, compiled ahead of time; Phase 6 tries Mojo beside it, and
  it becomes the kernels' language if it matches Metal (0063). Never
  `-ffast-math` (0063). FMA contraction is off: a kernel fuses only by
  calling `std::fma` (Metal's `fma()`), validated; contraction is turned
  on for one target or kernel only when its benchmark shows a gain and
  the validation passes (0071).
- The C++ follows the safety rules from its first commit: RAII, no raw
  `new` or `delete`, one thin layer for raw memory, warnings as errors,
  clang-tidy and the static analyser, sanitizers and fuzzing in
  `just verify` and in workflows started by hand, a hardened standard
  library, and no crash reaching the user (0065).
- The library is rewritten in C++ one inventory group at a time, with
  `main` green, each group designed for C++, not translated from the
  Python. The Python library is frozen: no new features, fixes only where
  a bug blocks the work. A group merges when its C++ tests and the
  validation runners it touches pass and its benchmark is not slower than
  the Python it replaces; in the same merge its Python is deleted with
  every test of it. Behaviour inside the library is tested in C++,
  behaviour seen through `sq.` in Python. Before `1.0.0` the `sq.` API
  may change in the commit that needs it, recorded in
  `tests/public_api.txt`; only a departure from scikit-learn's
  conventions needs an ADR. Files saved before the rewrite need not load
  after it; `sq.load`'s security rules hold (0070).
- Python 3.12 is the floor (0007). Every task runs through `just` (0008).
- British English in prose, American spelling in identifiers (0010).
- sqlearn ships, generates and fetches no datasets: the user brings their
  own. `devdata/` at the root is for developing sqlearn: it never ships,
  `src/` never imports it, and published docs do not use it (0053).
- sqlearn never changes on its own what the user asked for: it keeps the
  default, warns with a `Fix:` line, and the user opts in (0046). The one
  exception: on Apple silicon a kernel runs on the GPU by itself when its
  answer is bit for bit the CPU's (0064).

Superpowers skills save specs to `docs/specs/` and plans to `docs/plans/`
here, not `docs/superpowers/`.

## Working with Tomas

How to explain choices to him and keep track of the work:
`docs/agents/working-with-tomas.md`. Keep nothing in Claude's auto-memory:
everything a later session needs goes into the repository (rules here and
in the ADRs, the state of work in `HANDOFF.md`, decisions on the issues).

## Current state of work

@HANDOFF.md

`HANDOFF.md` is the current state of work: in progress, waiting on me, next
up, dead ends. The `/handoff` skill creates and updates it, and it lives in
the repository only, never in memory files.

- Start every session from it, and re-check each item marked [assumed] before
  relying on it.
- When you finish an item it lists, update it in the same commit as the work:
  move the item to "Just finished" with its commit or issue, and remove what
  no longer applies.

## Commit conventions

This repository's history must contain no AI or tool attribution.

- Never add `Co-Authored-By:` trailers for Claude, Anthropic, or any AI tool.
- Never add "Generated with Claude Code", `Claude-Session:` links, or similar
  lines to commit messages, PR titles, or PR descriptions.
- Commit messages end after the body. Add a trailer only when I ask for one.
- Do not add "generated by AI/Claude" notes in code comments, file headers,
  docs, or changelogs.
- Leave git author/committer configuration as it is.

### Every new repo carries this itself

`~/.claude/` is not loaded by Claude Code web sessions: they clone a repo and
get nothing else. So when scaffolding or first committing to a new repository,
commit both of these into it, without being asked:

1. `.claude/settings.json` containing:

   ```json
   {
     "attribution": { "commit": "", "pr": "", "sessionUrl": false }
   }
   ```

2. The section above in the repo's own `CLAUDE.md`.

## Checks

- **Once per clone, run `just setup`.** It installs the git hooks, checks the
  C++ toolchain (`just doctor`; `brew install llvm cmake ninja ccache
  include-what-you-use gitleaks`), fetches the submodules and syncs the
  environment, which builds DuckDB with sqlearn's C++ (minutes the first
  time). `docs/architecture/setup.md` has the details.
- **Before every commit, `just check` and `just test` pass.** The pre-commit
  hook runs `just pre-commit` (`just check`, `just check-lockfile` and
  `just check-secrets`, gitleaks) over the
  files going into the commit and refuses the commit when it fails; the
  commit-msg hook runs commitlint. `just test` is yours to run before you
  commit: it runs the tests when what they read changed since a passed run.
  Never `--no-verify`. Run `just fmt` before you commit: it wraps the Markdown
  at 80 columns and formats the Python, the C++ and the CMake files, and its
  three parts are the only recipes that reformat your files.
- **Before you say any work is done, `just done` passes.** It runs
  `check-lockfile`, `check-mirror` and `check-no-devdata`, then each check
  (`format`, `lint`, `docstrings`, `types`, `tidy`, `test`, `sql`, `validate`,
  `docs`) on what changed since it passed, every one even when another fails,
  and remembers the tree that passed (nothing uncommitted but the checks'
  outputs), so a passed tree (after a fast-forward or a merge too) runs nothing
  again in the same place (Python, platform, machine), and everything in a new
  one. `just full <task>` runs one check all through. `just verify` is the
  release tier: every check in full, then the sanitizers, the leak check of
  the release build (`leaks-engine`), a minute of fuzzing,
  the C++ coverage gate, mutation testing, the licence check, coverage and every
  Python, run by hand before `1.0.0` (an hour or more). A reviewer's verdict
  says which ran and passed. How a check finds what changed:
  `docs/architecture/testing.md`.
- **`just --list` names every recipe.** When a composite fails, `just` names
  the recipe that failed: run that one alone.
- **The conventions are in `docs/architecture/`**: the layout, the Python
  versions, how documentation and tests are written. Read the page for the
  work in hand.

## Skills and routine work

- TDD: follow superpowers test-driven-development. Watch each test fail for
  the right reason, then run the whole suite and name every failure. Test
  through public seams in vertical slices (one test, then its code), and name
  tests in `GLOSSARY.md` terms. When mattpocock implement or implement-spec
  calls `tdd`, follow this line instead.
- Bugs: use mattpocock diagnosing-bugs. Before any fix, have one fast command
  that fails on this exact bug. Tag debug logs `[DEBUG-xxxx]` and remove them
  at the end. After 3 failed fixes, stop and rethink; if the bug still
  resists, offer a workflow with parallel hypotheses.
- Before each commit: the checks above, and name every failure.
- GitHub: keep issues, milestones, labels and board status in sync as you work
  (github-pm skill).
- Docs: when behaviour changes, update the docs that describe it; `/docs-sync`
  does a full pass.

## Project tools

- **CodeGraph:** code map in `.codegraph/`, updates on save. Use
  `codegraph_explore` before grep or reading files. Off: `codegraph uninit`.
- **Docs layout:** `docs/adr/` (decisions), `docs/architecture/` (how it works),
  `docs/specs/` (what to build), `docs/plans/` (how to build it),
  `docs/questions/` (open questions). New decision → new ADR. Answered question
  → move the answer into the right doc.
- **Docs index:** docs are tagged automatically (frontmatter `type`, `tags`,
  `summary`, `related`) and searchable with `qmd query "<question>" -c sqlearn`.
  Search here before grepping docs. Status: `mdindex status`. Off: delete
  `.mdindex/` and run `qmd collection remove sqlearn`.
- **Matt Pocock setup:** see `docs/agents/` for the issue tracker and the domain
  doc rules.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for glaucis/sqlearn, managed with the `gh`
CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default triage labels: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See
`docs/agents/domain.md`.
