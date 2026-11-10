# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-10 · Branch: `library-datasets` (worktree
`.worktrees/library-datasets`, not merged) · Checks: passing (`just verify` on
the branch)
Verify with: `just verify`

## In progress

- The datasets area (#45, plan `docs/plans/2026-11-10-library-datasets.md`):
  done and verified on its branch, waiting for the merge (see below).

## Waiting on the user

- Merge `library-datasets` into `main`, and check its rulings, listed with
  their costs in #45 (ledger
  `.superpowers/sdd/2026-11-10-library-datasets/progress.md`, in the
  worktree). Chiefly: the generators run on one thread (R3); an explicit
  `n_informative > n_features` is refused where scikit-learn clips (R7/R16);
  rows keep their order through `preserve_insertion_order`, not an `ORDER BY`
  (R10). (since 2026-11-10)
- [assumed] The UCI URLs in `src/sqlearn/datasets/data/README.md` (iris 53,
  wine 109, breast cancer 17) were written without network: check them online.
  (since 2026-11-10)
- Check fix batch 2's rulings (ledger
  `.superpowers/sdd/2026-11-10-fix-batch-2/progress.md`, in the main
  checkout), each with its cost if wrong:
  - #44 is refused, not learned: a plain aggregate inside a staged one (`std(x
    - mean(x))`, `median(x - mean(x))`) is a house-form error (cost: such
    forms must be rewritten side by side or split across steps);
  - `sq.agg.var`'s validation bound is 2 ULPs, as std's, for thread order
    (cost: a 2-ULP regression of var would pass unseen);
  - impute keeps an ENUM column's type for the constant and the mode fill, and
    refuses a constant outside the declared values; the mode fill gave VARCHAR
    before the batch too (cost: a little more impute code);
  - impute's ENUM types are state set by `inputs` and read by `apply` (cost: an
    `apply` without `inputs` would skip the cast). (since 2026-11-10)
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
    (cost: a 2-ULP regression would pass unseen). (since 2026-11-10)
- #31: keep `list_position` and close, use the MD5 hash above a threshold, or
  allow a join (an ADR); numbers in `docs/benchmarks/category-lookup.md`
  (which now also has the target encoder's learn after #41).
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

- Choose the next 3.3 area: more metrics (confusion matrix, report, curves,
  fbeta), or a fetcher of real datasets (ADR 0006: an explicit call).
- The target encoder's learn after #41 is mostly Python `Fraction`
  arithmetic in `_encodings`/`_totals` (about 5 s at 200k rows before #41);
  file an issue if it matters.

## Dead ends and traps

- A wait loop `while pgrep -f name` (or `until ! pgrep -f name`) matches its
  own command line and never ends: subagents left two such loops running.
  Wait on a PID, or let the harness notify. A `VALUES ('a'::ENUM(...))`
  relation comes out VARCHAR: build an ENUM column by casting over the VALUES.
  (2026-11-10)
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
  Under heavy load (load average 60) an absolute limit fails anyway: a busy
  machine slowed the cold staged learn 8 times. Compare two sizes in the same
  test instead (the median of three of each, alternating; the fastest favours
  the short one), as `test_a_cold_learn_of_many_staged_aggregates_is_fast`
  does. To reproduce load, run 32 busy shell loops beside the test. Never pipe
  `just test` through `tail` before `&&`: the pipe hides its failure.
  (2026-11-10)
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

- The datasets area (#45): `sq.datasets` with `iris`, `wine`,
  `breast_cancer` (bundled, CC BY 4.0) and `blobs`, `regression`,
  `classification`, `customers` (SplitMix64 in SQL, lazy, any size), ADR 0045,
  `docs/guide/datasets.md`; the tuning example uses `customers`. 5 tasks,
  final review, one fix wave. (2026-11-10)
- The cold staged-learn test compares two sizes instead of an absolute 2 s
  (`d8d5daf`): it failed under load, and still fails on the planning
  regression. (2026-11-10)
- Fix batch 2 (plan `docs/plans/2026-11-10-fix-batch-2.md`), merged into `main`
  and pushed, #41-#44 closed: #43 `sq.cols.string()` selects ENUM, one `is_text`
  for selector, hand-over and metrics, impute keeps an ENUM's type (`53dc701`,
  `cc6cfdd`); #44 a plain aggregate inside a staged one is refused in the house
  form (`a066963`, `83fbad9`); #42 `sq.agg.var` in std's two passes, 20 to 1
  ULP, bound 2 (`ce4b967`, `d1ccdb5`); #41 the learn stage reads a whole staged
  value once, target encoder's learn at 10,000 categories 46.8 s to 4.0 s
  (`4a73236`). 4 tasks, final review, one fix wave. (2026-11-10)
- Fix batch (plan `docs/plans/2026-11-09-fix-batch.md`), fast-forwarded into
  `main` and pushed; #28, #32, #35, #37-#40 closed with their commits: #32
  impute's filled copies keep their type (`Step.copies_inputs`); #35 accuracy
  refuses continuous and mixed-kind labels; #37 the metrics refuse infinite,
  list and incomparable labels; #38 ENUM features reach models as categories in
  declared order; #39 a failing fold fails its Optuna trial; #40 streamed
  predictions widen to each batch's type; #28 `sq.agg.std` in two staged passes
  (12 to 1 ULP, about 2.9x the cost, ADR 0044); #31 and #27 measured and handed
  back. 9 tasks, final review, one fix wave. (2026-11-10)
