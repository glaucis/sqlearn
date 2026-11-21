# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-21 · Branch: `exploration` (worktree
`.claude/worktrees/exploration`) · Last commit: `b10d464` docs: state the
exploration budgets as DuckDB reported them (#74) · Checks: passing (`just
verify` on it: 3190 passed, 24 skipped, every validation runner 0 fails)
Verify with: `just verify`

## In progress

- #74, the exploration module `sq.explore` (3.6, the library module): built
  on branch `exploration`, every task reviewed, final review and fix wave
  done. Waiting on Tomas's merge (below).

## Waiting on the user

- Merge `exploration` into `main` (28 commits; #74 closes on merge). The
  rulings made during the build are listed in the session's summary and in
  the spec's "ruled during the build" notes. (since 2026-11-21)
- The #46 benchmark (`docs/benchmarks/generators-on-many-threads.md`) was not
  on a quiet machine (load average about 4 to about 35) and can be rerun on
  request; so can `docs/benchmarks/gram-batches.md`, whose `file_row_number`
  cut lost at 500 columns on one loaded run. (since 2026-11-18)
- #4, #6: where the site is hosted (`docs/questions/site-hosting.md`), so
  the README and `switcher.json` get a URL: make the repository public, or
  push the built site to an orphan branch or a public repository. Both fixes
  are a few lines once it is chosen. (since 2026-11-05)

## Next up

- #75: Spearman's first scan reads every chosen column; number it in
  column groups so it is bounded as Pearson's blocks are.
- #76: `read` gives a raw `ResourceInUseException` when the user's
  connection holds an unfinished result; and the trap below about
  `con.execute` discarding it needs rewording (DuckDB 2.0 keeps it).
- One-line follow-up from the final review: `profile`'s skewness and
  kurtosis multiply before dividing (`profile.py`, `_shape`), so a finite
  third or fourth sum near the largest double gives inf where the docstring
  promises NULL (`[0, 0, 0, 6e102]`); divide first. Also `_SCAN_COLUMNS`'
  docstring says "under 2 GB" where the benchmark page says 1,986 MB.
- The rest of 3.6: a target panel, outliers, normality screens, Kendall,
  sampling, time-series views (spec §8), then the application. Models stay
  with scikit-learn and the libraries users install (ADR 0017; Tomas,
  2026-11-20: leave models aside). Other 3.3 candidates: text features,
  more preprocessing, truncated SVD, `cross_validate`/learning curves.
- #65's other minor follow-ups (listed in its comments; #65 is closed).

## Dead ends and traps

- DuckDB's `FILTER (WHERE ...)` gives each filtered aggregate its own copy
  of the statement's inputs: memory grows with the square of the columns,
  outside `memory_limit` (the OS killed `profile` at ~1.2 GB RSS). Write
  `agg(CASE WHEN ... THEN x END)`. `sq.set_config(memory=X)` gives DuckDB
  half of X. No statement over 200 columns fits a 1–2 GB limit on default
  122,880-row Parquet groups (8 threads × a row group of every column):
  read 20 columns a statement. Exact `quantile_cont` and
  `count(DISTINCT)` hold every value and do not spill. A single-threaded
  row-order `avg`/`stddev_samp` was 119 and 13 ULPs off on 100k rows:
  `favg` and a compensated second pass give 1. In DuckDB a `-0.0` literal
  is DECIMAL and becomes +0.0: insert it as text. (2026-11-21)
- DuckDB's `memory_limit` and `duckdb_memory()` do not count parsing and
  binding a statement: a query of many constants (PCA's apply) holds GBs
  outside them. `ru_maxrss` peaks depend on whether DuckDB has handed
  memory back yet: probe twice. `repr(np.float64(x))` is
  `np.float64(...)` in SQL: write `float(x)!r`. A script outside the repo
  importing `validation` needs `PYTHONPATH` set to the repo. A test
  learning twice must `STORE.clear()` between, or the second reuses the
  first. macOS has no `timeout` (nor `gtimeout`): a capped run needs
  another way. A
  cross-fitted step's `learn` needs the target, so `sq.load` takes its
  names from `Step._derives`. (2026-11-20)
- A wait loop such as `until grep -q "^EXIT=" log` never ends when the
  log's last line has no newline: wait on the PID. Subagents can leave such
  loops behind; check with `pgrep -fl`. DuckDB's numpy fetch has no
  streaming form without pandas or pyarrow, so a Gram learn takes its batches
  from a numbered temporary table by row range. Capture a Gram step's matrix
  in validation at its `learned_from_gram`. `just test` skips the Sphinx
  doctests: a changed docstring example fails only in `just verify` or
  `build-docs`. (2026-11-20)
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

- #74 built on `exploration`: `sq.explore.profile`, `histogram`, `top`,
  `missing`, `correlations` (Pearson, Spearman), ADR 0059, validation 809
  pass, guide and benchmarks (`explore-correlations.md`,
  `explore-larger-than-memory.md`: profile and Pearson run on 20 GB at a
  1–2 GB DuckDB limit; Spearman refuses with a `Fix:`, #75). (2026-11-21)
- #65's first follow-up, pushed: a column selector by position passes
  `refuse_positionals` (`sq.select`, `sq.decompose`), `d37b08d`.
  (2026-11-20)
- #70, #71, #72, #73, pushed and closed: the Gram contract tidied and
  documented in `docs/guide/writing-a-step.md`; `validate_pca` sturdier
  (neighbour cut 1e-14 λ₁); small tidies; PCA's weights written once as a
  matrix (learn peak at 200 columns 1.11 to 0.36 GB). Details on each issue.
  (2026-11-20)
