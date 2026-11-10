# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-10 · Branch: `main` (pushed) · Last commit:
`bd3e2af docs: record the datasets area in the handoff and CLAUDE.md` · Checks:
passing (`just verify` on the datasets branch; `just test` on the merged `main`)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- The datasets area's rulings, listed with their costs in #45 (ledger
  `.superpowers/sdd/2026-11-10-library-datasets/progress.md`). Chiefly: the
  generators run on one thread (R3); an explicit `n_informative > n_features`
  is refused where scikit-learn clips (R7/R16); rows keep their order through
  `preserve_insertion_order`, not an `ORDER BY` (R10). (since 2026-11-10)
- [assumed] The UCI URLs in `src/sqlearn/datasets/data/README.md` (iris 53,
  wine 109, breast cancer 17) were written without network: check them online.
  (since 2026-11-10)
- Fix batch 2's rulings (ledger
  `.superpowers/sdd/2026-11-10-fix-batch-2/progress.md`): #44 refused, not
  learned; `sq.agg.var`'s bound 2 ULPs; impute keeps an ENUM's type and refuses
  an undeclared constant; impute's ENUM types are state set by `inputs`.
  (since 2026-11-10)
- The 2026-11-09 fix batch's rulings (ledger
  `.superpowers/sdd/2026-11-09-fix-batch/progress.md`): accuracy's private label
  flag; a std may hold other staged aggregates; std's bound 2 ULPs.
  (since 2026-11-10)
- #31: keep `list_position` and close, use the MD5 hash above a threshold, or
  allow a join (an ADR); numbers in `docs/benchmarks/category-lookup.md`.
  (since 2026-11-10)
- #27: an approximate median beyond the exact one's reach
  (`docs/benchmarks/median-reach.md`)? (since 2026-11-10)
- #22 (OneHot as a list column): decide from
  `docs/benchmarks/onehot-second-run.md`. (since 2026-11-06)
- The model-selection build's rulings (#33; chiefly R8, R11/R22, R13, R21) and
  the metrics build's 11 (#34's ledger). (since 2026-11-08)

## Next up

- Choose the next 3.3 area: more metrics (confusion matrix, report, curves,
  fbeta), or a fetcher of real datasets (ADR 0006: an explicit call).
- The target encoder's learn after #41 is mostly Python `Fraction` arithmetic
  in `_encodings`/`_totals`: file an issue if it matters.

## Dead ends and traps

- A wait loop `while pgrep -f name` matches its own command line and never
  ends; wait on a PID or let the harness notify. A `VALUES ('a'::ENUM(...))`
  relation comes out VARCHAR: cast over the VALUES instead. (2026-11-10)
- DuckDB reports a collated VARCHAR as plain `VARCHAR`; a NULL-only column's
  type is `"NULL"`, quotes included. Arrow batches keep only the ENUM values
  they hold: an ENUM's declared list comes from the relation's type.
  (2026-11-10)
- A cast error between types DuckDB cannot compare is raised at execution, not
  bind. Catch only `ConversionException` and `BinderException`. (2026-11-10)
- `dataclasses.replace` drops `init=False` fields. (2026-11-10)
- `just verify` rewrites `validation/**/*.results.json` and `tests.json`; a
  rerun differs only by thread-order ULPs (ADR 0043): discard those diffs
  unless the validation changed. Commit `tests.json` when tests were added.
  (2026-11-10)
- Large in-memory benchmarks can be killed: write Parquet with `COPY`, one
  probe per subprocess. (2026-11-10)
- DuckDB sums doubles in thread-finish order: means, stds and scores can move
  one ULP between runs; compare within a bound (ADR 0043). (2026-11-09)
- `just test` skips the Sphinx doctests, and an incremental docs build reuses
  stale pages: `rm -rf docs/reference/generated docs/_build && just
  build-docs`. `just verify` also runs mypy and `check-docstrings`.
  (2026-11-07)
- A subagent that has handed back can still run a background step: check the
  agent panel, stop it with `TaskStop`. (2026-11-08)
- Wall-clock tests: an absolute limit fails under heavy load (load average 60
  slowed a learn 8 times). Compare two sizes in the same test (median of three
  each, alternating), as `test_a_cold_learn_of_many_staged_aggregates_is_fast`.
  Reproduce load with 32 busy shell loops. Never pipe `just test` through
  `tail` before `&&`. (2026-11-10)
- DuckDB 2.0: NaN sorts greatest; a staged result read with `any_value` breaks
  inside another aggregate; chained quantile stages spill only with the SQL of
  `b633816`; `range()` is read on one thread. (2026-11-08)
- LightGBM's macOS wheel needs `brew install libomp`; nothing tests LightGBM.
  (2026-11-07)
- The git stash is shared by all worktrees: never a bare `git stash`.
  (2026-11-06)

## Just finished

- The datasets area, merged into `main` and pushed, #45 closed: `sq.datasets`
  with `iris`, `wine`, `breast_cancer` and `blobs`, `regression`,
  `classification`, `customers`; ADR 0045, `docs/guide/datasets.md`.
  (2026-11-10)
- The cold staged-learn test compares two sizes, not an absolute 2 s
  (`d8d5daf`). (2026-11-10)
- Fix batch 2 pushed, #41-#44 closed. (2026-11-10)
