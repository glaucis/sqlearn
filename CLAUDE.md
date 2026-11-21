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
  `docs/plans/2026-11-20-library-exploration.md`, ADR 0059, issue #74. sqlearn's
  own models are a goal, built in the engine; outside models stay supported (ADR
  0017, 0068). **Next:** chosen from `HANDOFF.md`'s "Next up".

Rules from the ADRs:

- Python packaging uses **uv**: `uv add`, `uv run`. Never use pip or a bare
  `python` (0001).
- Computation runs inside DuckDB: SQL, and the native engine's C++
  functions (`sqlearn_*`), which Python reaches only through the SQL it
  builds (0002, 0060). Apply SQL may call the engine where a benchmark
  shows it faster; each such function keeps a plain-SQL twin where one
  exists. Until the engine's Phase 2, a Gram step's learn sums XᵀX in
  numpy from batches DuckDB streams (0058).
- The API follows scikit-learn conventions; any departure needs its own ADR
  (0003). The verbs are sqlearn's own: `learn`/`apply` for steps,
  `train`/`predict` for models (0013).
- sqlearn runs on its own DuckDB build: the `duckdb` module, built from
  DuckDB's source at a pinned release with the engine compiled in, shipped
  as a second package beside sqlearn. With numpy it is the whole runtime;
  anything else needs a written reason (0005, 0057, 0061).
- Runtime code carries only permissive licences approved by the OSI (MIT,
  BSD, Apache-2.0, PSF, Boost, zlib, Unicode, ISC), never copyleft, each
  listed in the third-party file (0004, 0066).
- Nothing needs the network: no telemetry, no cloud, data never leaves the
  machine. sqlearn's DuckDB never downloads an extension by itself; one the
  user installs works (0006, 0061).
- Apple silicon first: macOS 15 or later gets the tuned build (CPU,
  matrix units, GPU); Linux and Windows get the safe CPU build; no Intel
  Macs, and no musl for now (0062).
- float64 runs on the CPU: Accelerate on macOS, OpenBLAS elsewhere. No
  MLX. GPU kernels are Metal, compiled ahead of time. Never `-ffast-math`
  (0063).
- The C++ follows the safety rules from its first commit: RAII, no raw
  `new` or `delete`, one thin layer for raw memory, warnings as errors,
  clang-tidy and the static analyser, sanitizers and fuzzing in CI, a
  hardened standard library, and no crash reaching the user (0065).
- Computation moves to the engine piece by piece, with `main` green: a
  piece moves when its C++ passes the same tests unchanged and is not
  slower, then its Python is deleted. A test of the public API changes
  only with an ADR (0067).
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

- **Once per clone, run `just setup`.** It installs the git hooks and syncs
  the environment.
- **Before every commit, `just check` and `just test` pass.** The pre-commit
  hook runs `just pre-commit` over the files going into the commit and refuses
  the commit when it fails; the commit-msg hook runs commitlint. `just test` is
  yours to run before you commit. Never `--no-verify`. Run `just fmt` before
  you commit: it wraps the Markdown at 80 columns and formats the Python, and
  its two parts are the only recipes that reformat your files.
- **Before you say any work is done, `just verify` passes**, and a reviewer's
  verdict says whether it ran and passed.
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
