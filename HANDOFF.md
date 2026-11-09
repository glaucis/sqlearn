# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-09 · Branch: `main` · Last commit: `4b9bf1f docs: record the
merged metrics build in the handoff` · Checks: passing
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- Check the metrics build's rulings (11, with cost-if-wrong) and its 4
  deferred minors in
  `.superpowers/sdd/2026-11-09-library-metrics/progress.md`; file the minors
  you want as issues. (since 2026-11-09)
- Check the model-selection build's rulings (listed in #33's summary, all 22
  in `.superpowers/sdd/2026-11-07-library-model-selection/progress.md`),
  chiefly R8 (no LightGBM test), R11/R22 (a passed connection's DuckDB counts
  as at most half the budget; a warning when its limit is higher, which
  DuckDB's default is), R13 (`keep_prepared` does not see an in-place UPDATE
  keeping the row count), R21 (one-at-a-time searches keep only the current
  preparation's fold tables). (since 2026-11-08)
- File the final review's "can stay" minors as issues? They are in the same
  ledger, triaged. Recommendation: file the few that can bite (later batches
  cast to the first batch's types; ENUM/collated VARCHAR not cast to
  categories; Optuna trial left RUNNING on a failing fold). (since 2026-11-08)
- #22 (OneHot as a list column): decide from the numbers in
  `docs/benchmarks/onehot-second-run.md`. (since 2026-11-06)

## Next up

- Ready for an agent: #28 compensated two-pass variance, then #27 (the
  median's reach); #32 (impute's filled copies typed INTEGER); #31 (the
  encoders' linear category lookup); #35 (accuracy's label checks).
- Choose the next 3.3 area: datasets, or more metrics (confusion matrix,
  report, curves, fbeta).

## Dead ends and traps

- DuckDB sums doubles on several threads in the order they finish, so a
  learned mean or standard deviation (and any score) can differ by one ULP
  between runs on a busy machine; compare runs within a bound, never byte
  for byte (ADR 0043). Median, quantiles, min, max and counts are exact.
  (2026-11-09)
- `just test` does not run the Sphinx doctests, and an incremental docs build
  reuses stale generated pages: check docs with
  `rm -rf docs/reference/generated docs/_build && just build-docs`. (2026-11-06)
- `just verify` also runs `just check-docstrings` and mypy, which `just check`
  does not: run them before calling a branch done. (2026-11-07)
- A subagent that has handed back can still be running a background step
  while `ListAgents` shows it completed; check the agent panel and stop it
  with `TaskStop`. A subagent cut off by a network drop leaves its work
  uncommitted in the worktree: resume it with `SendMessage`. (2026-11-08)
- Wall-clock tests must warm up first, and set a limit between the normal
  time under load and the regression's, not just above the normal time.
  Never pipe `just test` through `tail` before `&&`: the pipe hides its
  failure. (2026-11-07)
- DuckDB 2.0: NaN sorts greatest, so `max` over a column with NaN is NaN
  (every aggregate filters missing values); a staged result read with
  `any_value` breaks inside another aggregate (plain column there); chained
  quantile stages spill only with the SQL shape of `b633816`. Relations have
  no `fetchone()`; while an Arrow reader is open, the connection refuses other
  statements and a cursor cannot see TEMP tables. (2026-11-08)
- LightGBM's macOS wheel needs `brew install libomp`; it is not installed, so
  nothing tests LightGBM. (2026-11-07)
- The git stash is shared by all worktrees: never a bare `git stash`. The
  CodeGraph index covers the main checkout, not the worktrees. (2026-11-06)

## Just finished

- #36: a seeded search is repeatable within rounding (ADR 0043): same
  settings and best, scores within 1 ULP; scores within 16 ULPs of the best
  tie, the first tried winning. (2026-11-09)
- Metrics area (#34): precision, recall and f1 with scikit-learn's `average`,
  `pos_label` and `zero_division`, counted per class in DuckDB and exact to the
  double; spec `docs/specs/library-metrics.md`, plan
  `docs/plans/2026-11-09-library-metrics.md`, ADR 0042; 6 tasks, final review,
  one fix pass; fast-forwarded into `main` and pushed; #34 closed with its
  summary. (2026-11-09)
- Model selection (#33, closed with a summary; #21 and #25 closed): spec
  `docs/specs/library-model-selection.md`, plan
  `docs/plans/2026-11-07-library-model-selection.md`, ADRs 0039–0041; 15
  reviewed tasks, final review and fix wave; fast-forwarded into `main` at
  `2fc0059` and pushed. (2026-11-09)
