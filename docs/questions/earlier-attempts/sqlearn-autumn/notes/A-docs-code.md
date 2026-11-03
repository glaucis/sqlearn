---
type: note
tags: [sqlearn, rehearsal, agent-rules, foundation-spec, validation]
summary: "Batch A review of the OLD sqlearn repo: its foundation spec, the agent-rule rehearsal cases, and what carried over to the current repository."
related: [docs/specs/foundation.md, docs/questions/agents-and-skills.md, CLAUDE.md, commitlint.config.mjs, docs/superpowers/plans/2026-10-01-foundation-closing.md, docs/superpowers/specs/2026-10-01-foundation-design.md, docs/superpowers/plans/2026-10-02-case-one.md, docs/superpowers/plans/2026-10-03-case-three.md]
mdindex: [type=edb465, tags=59f4b1, summary=8207ad, related=cf9360]
---
# sqlearn, autumn: batch A, docs and code

Source (read only), called OLD below: "/Users/tomas/Desktop/Desktop -
Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn", GitHub `glaucis/sqlearn`,
30 September to 4 October 2026, branches `main` and `rehearsal` (checked out:
`rehearsal`, read from `.git/HEAD` as a file; no git command was run). Batch:
`docs/` (81 files), `tests/` (5 test files and 6 compiled caches),
`rehearsal/` (2), and the root files `CLAUDE.md`, `pyproject.toml`,
`commitlint.config.mjs` and `.gitignore`. No file in the batch was cloud-only;
every read finished.

## Summary

- OLD has no ADRs, no `docs/questions/` and no product code. Its decisions sat
  in a `BLUEPRINT.md` that is not in the tree any more (its sections 4 to 6 were
  moved into the foundation spec,
  OLD:docs/superpowers/plans/2026-10-01-foundation-closing.md:L426-L442); the
  blueprint itself belongs to batch B or the history.
- Its one design document is the foundation spec, approved section by section on
  2026-10-01 (21 rows,
  OLD:docs/superpowers/plans/2026-10-01-foundation-closing.md:L333-L357), and
  its implementation plan of ten tasks and 36 rulings. On this branch the
  foundation was not built: `pyproject.toml` is still "Not an installable
  package yet" (OLD:pyproject.toml:L15-L17).
- The current repository carried the spec over almost whole
  (`docs/specs/foundation.md` says so, and lists the changes in its §19); it
  dropped the web bootstrap, `records/`, the copied skills and agents, and the
  session-start author fix.
- The rest of `docs/` (about 70 files) is "the rehearsal": four plans that
  test `CLAUDE.md`'s agent rules (stop and ask, the bug ladder, pauses,
  resumes) on toy code, with planted faults, orphan branches and nested
  agents up to five deep.
- The rehearsal's cover code touches the library only in passing: an
  identifier-quoting helper and a `PolynomialFeatures`-named `SELECT` writer
  (case three), and an AS 241 normal quantile, a probit link, softplus and
  log-sigmoid with ulp sweeps against `decimal` (case four).
- Bearing on the open questions: nothing on fit execution or learned state; a
  hand-built SQL string with no sqlglot, and a reserved-word list that DuckDB
  itself can give (`duckdb_keywords()`); for validation, a deterministic,
  chunked ulp sweep against a 50-digit `decimal` reference, results committed
  as text.
- One validation trap found: Python's `statistics.NormalDist.inv_cdf` is itself
  AS 241, so it cannot serve as an independent reference for an AS 241
  implementation
  (OLD:docs/superpowers/plans/2026-10-03-case-four-work/results/plant-check.out).
- Confirms the baseline's process finding at its extreme: 316 commits, a
  3,174-line plan for a rehearsal, and no line of library code.

## Aim and decisions

What OLD set out to do: build sqlearn's foundation (part 3.1 of a blueprint,
OLD:docs/superpowers/specs/2026-10-01-foundation-design.md:L3-L9), then, before
"a ten-task plan runs on them with some twenty agents", rehearse the agent
rules of `CLAUDE.md` one case at a time
(OLD:docs/superpowers/plans/2026-10-02-case-one.md:L24-L26).

There are no ADRs and no question files in the batch. The decisions found:

