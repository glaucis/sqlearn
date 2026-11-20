# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-20 · Branch: `main` · Last commit: `717a286` Merge branch
'feature-selection': feature selection (#65) · Checks: passing (`just test`
on the merged `main`: 2802 passed, 24 skipped; `just verify` on the branch
after the final review's fixes: 2813 passed, 24 skipped, no validation fail)
· Not pushed
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- The #46 benchmark (`docs/benchmarks/generators-on-many-threads.md`) was not
  on a quiet machine (load average about 4 to about 35) and can be rerun on
  request. (since 2026-11-18)

## Next up

- The next 3.3 area, not chosen yet. No dataset fetcher (ADR 0053).

## Dead ends and traps

- A step's first positional argument is its columns: `sq.select.percentile(50)`
  is refused with a `Fix:` (write `percentile=50`), but other groups still
  read a positional number as `cols` and fail later. The errors are in
  `sq.errors` (`sq.errors.StepError`), not `sq`. BSD `sed -i` needs an
  extension argument, so use Edit for in-place changes. (2026-11-20)
- DuckDB 2.0 has no `log1p`: use Kahan's form, `_log1p` in
  `src/sqlearn/metrics/regression.py`. scikit-learn's D² pinball baseline is
  `_weighted_percentile(average=True)`, not any DuckDB quantile
  (`quantile_cont` and `quantile_disc` both differ). The full validation
  takes about 47 minutes under load; one runner can run alone through
  `validation.__main__.main([module], ROOT)`. The docs tagger's uncommitted
  frontmatter edits on `main` can block a merge: save that file's diff as a
  patch, `git checkout` it, merge, `git apply` the patch. (2026-11-19)
- `meta_sqlearn` (ADR 0052): one transaction writes one attached database,
  so it is written through a cursor. `con.execute` on the user's connection
  discards their unfinished result, so only bind there. A transaction may
  not see a ticket table made after it read that database. Database names
  match case-insensitively in `ATTACH` and three-part names but not in
  `duckdb_databases()` string comparisons. A two-part name is ambiguous
  with a same-named schema. (2026-11-18)
- The level planner (`_calls` in `_compose.py`) reads SQL text: a name in
  `duckdb_functions()` of type aggregate is an aggregate, but DuckDB's scalar
  `filter` (`list_filter`) is not, a subquery's aggregates are its own, and
  macro aggregates (`geomean`) are not listed at all. Nested values against
  numpy carry the inner rounding: allow 4 ULPs (`NESTED_ULPS`). (2026-11-17)
- DuckDB rounds halves away from zero (`round(-2.5)` is -3), numpy to even:
  compare with `floor`. A pandas frame hands NaN to DuckDB as NULL; insert
  into a DuckDB table to test NaN. (2026-11-17)
- Projecting `rel.columns` back by name (`ColumnExpression(c)`) loses a
  column differing only by case (`a`, `A`): DuckDB resolves `A` to `a`. Use
  `StarExpression()` (fixed in the folds' `rows`, `f405ef5`). Reading the
  source twice (once for features, once for a target) misaligns rows on a
  shuffled or sampled source: read it once (#59). (2026-11-15)
- `_drop_later` tables are dropped at the next `read`, not on garbage
  collection: a test checking a drop reads once more first. A `just verify`
  rerun can flip a large-set result to "anomaly" (DuckDB's reference drifting
  by thread order, ADR 0016): discard it as a ULP diff. (2026-11-15)
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
- Benchmarks share the machine with other jobs: record `uptime` before and
  after each count. (2026-11-12)
- Timing a query by summing two columns measures only those two: DuckDB
  drops the unread ones. DuckDB 2.0's relations have no `fetchone()`.
  (2026-11-10)
- `while pgrep -f name` matches itself and never ends: wait on a PID. A
  `VALUES ('a'::ENUM(...))`
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
- Wall-clock tests: an absolute limit fails under heavy load. Compare two
  sizes in the same test, as
  `test_a_cold_learn_of_many_staged_aggregates_is_fast`. Never pipe
  `just test` through `tail` before `&&`. (2026-11-10)
- DuckDB 2.0: NaN sorts greatest; a staged result read with `any_value` breaks
  inside another aggregate; chained quantile stages spill only with the SQL of
  `b633816`; `range()` is read on one thread. (2026-11-08)
- The git stash is shared by all worktrees: never a bare `git stash`.
  (2026-11-06)

## Just finished

- Feature selection (#65, ADRs 0055 and 0056): `sq.select.variance`, `best`
  and `percentile` (and `sq.select(..., method=)`) with the `f_classif`,
  `f_regression` and `chi2` scores; a target step that does not cross-fit
  (0055); a search over `k`, `percentile` or `threshold` learns each fold once
  (0056). Spec `docs/specs/library-feature-selection.md`, plan
  `docs/plans/2026-11-19-library-feature-selection.md`, guide page
  `docs/guide/selecting-features.md`. Found on the way: `sq.load` refused a
  saved pipeline ending in a feature selector that drops a column (fixed: a
  whole-row step's columns are now checked against its values at load);
  sqlearn gives the exact score where scikit-learn's rounding departs (spec
  4.4); `k=True` is refused (spec 4.2); a 12-byte crafted value could hang
  `sq.load` (learned values must now be plain numbers). Merged in `717a286`,
  not pushed; minor follow-ups are on #65. (2026-11-20)
- #63's deferred minors, merged in `62eecbd` (not pushed). Found on the
  way: a scored column named `__sqlearn_stage_...` silently replaced a D² or
  ranking score's own (now refused). The deviances keep 4 or 5 digits far
  from zero, not the 6 #63 said. `msle` and the deviances now run on
  `offset` with measured bounds. (2026-11-19)
- Regression metrics (#63, ADR 0054): `mse`, `msle`, `rmsle`,
  `median_absolute_error`, `max_error`, `mape`, `explained_variance`, the
  Poisson, gamma and Tweedie deviances (`power=`), `pinball_loss`
  (`alpha=`) and the D² scores. `Metric` gained `_outside` (range
  refusals), `_predict_stages` (window projections) and `_finish`. Spec
  `docs/specs/library-regression-metrics.md` (section 6 lists the
  departures), plan `docs/plans/2026-11-19-library-regression-metrics.md`.
  Merged in `88e12ce` and pushed; deferred minors are on #63. (2026-11-19)
