# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-20 · Branch: `main` · Last commit: `b1d1cc4` Merge
branch 'load-and-gram-fixes' · Checks: passing (`just verify` on the
branch at `8dba18c`: 3017 passed, 24 skipped; the merged tree is the
same) · Pushed
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- The #46 benchmark (`docs/benchmarks/generators-on-many-threads.md`) was not
  on a quiet machine (load average about 4 to about 35) and can be rerun on
  request; so can `docs/benchmarks/gram-batches.md`, whose `file_row_number`
  cut lost at 500 columns on one loaded run. (since 2026-11-18)

## Next up

- The next 3.3 area, not chosen yet. Linear or ridge regression would reuse
  the Gram step with Xᵀy (ADR 0058 opens it to users' steps after that). No
  dataset fetcher (ADR 0053).
- #73: PCA's apply SQL takes about p² memory to bind (1.95 GB at 200
  columns in plain DuckDB), outside DuckDB's `memory_limit`; the options
  (a weight matrix written once, a weights table, or a note) are Tomas's
  to choose. #70–#72 are tidies from the PCA build.
- #65's minor follow-ups (listed in its last comments); the first worth
  doing: let `sq.select` shortcuts take a column selector by position, as
  the other groups do.

## Dead ends and traps

- DuckDB's `memory_limit` and `duckdb_memory()` do not count parsing and
  binding a statement: a query of many constants (PCA's apply) holds GBs
  outside them. `ru_maxrss` peaks depend on whether DuckDB has handed
  memory back yet: probe twice. `repr(np.float64(x))` is
  `np.float64(...)` in SQL: write `float(x)!r`. A script outside the repo
  importing `validation` needs `PYTHONPATH` set to the repo. A
  cross-fitted step's `learn` needs the target, so `sq.load` takes its
  names from `Step._derives`. (2026-11-20)
- A wait loop such as `until grep -q "^EXIT=" log` never ends when the
  log's last line has no newline: wait on the PID. Subagents can leave such
  loops behind; check with `pgrep -fl`. DuckDB's numpy fetch has no
  streaming form without pandas or pyarrow, so a Gram learn takes its batches
  from a numbered temporary table by row range. Capture a Gram step's matrix
  in validation at its `learned_from_gram`. `just test` skips the Sphinx
  doctests: a changed docstring example fails only in `just verify` or
  `build-docs`. `sq.load` now refuses learned values for columns a step did
  not learn, and column keys that are not text (`_saving/learned.py`).
  (2026-11-20)
- A step's first positional argument is its columns: `sq.select` refuses a
  number there with a `Fix:`, other groups read it as `cols` and fail later.
  The errors are in `sq.errors`, not `sq`. BSD `sed -i` needs an extension
  argument and has no `\b`: use Edit or perl. (2026-11-20)
- DuckDB 2.0 has no `log1p`: `_log1p` in `metrics/regression.py`.
  scikit-learn's D² pinball baseline is `_weighted_percentile(average=True)`.
  The full validation takes about 47 minutes under load; one runner runs
  alone through `validation.__main__.main([module], ROOT)`. The docs
  tagger's uncommitted frontmatter edits can block a merge: save them as a
  patch, `git checkout` the files, merge, `git apply` (a file the branch
  changed no longer takes it). (2026-11-20)
- `meta_sqlearn` (ADR 0052): one transaction writes one attached database,
  so it is written through a cursor; `con.execute` on the user's connection
  discards their unfinished result. Database names match case-insensitively
  in `ATTACH` but not in `duckdb_databases()` comparisons. (2026-11-18)
- The level planner (`_calls` in `_compose.py`) reads SQL text: DuckDB's
  scalar `filter` is not an aggregate, a subquery's aggregates are its own,
  macro aggregates (`geomean`) are not listed. Nested values against numpy:
  allow 4 ULPs (`NESTED_ULPS`). (2026-11-17)
- DuckDB rounds halves away from zero, numpy to even: compare with `floor`.
  Pandas hands NaN to DuckDB as NULL: insert into a DuckDB table to test NaN.
  A bare `1.0` in SQL is DECIMAL: write `1.0::DOUBLE`. NaN sorts greatest.
  (2026-11-17)
- Projecting `rel.columns` back by name loses a column differing only by
  case: use `StarExpression()`. Read the source once (#59). `.df()` renames
  the second of `a`, `A` to `A_1`. (2026-11-15)
- `_drop_later` tables drop at the next `read`. A `just verify` rerun can
  flip a large-set result to "anomaly" by thread order (ADR 0016): discard
  it. `just verify` rewrites `*.results.json` and `tests.json`: discard ULP
  diffs, commit `tests.json` when tests were added (ADR 0043). (2026-11-15)
- commitlint takes no scope but `hooks`, `site`, `deps`; header and body
  lines at most 72 characters. (2026-11-13)
- When the network drops mid-build, resume the same subagent (SendMessage
  to its id). Never kill a stray test run: wait on its PID. (2026-11-14)
- DuckDB hands `TIMESTAMP WITH TIME ZONE` to Python only through pytz (not
  installed): fetch zoned output as text. `just fmt` can pick up the
  tagger's frontmatter edits: leave them out of commits. (2026-11-11)
- `gh-board status` can fail for one issue now and then: rerun it, then
  `GH_BOARD=glaucis/6 gh-board audit`. (2026-11-11)
- `sq.load` security: per-task reviews passed, yet whole-branch reviews found
  routes from a crafted file to `KeptFolds` (#55) and a 12-byte value that
  hung it (#65). Probe every tag and learned slot end to end after any
  change to `_saving` or a step's learned values; learned values reach
  `Fraction` only as plain `int`/`float`. The class lookup stays static
  (`is`, type descriptors; no `getattr`/`isinstance`/`==` on file data).
  "nanobind: leaked" at exit is DuckDB's noise. (2026-11-20)
- After a merge adding a dependency, run `uv sync` before committing. A
  step's `inputs` sees only names and types, never the table. (2026-11-11)
- Benchmarks: record `uptime` before and after; write large data as Parquet
  with `COPY`, one probe per subprocess. Timing by summing two columns
  measures only those. Relations have no `fetchone()`. (2026-11-12)
- `while pgrep -f name` matches itself: wait on a PID. A `VALUES
  ('a'::ENUM(...))` comes out VARCHAR: cast over the VALUES. (2026-11-10)
- DuckDB reports a collated VARCHAR as `VARCHAR`; a NULL-only column's type
  is `"NULL"`. A cast error between incomparable types comes at execution:
  catch `ConversionException` and `BinderException`. `dataclasses.replace`
  drops `init=False` fields. (2026-11-10)
- DuckDB sums doubles in thread-finish order: compare within a bound (ADR
  0043). (2026-11-09)
- `just test` skips the Sphinx doctests; rebuild docs with `rm -rf
  docs/reference/generated docs/_build && just build-docs`. Wall-clock tests
  compare two sizes in one test. Never pipe `just test` through `tail`
  before `&&`. (2026-11-10)
- The git stash is shared by all worktrees: never a bare `git stash`.
  (2026-11-06)

## Just finished

- #69, #68, #67, merged in `b1d1cc4` and pushed, closed: `sq.load` refuses
  learned names a step never learns, folds unlike the values on all rows,
  columns listed twice and columns out from nowhere (`987347e`); an
  out-of-memory error on a Parquet file names its row groups and a
  `ROW_GROUP_SIZE` (`fcf9db3`); the Gram learn's peak above `check_fits` is
  DuckDB binding PCA's apply SQL, measured and written into `gram-streaming.md`
  (`8dba18c`), its remedy #73. (2026-11-20)
- Decomposition (#66, ADRs 0057 and 0058): `sq.decompose.pca` and
  `sq.decompose(method="pca")`, a Gram step in the core (`_gram.py`), numpy
  as a runtime dependency. Spec `docs/specs/library-decomposition.md`, plan
  `docs/plans/2026-11-20-library-decomposition.md`, runner
  `validation/sqlearn/decomposition/validate_pca.py`, benchmarks
  `gram-batches.md` and `gram-streaming.md`. On branch
  `decomposition` from `1c88839`; whole-branch review and `just verify`
  passed; merged in `cdb2aec` and pushed, #66 closed. It also hardened
  `sq.load` for every step (learned values for columns a step did not learn,
  non-text column keys). Follow-ups #67–#72. (2026-11-20)
