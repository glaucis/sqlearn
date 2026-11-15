# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-15 · Branch: `main` · Last commit: the merge of
`holdout-rows` (#60) · Checks: passing (`just verify` on the branch: 2321
passed, 24 skipped on each interpreter)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

None.

## Next up

- #46 (generators on many threads: needs a parallel, ordered, lazy row
  source; measurements in the issue) and #49 (learn nested aggregates; an ADR
  amending 0036/0044), both ready-for-agent and needing a design first.
- The next 3.3 area, not chosen yet: a fetcher of real datasets (ADR 0006:
  an explicit call), or more scores (balanced accuracy, MCC, Brier).

## Dead ends and traps

- DuckDB cannot name a column `""`, and `.df()`/`.fetchnumpy()` rename the
  second of two names differing only by case (`a`, `A_1`); a bare `1.0` in
  SQL is DECIMAL, write `1.0::DOUBLE`. commitlint here takes no scope but
  `hooks`, `site`, `deps`, and a header of 72 characters at most.
  (2026-11-13)
- When the network drops mid-build, resume the same subagent (SendMessage
  to its id) to check and finish; killing a stray test run is not allowed
  here, so wait on its PID before a new `just verify`. (2026-11-14)

- DuckDB hands a `TIMESTAMP WITH TIME ZONE` to Python only through pytz,
  which is not installed. sqlearn's learned values come through
  `_fetch_learned` (UTC); a test reading zoned output fetches it as text
  (`CAST(COLUMNS(*) AS VARCHAR)`). `just fmt` can pick up frontmatter edits
  the docs tagger made to files you did not touch: leave them out of the
  commit. (2026-11-11)
- `gh-board status` in a loop can fail for one issue now and then (#36 did):
  rerun it for that issue, then `GH_BOARD=glaucis/6 gh-board audit`.
  (2026-11-11)
- `sq.load` security: per-task reviews each passed, yet the final review found
  two routes from a crafted file to `KeptFolds` (which creates a DuckDB file).
  Probe every tag (`object`, `estimator`, nested estimator, `aggregate`,
  learned part, `trained`) end to end after any change to `_saving`. The
  class lookup must stay static (#55): `getattr`, `hasattr`, `isinstance`,
  `in` or `==` on anything a file reaches can run its code (a lazy module
  `__getattr__`, a `__class__` property, a metaclass `__eq__`); read through
  the type descriptors and compare by `is`. Saving tests print
  "nanobind: leaked" at exit (DuckDB); the exit code stays 0. (2026-11-11)
- After a merge that adds a dependency, the pre-commit hook fails on `main`
  until its environment is synced: run `uv sync` (or `just pre-commit` once),
  then commit. A step's `inputs` sees only column names and types, never the
  source table, so nothing per table (a collation) can be checked there.
  (2026-11-11)
- Benchmarks here share the machine with other projects' jobs (`ps -Ao
  pcpu,comm -r`): record `uptime` before and after each count and measure
  the counts near a crossing twice. (2026-11-12)
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

- `Holdout.rows(rel, k=0, *, held)` (#60), merged in `ed06a24`: a holdout's
  held-out or training rows, as `KFold.rows`; any `k` but 0 is refused. The
  evaluating guide now holds out a fifth with `sq.folds.holdout`. Design on the
  issue, plan `docs/plans/2026-11-15-holdout-rows.md`.
- `Pipeline.predict_proba` (#59), merged in `8288e35`: the target (when
  the data holds it) beside one `__sqlearn_proba_<i>` column per class in
  input order, `Pipeline.classes_`, `Search.predict_proba`, and the
  evaluating guide using them. ADR 0050, spec
  `docs/specs/pipeline-predict-proba.md`, plan
  `docs/plans/2026-11-15-pipeline-predict-proba.md`. The final review found
  the target read twice (misaligned on a shuffled or sampled source); fixed
  in `f3eb279` by reading the data once into a temporary table. Also fixed
  `main`'s failing `check-docstrings` (`b5cd3e1`).
