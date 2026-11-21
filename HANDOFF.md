# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-21 · Branch: `read-busy-connection` (worktree
`../sqlearn-76`, on `main`'s `b135f1b`) · Last commit: `7d44141` docs: tests
rerun only when what they depend on changed · Checks: on the branch `just
check` and `just test` passing (3193 passed); `just verify` on `main` at
`b135f1b` passed every step up to the validation, then stopped by the agent
before a reboot
Verify with: `just verify`

## In progress

- [verified] `just verify` on `main` (`b135f1b`, the `profile` fix) was
  stopped by the agent, at Tomas's request before a reboot, during `python
  -m validation`. No result file was half-written; only
  `validation/tests.json` changed, from the finished test step (left
  uncommitted). Do not rerun it on `main`: the branch below contains
  `b135f1b`, and #76 changed `read`, which every runner goes through, so one
  `just verify` on the branch covers both (Tomas, 2026-11-21). Discard
  `main`'s `tests.json` change (`git checkout validation/tests.json`) and
  leave the docs tagger's frontmatter edits (about 20 docs) out of commits.
- [verified] The branch `read-busy-connection` holds #76's fix
  (`52e17d3`), #75's deferral (`1ec69e4`), spec §4's change (`7d44141`) and the
  Phase 1 spec draft. Next: `just verify` on it (about an hour), commit its
  `tests.json`, merge it into `main` (both hold the same `HANDOFF.md`, so no
  conflict), close #76 (github-pm), push, remove
  the worktree and branch.
- [verified] Phase 1's spec, `docs/specs/native-engine-phase-1.md`, drafted
  with Tomas and checked by a builder subagent (its 11 questions answered in
  the text, the agent's calls marked). Waits on his approval below; then
  superpowers:writing-plans for step 1 (the checks).

## Waiting on the user

- Approve the Phase 1 spec, or say what to change. Check the calls marked
  "(the agent's call)" in it. (since 2026-11-21)
- The CLion MCP stays (its debugger, for step 2 on); no other tool or skill
  needed. Told Tomas; nothing to do.
- Benchmarks run on a loaded machine, to rerun on a quiet one if wanted:
  `generators-on-many-threads.md` (#46), `gram-batches.md`, both
  `explore-*.md` pages (load up to 145) and `engine-profile.md` (load 10 to
  17, 2026-11-21). (since 2026-11-18)

## Next up

- Phase 1, once its spec is approved: step 1 (the checks: testmon, xdist,
  recorded validation, the passed-tree record) on today's Python, then the
  build, the workflows and the site (#4, #6), the review (spec §3.7).
- After the port (Phases 1–4): the rest of 3.6 (spec §8: target panel,
  outliers, normality, Kendall, sampling, time series), then the
  application; 3.3 candidates: text features, more preprocessing, truncated
  SVD, `cross_validate`; sqlearn's own models are Phase 5 (spec §3.9).
- #65's other minor follow-ups (in its comments; #65 is closed).
- #75 (Spearman's first scan reads every chosen column) is fixed in the
  port, not in Python (Tomas, 2026-11-21): the C++ scan carries each row's
  position, so the copy goes a column group at a time. The options weighed
  are on the issue.

## Dead ends and traps

- Medium refuses the web-fetch agent (403): ask Tomas to paste the text.
  On Apple clang, `-std=c++26` is accepted with almost no C++26 inside:
  test a feature by its `__cpp_*` macro, never by the flag. (2026-11-21)
- Apple clang has no libFuzzer runtime (`libclang_rt.fuzzer_osx.a` not
  found) and refuses `detect_leaks` on Apple silicon: Homebrew LLVM
  (`/opt/homebrew/opt/llvm`) has both; build with `-isysroot $(xcrun
  --show-sdk-path)`. LLVM 23 lists `-freflection` but the driver ignores
  it. In zsh, `$flags` holding several flags is one word: use `eval` or an
  array. (2026-11-21)

- Subagents writing ADRs invent reasons and attribute them to Tomas unless
  told "no reason the spec does not give"; they leave `pgrep -f` wait loops
  unless told to run `just test` once in the foreground. One, denied a
  `kill`, asked the controller to do it: refuse, ask Tomas. (2026-11-21)
- MLX (weighed for the engine, then left out): float64 runs on its CPU only,
  and there `exp` and `erf` are computed in float32 (`exp(1.0)` 1.86e8 ULPs
  off, `exp(100)` inf); `mx.array` of a float64 numpy array gives float32
  unless `dtype=mx.float64`; float64 on the GPU raises. Research:
  `docs/questions/engine-compute-libraries.md`. (2026-11-21)
- DuckDB 2.0's profiling: `profiling_output` keeps only the last statement;
  with no output file set, `SET enable_profiling = 'json'` prints one JSON
  profile per statement to stderr, so a subprocess can capture them all. Its
  stderr also carries nanobind's leak report, printed at exit after any
  traceback. `duckdb_logs`' timestamps need pytz too: fetch them as text.
  (2026-11-21)
- The docs tagger keeps a stale `summary` after an ADR body is rewritten
  (`mdindex tag` has no force): edit `summary` and `tags` by hand, never the
  `mdindex:` line. After a merge, `git branch -d` refuses when the branch's
  upstream is behind: check `git merge-base --is-ancestor` then `-D`.
  (2026-11-21)
- The harness moves a long foreground command (`just test` chained with
  others) into the background after about 2 minutes: wait for its
  notification, never start a second copy. (2026-11-21)
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
  so it is written through a cursor. With DuckDB 2.0 a user's unfinished
  `execute` result is kept and any other statement on that connection is
  refused (`ResourceInUseException`); `read` probes for it first and refuses
  with a `Fix:`. Database names match case-insensitively
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

- The C++ standard and compilers: C++23 for now (Tomas), C++26 by ADR once
  Apple clang has reflection and contracts; each compiler's job; LeakSanitizer
  and libFuzzer from Homebrew LLVM; written into the Phase 1 spec, §3.8. The
  probe on macOS 27.2.1: Apple clang 21 and LLVM 23.1.6 have neither
  reflection nor contracts, GCC 16.2 has both, experimental; none has
  `std::linalg`. CodeGraph: a root `codegraph.json` in step 2 excludes the
  DuckDB submodules, for this project only (Tomas). (2026-11-21)

- The `profile` fix (`b135f1b`, on `main`, not pushed): skewness and
  kurtosis divide each sum by its power of the variance first, so `[0, 0,
  0, 6e102]` gives 2.0, not inf; `_SCAN_COLUMNS`' docstring says 1,986 MB.
  (2026-11-21)
- #76 (`52e17d3`, on the branch): `read` probes with `SELECT 1` and refuses
  a connection busy with the user's unfinished `execute` result with a
  `Fix:`, for every kind of input. (2026-11-21)
- #75 deferred to the port (`1ec69e4`, options on the issue); spec §4: a
  test reruns only when what it depends on changed, full runs at a release
  (`7d44141`). (2026-11-21)
- The merged remote branch `engine-phase-0` is deleted. (2026-11-21)
