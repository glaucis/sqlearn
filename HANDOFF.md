# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-11 · Branch: `main` · Last commit:
`ead6712 Merge branch 'fix-batch-3'` · Checks: passing (`just test` on merged
`main`: 1826 passed, 24 skipped; `just verify` on `fix-batch-3`)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- The GitHub steps for the saving area are pending with the controller:
  close #20 and part 1 of #24 (retitle #24 "Export a trained pipeline as
  standalone code"), open the summary issue (replace `#TBD` in `CLAUDE.md`),
  and file an issue for model formats other than pickle. (since 2026-11-11)

## Next up

- Re-measure the category lookup on an idle machine (check `uptime` first;
  the load was about 30 on 2026-11-11): both encoders at 15,000, 20,000 and
  100,000 categories, one count per process, then lower `WARN_ABOVE` if the
  ordinal crossover is below 30,000 and give the target encoder a warning if
  the hash wins for it (R7, R8 on #31).
- #46 (generators on many threads: needs a parallel, ordered, lazy row
  source; measurements in the issue) and #49 (learn nested aggregates; an ADR
  amending 0036/0044), both ready-for-agent and needing a design first.
- The next 3.3 area: more metrics (confusion matrix, report,
  curves, fbeta), or a fetcher of real datasets (ADR 0006: an explicit call).
- The target encoder's learn after #41 is mostly Python `Fraction` arithmetic
  in `_encodings`/`_totals`: file an issue if it matters.

## Dead ends and traps

- After a merge that adds a dependency, the pre-commit hook fails on `main`
  until its environment is synced: run `uv sync` (or `just pre-commit` once),
  then commit. A step's `inputs` sees only column names and types, never the
  source table, so nothing per table (a collation) can be checked there.
  (2026-11-11)
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
- The git stash is shared by all worktrees: never a bare `git stash`.
  (2026-11-06)

## Just finished

- The saving area (the fifth 3.3 area): `sq.save` and `sq.load`, one JSON
  file of recipe, learned values and the data's fingerprint, the trained
  model by pickle only on request; spec `docs/specs/library-saving.md`, plan
  `docs/plans/2026-11-11-library-saving.md`, ADR 0047, guide
  `docs/guide/saving-a-pipeline.md`, on branch `library-saving`. (2026-11-11)
- Fix batch 3's rulings confirmed by Tomas, each recorded on its issue: R6
  (#50; its cross-process warning goes with saving learned state, noted on
  #20), R7, R8 and R10 (#31). (2026-11-11)
- Fix batch 3, merged into `main` (`ead6712`) and pushed; plan
  `docs/plans/2026-11-10-fix-batch-3.md`. Closed: #47 (regression clips
  `n_informative` with a warning), #48 (`ordered=True`), #50 (a table edited in
  place is prepared again, with a warning), #51 (LightGBM tested), #52
  (pos_label type hint), #53 (UCI citations), #31 (opt-in `lookup="hash"`),
  #27 (opt-in `approx=True` median and a house-form out-of-memory error).
  (2026-11-11)
- Polars as a second execution engine kept as an idea: #54,
  `docs/questions/multi-engine-support.md` (`9258e7b`). (2026-11-11)