- **The foundation spec's 21 rows**, approved 2026-10-01: the layout, hatchling
  with hatch-vcs, three dependency groups, `duckdb` the one dependency, Python
  3.12 floor with a 3.12 to 3.14 matrix, ruff, ty plus mypy strict over `src/`,
  pytest strict with warnings as errors, numpydoc validation, rumdl at 80
  columns with reflow, typos at locale `en`, the `justfile`, a Sphinx site with
  seven sections and offline MathJax
  (OLD:docs/superpowers/plans/2026-10-01-foundation-closing.md:L340-L357).
- **Three questions to Tomas**
  (OLD:docs/superpowers/specs/2026-10-01-foundation-design.md:L1560-L1654): the
  per-commit gate runs `just pre-commit` (`check`, then `check-lockfile`) over
  an export of the commit's files, with no tests (L1590-L1608); Python 3.13 and
  3.14 in a web session by allowing `releases.astral.sh` (L1631-L1636);
  commitlint kept over commitizen, gitlint and a home-made checker, "simple and
  direct" (L1638-L1654).
- **The agent rules of `CLAUDE.md`**: an order of instructions with this file
  first (OLD:CLAUDE.md:L5-L17); an unclear or forked instruction is a stop,
  never a guess (L27-L39); "Mistake", "Bug" and "Idea", with a bug climbing one
  rung at a time, one investigator per rung, pauses of every running agent
  (L76-L172); records in `records/` (L174-L218); every agent `opus` or `sonnet`,
  never Explore, Plan or a fork (L252-L272); commit by path and push at once
  (L274-L290); no AI credit (L292-L310); prose at 80 columns (L312-L323).
- **The project file**: Python `>=3.11`, no dependencies, `pytest` only,
  `filterwarnings = ["error"]` (OLD:pyproject.toml:L8-L23).

## What was built

- **No library code.** The only Python outside the rehearsal is the hook tests.
- **`tests/hooks/`**: five files, 48 test functions (162 tests with their
  parameters, OLD:docs/superpowers/plans/2026-10-02-case-one.md:L13), for the
  `commit-msg` hook and commitlint (17 functions), a `records/` file-name hook
  (14), `session-start.sh` writing the session's real author in a web
  container (11), the quoting of `$CLAUDE_PROJECT_DIR` in
  `.claude/settings.json` (3), and the superpowers session hook (3)
  (OLD:tests/hooks/test_commit_msg.py:L1-L15, test_session_start.py:L1-L15).
  The hooks themselves are in `.claude/`, batch B.
- **`commitlint.config.mjs`**: eleven types, scopes naming the agent engine
  (`commit`, `records`, `orchestrator`, `session`, `settings`, `superpowers`).
- **The foundation plan** (2,161 lines): written and approved, not run on this
  branch. Its Tech Stack pins DuckDB 1.5.6
  (OLD:docs/superpowers/plans/2026-10-01-foundation.md:L20-L23).
- **The rehearsal's sketches**, all pure Python and none running DuckDB:
  `rehearsal/slug.py` (case one), `sqltext/` (case three, embedded in its
  plan), `stats/`, `logexp/` and `tools/sweep.py` (case four, under
  `2026-10-03-case-four-work/`).

## Rehearsal

"Rehearsal" is the branch, and the four plans run on it, that tested whether
agents follow `CLAUDE.md`'s rules when something goes wrong. Each case plants
one fault in a cover task and hides from the agents that it is a test.

- **Case one** (2 October): a brief whose rules 3 and 6 give one input opposite
  outcomes; the agent must stop up front, record, be resumed by `SendMessage`
  and finish (OLD:docs/superpowers/plans/2026-10-02-case-one.md:L9-L11,
  L35-L53). Cover code: `slugify` and `unique_slug`
  (OLD:rehearsal/slug.py:L11-L38, with seven tests in
  OLD:rehearsal/test_slug.py). Twelve of thirteen checks passed; the thirteenth
  found that the agent had read two archived records describing the plant
  (OLD:docs/superpowers/plans/2026-10-02-case-two.md:L28-L40).
- **Case two**: the same, rerun in a worktree on an orphan branch with nothing
  describing the rehearsal in reach; it passed
  (OLD:docs/superpowers/plans/2026-10-03-case-three.md:L41-L47).
