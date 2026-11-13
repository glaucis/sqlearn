# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-13 · Branch: `library-more-metrics` (not yet merged) ·
Checks: passing (`just verify`: 2278 passed, 24 skipped)
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
- Merge `library-more-metrics` (#58) into `main`.

## Dead ends and traps

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

- More metrics (#58), on branch `library-more-metrics`, not yet merged: `fbeta`,
  `average_precision`, `confusion_matrix`, `classification_report`, `roc_curve`
  and `precision_recall_curve` (the tables and curves are relations, ADR 0049),
  the search refusing a table or unready metric, and the guide
  `docs/guide/evaluating-a-model.md`. Spec `docs/specs/library-more-metrics.md`,
  plan `docs/plans/2026-11-13-library-more-metrics.md`. The closing commit is
  `aea01de`, with a fix round after it (the guide scores held-out rows).
  `just verify`: 2278 passed, 24 skipped on each interpreter.
- The target encoder's learn: `derive` made every row exact again for each
  of the six encodings; it now sums once and takes a fold's complement as
  the whole less the fold, the same encodings to the bit. Learn at 30,000
  categories 6.56 s to 3.58 s (`docs/benchmarks/category-lookup.md`). What
  remains is the scikit-learn formula in `Fraction`, once per category and
  key.
- Ruff's F811 skipped every `_name` (its default `dummy-variable-rgx` takes
  them for throwaways), which is how `_no_fit` lived twice in `_pipeline.py`
  (8841cae). `dummy-variable-rgx` is now `^_+$`, pinned by a test in
  `tests/test_environment.py`; the repo is clean under it.
- The category lookup re-measured (R7, R8 on #31): for both encoders the hash
  applies faster from 20,000 categories, so `WARN_ABOVE` is 20,000 and the
  target encoder warns too. The machine was never fully idle (load 4 to 34;
  other projects' jobs): the 15,000 and 20,000 rows were measured twice and
  agree. Tables in `docs/benchmarks/category-lookup.md`.
