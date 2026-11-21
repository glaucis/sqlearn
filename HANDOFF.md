# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-21 · Branch: `engine-phase-0` · Last commit: `eb62ff6` chore:
share CLion's project settings · Checks: passing (`just check`, and `just test`:
3178 passed, on `eb62ff6`; `just verify` not run this session)

Verify with: `just verify`

## In progress

- Phase 0 of the native engine (#78), branch `engine-phase-0`: plan 0a (the
  decisions) running, then plan 0b (the inventory). Spec
  `docs/specs/native-engine.md`.

## Waiting on the user

- Benchmarks run on a loaded machine, to rerun on a quiet one if wanted:
  `generators-on-many-threads.md` (#46), `gram-batches.md`, and both
  `explore-*.md` pages (load up to 145, a Rust build and a VM running).
  (since 2026-11-18)

## Next up

- Phase 0 (#78), as above. The migration comes before any new library area
  (Tomas, 2026-11-21; spec §4).
- Then the three small fixes, before Phase 1:
  - The one-line `profile` fix: its skewness and kurtosis multiply before
    dividing (`profile.py` `_shape`), so `[0, 0, 0, 6e102]` gives inf where
    NULL is promised; divide first. `_SCAN_COLUMNS`' docstring says "under 2
    GB" where the benchmark says 1,986 MB.
  - #75: Spearman's first scan reads every chosen column; number it in
    column groups, as Pearson's blocks are bounded.
  - #76: `read` gives a raw `ResourceInUseException` on a busy user
    connection; reword the `meta_sqlearn` trap below with it.
- Phase 1's spec (#79), brainstormed with Tomas: sqlearn's DuckDB build, the
  safety stack in CI, the ready-made builds. Then #4 and #6: the site on
  GitHub Pages from the public repository, deployed with Phase 1's CI; then
  the README and `switcher.json` get its URL.
- After the migration (Phases 1–3): the rest of 3.6 (spec §8: target panel,
  outliers, normality, Kendall, sampling, time series), then the
  application; 3.3 candidates: text features, more preprocessing, truncated
  SVD, `cross_validate`; sqlearn's own models are Phase 4 (spec §3.9).
- #65's other minor follow-ups (in its comments; #65 is closed).

## Dead ends and traps

- MLX (weighed for the engine, then left out): float64 runs on its CPU only,
  and there `exp` and `erf` are computed in float32 (`exp(1.0)` 1.86e8 ULPs
  off, `exp(100)` inf); `mx.array` of a float64 numpy array gives float32
  unless `dtype=mx.float64`; float64 on the GPU raises. Research:
  `docs/questions/engine-compute-libraries.md`. (2026-11-21)
- DuckDB 2.0's profiling: `profiling_output` keeps only the last statement;
  with no output file set, `SET enable_profiling = 'json'` prints one JSON
  profile per statement to stdout, so a subprocess can capture them all.
  `duckdb_logs`' timestamps need pytz too: fetch them as text. (2026-11-21)
- `gh issue create --project sqlearn` left #77 to #84 off the board without
  an error: add with `gh project item-add 6 --owner glaucis --url <issue
  url>`, then `gh-board status`. The docs tagger once wrote a `related:` path
  that does not exist, and a stray "we still" once appeared atop `CLAUDE.md`:
  read a new file's frontmatter and `git diff CLAUDE.md` before committing.
  (2026-11-21)
- `FILTER (WHERE ...)` copies a statement's inputs per filtered aggregate,
  outside `memory_limit` (the OS killed `profile`): write `agg(CASE ...)`.
  `memory=X` gives DuckDB X/2. No statement over 200 columns fits 1–2 GB
  on default row groups: read 20 a statement. Exact `quantile_cont` and
  `count(DISTINCT)` do not spill. Row-order `avg` was 119 ULPs off: `favg`.
  A `-0.0` literal is DECIMAL (+0.0): insert it as text. (2026-11-21)
- DuckDB's `memory_limit` and `duckdb_memory()` do not count parsing and
  binding a statement: a query of many constants (PCA's apply) holds GBs
  outside them. `ru_maxrss` peaks depend on whether DuckDB has handed
  memory back yet: probe twice. `repr(np.float64(x))` is
  `np.float64(...)` in SQL: write `float(x)!r`. A script outside the repo
  importing `validation` needs `PYTHONPATH` set to the repo. A test
  learning twice must `STORE.clear()` between, or the second reuses the
  first. macOS has no `timeout` (nor `gtimeout`): a capped run needs
  another way. A cross-fitted step's `learn` needs the target, so `sq.load`
  takes its names from `Step._derives`. (2026-11-20)
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
- `sq.load` security: whole-branch reviews found what per-task ones missed
  (#55, #65). After any change to `_saving` or learned values, probe every
  tag and slot end to end; values reach `Fraction` only as plain
  `int`/`float`; the class lookup stays static (no `getattr`/`isinstance`/
  `==` on file data). "nanobind: leaked" is DuckDB's noise. (2026-11-20)
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

- The native engine's spec, approved by Tomas and committed with its
  research page (`e0f1a7d`): C++ inside sqlearn's own DuckDB build (the
  `duckdb` module, a second package), Apple silicon first, nine decisions
  for ADRs 0060–0068, seven phases. (2026-11-21)
- GitHub: milestone "Native engine"; #77 (CPU against GPU benchmarks, under
  #84) and #78 to #84 (Phases 0 to 6, each blocked by the one before), on the
  board; the hosting decision commented on #4 and #6. (2026-11-21)
- The backup branch `main_python` and annotated tag `python-final` at
  `ca2b720`, the last pure-Python state, pushed with `main` (Tomas, 2026-11-21).
  Everything else is committed and pushed too: the docs tagger's frontmatter
  edits (`7ca5a5e`) and CLion's project settings (`eb62ff6`). (2026-11-21)
- The repository is public (Tomas, 2026-11-21), the history searched for
  keys and tokens first (clean), secret scanning and push protection on; the
  README says sqlearn is not ready for use (`ca2b720`). (2026-11-21)
