# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-10 · Branch: `main` (25 ahead of `origin/main`) · Last
commit: `c7b43ec docs: record the fix batch in the handoff` · Checks: passing
(`just verify` on the branch, `just test` on the merged `main`)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- Push `main` (the fix batch, merged locally), then close #28, #32, #35, #37,
  #38, #39, #40 with their commits. Recommended: push now. (since 2026-11-10)
- Check the batch's rulings, each with its cost if wrong (ledger
  `.superpowers/sdd/2026-11-09-fix-batch/progress.md`, in the main checkout):
  - accuracy's label checks use a private flag, not a public `Metric` field
    (cost: one private field on `Metric`);
  - #31: the encoders keep `list_position`; the MD5 perfect hash (sublinear,
    1.7x faster at 10,000 categories, slower below about 2-3k, wrong for
    collated columns) is not adopted (cost: lookups past ~3k categories stay up
    to 1.7x slower);
  - a standard deviation may hold the other staged aggregates
    (`std(x - median(x))`), as ADR 0036 promises (cost: more compositor code);
  - the std's validation bound is 2 ULPs, not 1, for DuckDB's thread order
    (cost: a 2-ULP regression would pass unseen);
  - the ENUM text selector (#43) and `std(x - mean(x))` (#44) stay out of the
    batch (cost: `sq.encode.onehot()` still skips ENUM columns). (since
    2026-11-10)
- #31: keep `list_position` and close, use the MD5 hash above a threshold, or
  allow a join (an ADR); numbers in `docs/benchmarks/category-lookup.md`.
  (since 2026-11-10)
- #27: offer an approximate median beyond the exact one's reach (32/64/128 MB
  learn 8.1M/32.5M/110M rows on one thread, `docs/benchmarks/median-reach.md`),
  and recheck on DuckDB updates? (since 2026-11-10)
- #22 (OneHot as a list column): decide from the numbers in
  `docs/benchmarks/onehot-second-run.md`. (since 2026-11-06)
- The model-selection build's rulings (#33's summary; ledger
  `.superpowers/sdd/2026-11-07-library-model-selection/progress.md`), chiefly
  R8, R11/R22, R13, R21; and the metrics build's 11 rulings
  (`.superpowers/sdd/2026-11-09-library-metrics/progress.md`). Their minors
  that can bite are now #37-#40, fixed in this batch. (since 2026-11-08)

## Next up

- Choose the next 3.3 area: datasets (recommended: the learning site needs
  sample data) or more metrics (confusion matrix, report, curves, fbeta).
- Ready for an agent: #41 (the target encoder's learn crosses every row with
  its staged stats: 46.8 s at 10,000 categories on 1M rows); #42 (`sq.agg.var`
  in two passes, as std); #43 (`sq.cols.string()` skips ENUM, one shared
  definition of text); #44 (`std(x - mean(x))` gives a misleading GROUP BY
  error).

## Dead ends and traps

- DuckDB reports a collated VARCHAR's type as plain `VARCHAR` (the collation
  lives on the expression); a NULL-only column's type is `"NULL"`, quotes
  included. Arrow batches keep only the ENUM values they hold, so an ENUM's
  declared list comes from the relation's type. (2026-11-10)
- A cast error between types DuckDB cannot compare (DATE = INTEGER) is raised
  at execution, not at bind: a `LIMIT 0` probe does not catch it. Catch only
  `ConversionException` and `BinderException`: `OutOfMemoryException` and
  `InterruptException` are `duckdb.Error` too. (2026-11-10)
- `dataclasses.replace` drops `init=False` fields (accuracy's private label
  flag). (2026-11-10)
- `just verify` rewrites `validation/**/*.results.json` and
  `validation/tests.json`; a rerun differs only by thread-order ULPs (ADR
  0043). Discard those diffs unless the validation itself changed. (2026-11-10)
- Benchmarks that build large data in memory can be killed by the machine:
  write the data to Parquet with DuckDB's `COPY` and run each probe in its own
  subprocess. (2026-11-10)
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

- Fix batch (plan `docs/plans/2026-11-09-fix-batch.md`), fast-forwarded into
  `main` at `c7b43ec`, worktree and branch removed: #32 impute's filled copies
  keep their type (`Step.copies_inputs`); #35 accuracy refuses continuous and
  mixed-kind labels; #37 the metrics refuse infinite, list and incomparable
  labels; #38 ENUM features reach models as categories in declared order; #39 a
  failing fold fails its Optuna trial; #40 streamed predictions widen to each
  batch's type; #28 `sq.agg.std` in two staged passes (12 to 1 ULP, about 2.9x
  the cost, ADR 0044); #31 and #27 measured and handed back. 9 tasks, final
  review, one fix wave. (2026-11-10)