- **Case three** (3 October): a bug one rung down under a controller running
  `subagent-driven-development`. The plant is `sqltext/identifiers.py`, whose
  reserved-word set is built by `split(" ")` over a wrapped block, so 15 of 75
  words keep a newline and never match
  (OLD:docs/superpowers/plans/2026-10-03-case-three.md:L350-L360). The
  controller found the bug itself before Task 1, so no implementer stopped and
  no investigator ran
  (OLD:docs/superpowers/plans/2026-10-03-case-four.md:L258-L264). The run took
  four hours for a two-task plan (L245-L246).
- **Case four** (3 to 4 October, 3,174 lines plus a 70-file work folder): a bug
  five rungs down, beside sweepers at work, climbing to Tomas twice (a scripted
  wrong answer, then the right one), and a question climbing the same rungs
  (OLD:docs/superpowers/plans/2026-10-03-case-four.md:L65-L131). The plant is
  two swapped digits in `e0` of an AS 241 table "of Tomas's"
  (OLD:docs/superpowers/plans/2026-10-03-case-four-work/ladder/stats/as241.toml:L1-L8).
  Its harness facts were tried in `trials/harness/` (a message reaches an agent
  at its next tool round; a resume keeps context several rungs deep; an agent
  woken after handing back reports to `main`, past its caller,
  OLD:docs/superpowers/plans/2026-10-03-case-four.md:L293-L304). The work
  folder's `results/final-pass.out` and `final-review.out` are a stand-in dry
  run of 2026-10-04; whether the real run happened is not in this batch
  (records, batch B).

## Against the current repository

**Carried over** (the current `docs/specs/foundation.md` is this spec adapted;
its §18 and §19 say what came and what changed):

- The foundation spec, nearly whole: layout, packaging, tool configuration,
  the `justfile`, the site with seven sections and offline MathJax, the slow
  spill test under `memory_limit = '64MB'`
  (OLD:docs/superpowers/specs/2026-10-01-foundation-design.md:L1345; now
  `tests/test_environment.py:L13-L23`).
- The per-commit gate decision and commitlint, as the spec's §18.
- `commitlint.config.mjs`: the same rules, scopes reset to `hooks`, `site`,
  `deps`, the hook path changed to `.githooks/` (diffed against the current
  file).
- The commit conventions block, word for word, in `CLAUDE.md`
  (OLD:CLAUDE.md:L292-L302).
- The `CLAUDE.md` "Checks" block of the spec's §14
  (OLD:docs/superpowers/specs/2026-10-01-foundation-design.md:L1431-L1450),
  less the records-only exemption.
- `duckdb` the one runtime dependency, the 3.12 floor, British prose with
  American identifiers, the curriculum levels: now ADRs 0005, 0007, 0010 and
  0011 (inference: they came from the blueprint the spec cites, which is not
  in this batch).
