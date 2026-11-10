# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-10 · Branch: `main` · Last commit:
`4afa5a7 docs: update the handoff` · Checks:
passing (`just test` on `main` after the datasets merge)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

None.

## Next up

- The issues the 2026-11-10 decisions filed, all ready-for-agent: #46
  (generators on many threads: needs a parallel, ordered, lazy row source;
  measurements in the issue), #47 (regression clips `n_informative` with a
  warning), #48 (`ordered=True` on the generators), #49 (learn nested
  aggregates; an ADR amending 0036/0044), #50 (key a database table by its
  storage block ids), #51 (test LightGBM), #52 (pos_label type hint), #53
  (UCI citations and DOIs), #31 (opt-in `lookup="hash"` with a warning), #27
  (opt-in `approx=True` median and a house-form out-of-memory error).
- Choose the next 3.3 area: more metrics (confusion matrix, report, curves,
  fbeta), or a fetcher of real datasets (ADR 0006: an explicit call).
- The target encoder's learn after #41 is mostly Python `Fraction` arithmetic
  in `_encodings`/`_totals`: file an issue if it matters.

## Dead ends and traps

- Timing a generator by summing two of its columns measures only those two:
  DuckDB drops the unread ones. Sum every column. `range()` and a `UNION ALL`
  of ranges run on one thread while insertion order is kept (#46). DuckDB
  2.0's relations have no `fetchone()`. (2026-11-10)
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
- LightGBM's macOS wheel needs `brew install libomp` (installed here
  2026-11-10); uv cannot provide it. Nothing tests LightGBM yet (#51).
  (2026-11-07)
- The git stash is shared by all worktrees: never a bare `git stash`.
  (2026-11-06)

## Just finished

- Every pending ruling decided with Tomas (2026-11-10): outcomes in the
  ledgers' "Decisions" sections and as comments on #45, #33, #31, #27, #22;
  new issues #46-#53. #22 kept as an idea in
  `docs/questions/onehot-list-column.md`. The rule behind them is ADR 0046
  (sqlearn warns, the user chooses), also in CLAUDE.md's rules.
- The datasets area, merged into `main` and pushed, #45 closed: `sq.datasets`
  with `iris`, `wine`, `breast_cancer` and `blobs`, `regression`,
  `classification`, `customers`; ADR 0045, `docs/guide/datasets.md`.
  (2026-11-10)
