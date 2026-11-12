# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-12 · Branch: `main` · Last commit: `5d89737 docs: update the
handoff` · Checks: passing (`just test` on the merge `a61301a`:
2128 passed, 24 skipped; `just verify` on `a8558e3`: 2138 passed)
Verify with: `just verify`

## In progress

None.

## Waiting on the user

None.

## Next up

- Re-measure the category lookup on an idle machine (check `uptime` first;
  the load was about 30 on 2026-11-11): both encoders at 15,000, 20,000 and
  100,000 categories, one count per process, then lower `WARN_ABOVE` if the
  ordinal crossover is below 30,000 and give the target encoder a warning if
  the hash wins for it (R7, R8 on #31).
- #46 (generators on many threads: needs a parallel, ordered, lazy row
  source; measurements in the issue) and #49 (learn nested aggregates; an ADR
  amending 0036/0044), both ready-for-agent and needing a design first.
- The next 3.3 area: more metrics (confusion matrix, report, curves, fbeta),
  or a fetcher of real datasets (ADR 0006: an explicit call).
- The target encoder's learn after #41 is mostly Python `Fraction` arithmetic
  in `_encodings`/`_totals`: file an issue if it matters.
- `just check` passed with a function defined twice in `_pipeline.py`
  (ruff selects `F`, yet F811 stayed quiet): find out why.

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

- #55: the user saves the trained model; `sq.load` imports nothing and builds
  only steps, models, nested estimators and fold schemes; `allow=`,
  `trust_model=`, `model=` and pickle are gone; `pipe.model_` and
  `pipe.use_model` added; guide rewritten. Spec
  `docs/specs/library-saving-the-model.md`, ADR 0048. Merged in `a61301a`,
  pushed; #55 closed with the deferred findings listed on it.
  (2026-11-12)