- No CI while the repository is private (OLD spec §16, now the current
  spec's §16).

**Dropped** (the current spec's §19 names most):

- The web-session bootstrap (OLD spec §10) and its tests.
- `records/`, the bug ladder, pauses, one investigator per rung, and the
  order-of-instructions rules (OLD:CLAUDE.md:L5-L272). The current repository
  uses GitHub Issues and `docs/questions/` instead.
- The rule that agents are only `opus` or `sonnet`, never Explore, Plan or a
  fork (OLD:CLAUDE.md:L252-L265); the current workflow lists the built-in
  Explore and Plan agents as tools.
- The hook tests for `record-names.py`, `session-start.sh` and the settings
  quoting; only `commit-msg` and `pre-commit` tests exist now
  (`tests/githooks/`).
- The rehearsal and all its sketches.

**Lost, and worth a look:**

- The settings-quoting rule: an unquoted `$CLAUDE_PROJECT_DIR` in a shell-form
  hook silently never runs in a path with a space
  (OLD:tests/hooks/test_settings_hooks.py:L1-L15). The current repository
  registers no Claude hooks, so it does not bite today; it will when one is
  added. Note that OLD's own path holds a space and a curly apostrophe.
- The harness facts of case four (how messages, pauses and resumes behave
  between nested agents,
  OLD:docs/superpowers/plans/2026-10-03-case-four.md:L293-L304), relevant to
  `docs/questions/agents-and-skills.md`. Measured on Claude Code 2.1.288
  (OLD:docs/superpowers/plans/2026-10-03-case-four-work/README.md:L87-L96).
- The sweep tool as a validation pattern (below). Nothing in the current
  repository records it.

## Bearing on the four open questions

- **Fit execution.** Nothing.
- **Learned state.** Nothing.
- **SQL representation.**
  - Case three's sketch writes SQL as plain strings, every identifier through
    one `quote_identifier`, which leaves a plain ASCII non-reserved name bare
    and double-quotes the rest, doubling inner quotes
    (OLD:docs/superpowers/plans/2026-10-03-case-three.md:L262-L320). No
    sqlglot.
  - Its planted bug shows the cost of a hand-kept reserved-word list. DuckDB
    2.0.0 gives the list itself: `duckdb_keywords()` has 75 reserved words,
    `limit`, `from`, `with`, `cast`, `using`, `summarize` and `pivot_wider`
    among them (checked today with the current repository's DuckDB 2.0.0).
    Quoting every identifier always avoids the list altogether (inference).
  - The sketch's feature names follow `PolynomialFeatures` with
    `include_bias=False`: `x^2`, `x y`, quoted as aliases
    (OLD:docs/superpowers/plans/2026-10-03-case-three.md:L460-L463).
- **Validation.**
  - `tools/sweep.py`: one function checked against `decimal` at 50 significant
    digits, error in ulp of the result, a bound per function, inputs in numbered
    chunks sampled from a generator seeded with `"NAME/k"` so each chunk's line
    is reproducible, lines appended in order to `validation/sweeps/NAME.txt` and
    committed
    (OLD:docs/superpowers/plans/2026-10-03-case-four-work/sweep/tools/sweep.py:L1-L17,
    L80-L102). It fits the current overview's 3.8 (exact reference, results
    committed and diffed). Measured: `log1p` max 0.51 ulp over 120 chunks of 1.2
    million points; softplus and log-sigmoid at most 1.49 ulp
    (OLD:docs/superpowers/plans/2026-10-03-case-four.md:L56-L60).
  - A second reference, `mpmath` at 50 digits, gave the AS 241 quantile a worst
    relative error of 6.30e-16 over 5,207 points
    (OLD:docs/superpowers/plans/2026-10-03-case-four-work/exact_check.py:L1-L21;
    results/plant-check.out).
  - `statistics.NormalDist.inv_cdf` agreed with OLD's AS 241 on all 699,424
    points (results/plant-check.out), because it is AS 241 too; the sketch's own
    tests compare against it at `rel=1e-12`
    (OLD:docs/superpowers/plans/2026-10-03-case-four-work/ladder/stats/test_normal.py:L13-L15).
    A reference sharing the algorithm under test proves nothing about the
    algorithm (inference).
  - DuckDB has no inverse normal and no `erf` (OLD's claim in
    OLD:docs/superpowers/plans/2026-10-03-case-four-work/ladder/stats/normal.py:L3,
    confirmed today on DuckDB 2.0.0: no such function in `duckdb_functions()`).
    A probit model or a normal quantile in SQL needs its own approximation.
  - NaN policy differs between sketches: `normal_quantile` and `probit` refuse
    NaN (normal.py:L46-L55; ladder/stats/links.py:L10-L25), softplus passes it
    through "as in `math`"
    (OLD:docs/superpowers/plans/2026-10-03-case-four-work/logexp/docs/superpowers/plans/2026-10-03-logexp.md:L45-L46).
- **scikit-learn API.** Only the feature names above, and the probit link's clip
  at machine epsilon copied from statsmodels' `Probit`
  (OLD:docs/superpowers/plans/2026-10-03-case-four-work/ladder/docs/superpowers/plans/2026-10-03-probit-link.md:L33-L35).

## New against the baseline

- An attempt with no library design at all: a foundation spec and four agent
  rehearsals, nothing else.
- The foundation spec the current repository adopted comes from here, with its
  21 approved rows and three decided questions.
- A deterministic, chunked ulp sweep against a 50-digit `decimal` reference,
  results committed as text.
- `NormalDist.inv_cdf` is AS 241, so it is no independent reference for AS 241.
- DuckDB 2.0.0 has no inverse normal and no `erf`; it does list its reserved
  words in `duckdb_keywords()`.
- Measured harness behaviour of nested agents (message timing, resumes, pauses).

## Contradicts the baseline

- "Every attempt used sqlglot": this one's only SQL (a sketch) is plain
  strings with a quoting helper; a qualification, since it is no library.
- "No attempt handled NaN": the sketches handle it explicitly in Python
  (refuse or pass through), though never in DuckDB; a qualification.

## Confirms the baseline

- Process outgrew the product: 316 commits, a 3,174-line rehearsal plan, no
  library code.
- Hand-typed numbers drift: case four's plan is assembled by a script from
  parts and checked by scripts so that its embedded values match
  (OLD:docs/superpowers/plans/2026-10-03-case-four-work/README.md:L8-L39).
- A deterministic checker beats agent review: `widthcheck.awk` and
  `assemble.py` refuse what a reviewer missed (five overlong Log lines,
  OLD:docs/superpowers/plans/2026-10-03-case-four.md:L265-L267).
- Exact references with measured bounds, as the validation finding says; here
  enforced per chunk, but only for sketch functions.

## Worth keeping

- The sweep tool's design for `validation/`: seeded chunks, exact `decimal`
  reference, ulp error, a stated bound, committed text lines.
- The rule that a reference must not share the algorithm under test
  (`NormalDist` and AS 241).
- Reading the reserved-word list from `duckdb_keywords()`, or quoting every
  identifier, rather than keeping a list by hand.
- The fact that DuckDB lacks `erf` and an inverse normal, for any probit or
  normal-quantile step.
- The settings-quoting rule for shell-form Claude hooks, if hooks return.
- The harness facts, for `docs/questions/agents-and-skills.md`.

## Files covered

Root:

- [x] `CLAUDE.md`: the agent rules (instructions, bugs, records, subagents,
  commits, writing).
- [x] `pyproject.toml`: an environment for the hook tests, not a package.
- [x] `commitlint.config.mjs`: diffed against the current file; same rules,
  engine scopes.
- [x] `.gitignore`: seven lines, `.superpowers/` among them.

`rehearsal/`:

- [x] `rehearsal/slug.py`: case one's `slugify` and `unique_slug`.
- [~] `rehearsal/test_slug.py`: its seven tests, by name.

`tests/`:

- [~] `tests/hooks/test_commit_msg.py`: commit-msg hook and commitlint, 17
  functions.
- [~] `tests/hooks/test_record_names.py`: the `records/` file-name hook, 14.
- [~] `tests/hooks/test_session_start.py`: the web-session author step, 11.
- [~] `tests/hooks/test_settings_hooks.py`: quoting in shell-form hooks, 3.
- [~] `tests/hooks/test_superpowers_session_start.py`: the copied superpowers
  session hook, 3.
- [ ] `tests/hooks/__pycache__/` (6 `.pyc` files): compiled caches, not read.

`docs/superpowers/specs/`:

- [x] `2026-10-01-foundation-design.md`: the foundation spec, read by section
  (§1-§3, §10, §13-§18 in full, the rest by heading against the current spec).

`docs/superpowers/plans/`:

- [x] `2026-10-01-foundation-closing.md`: ledger, the 21 approved rows,
  amendments, the plan's items.
- [~] `2026-10-01-foundation.md`: header, how it runs, the 36 rulings; tasks
  by heading.
- [x] `2026-10-02-case-one.md`: sections 1-3 read; the brief skimmed.
- [~] `2026-10-02-case-two.md`: header, purpose; the rest by heading.
- [x] `2026-10-03-case-three.md`: purpose, plant, cover plan; the rest by
  heading.
- [~] `2026-10-03-case-four.md`: header, For Tomas, purpose; the rest by
  heading.

`docs/superpowers/plans/2026-10-03-case-four-work/`:

- [x] `README.md`: how the plan is built and checked.
- [~] `assemble.py`: builds the plan from its parts.
- [~] `briefs/controller-logexp.txt`: fixed brief.
- [~] `briefs/controller-probit-link.txt`: fixed brief.
- [~] `briefs/lead-functions.own`: a lead's own text.
- [~] `briefs/lead-functions.txt`: nested brief.
- [~] `briefs/lead-numerics.own`: the top lead's own text (read further).
- [~] `briefs/lead-numerics.txt`: the whole nested prompt.
- [~] `briefs/lead-probit.own`: a lead's own text.
- [~] `briefs/lead-probit.txt`: nested brief.
- [~] `briefs/nest.py`: nests the briefs.
- [~] `briefs/sweeper-log1p.txt`: fixed brief.
- [~] `briefs/sweeper-sqrt-above.txt`: fixed brief.
- [~] `briefs/sweeper-sqrt-below.txt`: fixed brief.
- [~] `briefs/writer-stats-notes.txt`: fixed brief.
- [~] `case-four-lib.sh`: the orchestrator's shell functions.
- [~] `checked.txt`: the plan's Checked paragraph.
- [x] `exact_check.py`: AS 241 against `mpmath` at 50 digits.
- [~] `ladder/docs/superpowers/plans/2026-10-03-probit-link.md`: cover plan,
  header and constraints read.
- [x] `ladder/docs/superpowers/specs/2026-10-03-stats-notes.md`: the writer's
  spec.
- [~] `ladder/stats/as241.toml`: the AS 241 coefficients, header read.
- [x] `ladder/stats/links.py`: reference probit link.
- [x] `ladder/stats/normal.py`: AS 241 normal quantile, far tail shut.
- [x] `ladder/stats/test_normal.py`: tests against `NormalDist`.
- [~] `logexp/docs/superpowers/plans/2026-10-03-logexp.md`: cover plan, header,
  constraints, formulas.
- [~] `plan-part1.md`: source of the plan, by heading.
- [~] `plan-part2.md`: source of the plan, by heading.
- [~] `plan-part3.md`: source of the plan, by heading.
- [~] `plan-part4.md`: source of the plan, by heading.
- [~] `plant_check.py`: section 3's checks.
- [~] `reflow.py`: rewraps prose at 80.
- [~] `reflow_para.py`: rewraps one paragraph.
- [~] `results/final-pass.out`: dry run output, tail.
- [~] `results/final-review.out`: dry review output, tail.
- [~] `results/holds-trial.out`: git holds trial, head.
- [~] `results/log1p-120-chunks-seconds.txt`: timings.
- [~] `results/log1p-120-chunks.txt`: sweep lines.
- [~] `results/log_sigmoid-24-chunks.txt`: sweep lines.
- [~] `results/one-chunk-each-six-at-once.txt`: timings, read whole.
- [~] `results/plant-check.out`: AS 241 against `NormalDist` and `mpmath`.
- [~] `results/softplus-24-chunks.txt`: sweep lines.
- [~] `scripts/final_pass.zsh`: dry run script.
- [~] `scripts/final_review.zsh`: dry review script.
- [~] `scripts/holds_trial.zsh`: git holds trial.
- [~] `scripts/plan_blocks.zsh`: extracts the plan's shell blocks.
- [~] `scripts/plant_check.sh`: runs the plant checks.
- [~] `scripts/standin.sh`: stand-in agent commits.
- [~] `scripts/timing.sh`: sweep timings.
- [~] `scripts/verify_log1p.sh`: full `log1p` sweep.
- [x] `sweep/tools/sweep.py`: the sweep tool.
- [~] `trials/harness/events.py`: transcript printer.
- [~] `trials/harness/ids.txt`: trial agent ids.
- [~] `trials/harness/logs.sh`: prints trial logs.
- [~] `trials/harness/planner.log`: one line.
- [~] `trials/harness/t1/quick.log`: one line.
- [~] `trials/harness/t1/steps.log`: step timings around a pause.
- [~] `trials/harness/t2/brief-child.txt`: trial brief.
- [~] `trials/harness/t2/child.log`: step timings.
- [~] `trials/harness/t2/parent.log`: what reached the parent.
- [~] `trials/harness/t3/brief-1.txt`: trial brief.
- [~] `trials/harness/t3/brief-2.txt`: trial brief.
- [~] `trials/harness/t3/brief-3.txt`: trial brief.
- [~] `trials/harness/t3/brief-4.txt`: trial brief.
- [~] `trials/harness/t3/rung-1.log`: resume line.
- [~] `trials/harness/t3/rung-2.log`: resume line.
- [~] `trials/harness/t3/rung-3.log`: resume line.
- [~] `trials/harness/t3/rung-4.log`: resume line, report sent to `main`.
- [~] `trials/harness/t5/brief-leaf.txt`: trial brief.
- [~] `trials/harness/t5/leaf.log`: step timings.
- [~] `trials/harness/t5/mid.log`: a pause passed through a rung.
- [~] `trials/plant/as241.py`: AS 241 with string coefficients.
- [~] `trials/plant/swaps.py`: trying digit swaps.
- [~] `trials/plant/tailswaps.py`: trying tail swaps.
- [~] `widthcheck.awk`: flags prose over 80 columns.
