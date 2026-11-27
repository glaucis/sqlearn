# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-27 · Branch: `main` · Last commit: `7597ae9 docs: refresh
the docs index frontmatter` · Checks: passing (`just check`, `just test`;
nothing uncommitted)
Verify with: `just done` (`just verify` is the release tier)

## In progress

None. [verified]

## Waiting on the user

- The audit's first real run, `just audit-groups` (builds a second,
  coverage-instrumented wheel with DuckDB, then runs every test set and runner
  on it: an hour or more on all cores): awaits your go-ahead. It must pass
  before the first group claims Python tests (`PYTHON_TESTS`) or a runner
  (`VALIDATION`) lands, since it is the only check that a claim is not too
  small; the first claim's plan carries that step. (since 2026-11-27)
- The first benchmark reruns, `just benchmarks-due` then `just bench
  <name>` for each due one (ADR 0072): awaits your go-ahead. The pages
  `explore-correlations`, `explore-larger-than-memory` and
  `generators-on-many-threads` have no script, so nothing lists them.
  (since 2026-11-27)

## Next up

- When `pyright-lsp` is installed globally (not yet), turn it off here in
  `.claude/settings.json`: `"enabledPlugins":
  {"pyright-lsp@claude-plugins-official": false}`. ty and mypy are this
  project's type checkers, and pyright disagrees with them (Tomas,
  2026-11-27).

- Follow-ups of selecting by group (Tomas, 2026-11-27: next, in a fresh
  session; Phase 1 step 3 after them or beside them):
  - Move `release()` (the version rule) out of `validation/_groups.py`
    into a file of its own that `_cases.py` and `_groups.py` both import:
    every runner imports `_groups` only for it, so an edit of the
    fingerprint code reruns all 24 runners (about 47 min).
  - `engine/sqllogic/CMakeLists.txt` gives `sq_test_data(sqllogic ...)`
    only the `.test` files: add every file under `engine/extension/test`
    (a `GLOB_RECURSE`), or a data file beside a `.test` reruns the `sql`
    task while `_ctest` skips the label. Latent: one `.test` file today;
    before the first data file lands.
  - Record each validation runner's wall time (and the split between the
    exact maths, the references and sqlearn) in its record, to see where
    the 47 minutes go.
  - Then move as much of the validation as can go to C++ (the exact
    maths, for example with Boost.Multiprecision, the runner code, the
    case generation), keeping Python only where it calls scikit-learn,
    numpy, scipy or pandas to compare; the heaviest runners first, by the
    timing.
- #86: the follow-ups of selecting by group that its reviews rated "can
  wait" (all fail safe today), grouped by kind; the two above that matter
  most are also in this list.
- The published validation pages: ADR 0016 has each step's page generated
  from the runs' `*.results.json`; `docs/validation/index.md` is a
  placeholder until then (`docs/architecture/validation.md` says so).
- Windows needs its own crash handler (no POSIX signals there; the
  current one calls `sigaction`): write it when the Windows build starts
  (ADR 0069). For now macOS and Linux only (Tomas, 2026-11-26).
- #85: the follow-ups of Phase 1 step 2's reviews, triaged "can wait" and
  grouped by area.
- Phase 1 step 3: the release tier's workflows, started by
  hand, and the site's deploy (spec §3.5, §3.6; #4, #6); its plan first,
  with superpowers:writing-plans. Then step 4, the review and the
  measurements (spec §3.7).
- The engine's rebuild costs about 24 s after any commit: uv's isolated
  build environment has a new random path each time, so nanobind's sources
  and every duckdb-python binding object compile again and miss ccache.
  Follow-up: no build isolation for sqlearn (`no-build-isolation-package`)
  with its build requirements in a dependency group, or ccache path
  settings.
- numpy leaves the runtime after the port's Phase 3 (Tomas, 2026-11-24):
  XᵀX (Phase 2) and `eigh` (Phase 3) move to C++ on Accelerate and
  OpenBLAS (ADR 0063); then an ADR replaces 0057, with numpy optional
  (for example `sqlearn[numpy]` for numpy output). Eigen stays out
  (MPL-2.0, ADR 0066). Until then numpy's 0BSD and CC0-1.0 stay allowed
  for numpy alone (ADR 0066, amended).
- `just done` runs `just place` before `check-lockfile`, so a stale lock
  fails with uv's error rather than the named check (fails safe; reorder
  if wanted).
- Open question: free-threaded Python,
  `docs/questions/free-threaded-python.md` (no free-threaded wheel in step
  2: nanobind's stable ABI excludes it).
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

- clangd (2026-11-27). A new source in `engine/src/bindings/`,
  `engine/extension/src/` or `engine/bench/` has no compile flags until
  `just tidy-engine` reruns (only its merged database lists them). The
  plugin starts clangd by name, so `ps` shows a bare `clangd`: name the
  binary with `lsof` (`docs/architecture/setup.md`). `clangd --check`
  counts its refactoring tweaks' failures ("tweak: ... FAIL") as errors:
  read the `E[` lines before taking a count as diagnostics.

- Selecting by group (2026-11-27). Any edit of `validation/__main__.py`,
  `_cases.py` or `_groups.py` reruns all 24 runners (about 47 min): group edits
  to them into one commit. The first `just done` after a record's key changes
  reruns everything once. sqlearn's version carries the commit hash in
  `build_identity.hpp`, the extension's `-DEXT_VERSION_SQLEARN` and the
  generated `sqlearn_describe.c`: anything that fingerprints the build cuts it
  with `_groups.release()`, or every commit reruns everything. clang has no
  `-fpreprocessed` (GCC only): `_groups.stripped()` uses
  `-Xclang -dump-raw-tokens`. The docs tagger's frontmatter edits are committed
  too (Tomas, 2026-11-27), in their own commit
  `docs: refresh the docs index frontmatter`, after checking every `related:`
  path exists; left uncommitted they block `git checkout main` when a branch
  changed the same file. A `just check` under `cargo` in `ps` belongs to another
  project: leave it. commitlint reads a body line that starts `word:` as a
  footer and warns. Subagents doing TDD skip watching the test fail unless the
  dispatch asks for the RED output.
- ThreadSanitizer intercepts signals and delivers them late: the crash
  group's signal-chaining cases failed under it, and one hung 20 h, past
  its child's `alarm(20)`. TypeSanitizer cannot see the kernel's writes of
  siginfo and ucontext, so every read of them is a finding. Every CTest
  test now has a 300 s timeout (`sq_test_timeout`). A group added after a
  task's sanitizer and Mull runs was never run under them: run
  `just sanitize` and `just mutate-engine` after any new group or raw
  file. (2026-11-25)
- macOS drops `SA_RESETHAND` from what `sigaction` reports back, so a
  chained handler cannot honour it (engine/src/crash/handler.hpp).
  ccache's default `compiler_check=mtime` serves objects of an old
  compiler behind the `xcrun` shim: the presets set a content check.
  DuckDB 2.0.1 refuses `SELECT * FROM (t)`, which 2.0.0 accepted: never
  wrap a bare table name in parentheses (`_compose`). uv's isolated build
  has a new random path each time, so every rebuild misses ccache for
  nanobind and duckdb-python (about 24 s a commit). (2026-11-24)
- When the network drops mid-task (ENOTFOUND), resume the same agent
  (SendMessage to its id); it had changed nothing. (2026-11-24)
- pytest-testmon selects from the lines each test ran, so it misses code run
  at import (module constants, `__init__` re-exports, class bases,
  `__post_init__` behind module-level instances), files read as data, and
  anything compiled; under xdist it also never records tests a pass leaves
  out by marker. Three reviews found a new hole each: dropped for per-check
  selection (spec §3.1). Its environment includes every installed
  package's version, and sqlearn's carries the commit hash. A `-p` pytest
  plugin loads before coverage and testmon start: import nothing of
  sqlearn in one. (2026-11-22)
- Subagents leave log watchers behind (13 idle `tail -F /tmp/t6/s1a.log`
  shells, 2026-11-22): every dispatch carries the waiting rule (no Monitor,
  no `tail -F`/`until`/`pgrep` loops); after each agent, `ps -Ao command |
  grep "tail -F"`. A subagent that reports BLOCKED but "waits on its own
  background work" can wake and run commands: stop it (TaskStop) before
  dispatching another into the same worktree. (2026-11-22)

- While `just test` or the validation runs in a worktree, start no other
  `uv run` there: after a commit or a pyproject edit it reinstalls the
  editable sqlearn and the tests reading its metadata fail (2026-11-22).
- An OS update can change Accelerate, numpy's BLAS, and with it the last
  digits of `eigh`: macOS 27.2.1 failed three PCA bounds by a hair, the same
  on every run and on `main` alike; the bounds were loosened with their
  reason. `environment.json` now records `os_release` and `blas`. A failure
  that repeats exactly is not summation order: check the environment.
  `validation.__main__.main` takes `validation/` as its root (`ROOT`),
  never `.`. `just verify > log; echo EXIT=$?` keeps `just`'s exit only
  when saved first (`rc=$?`). (2026-11-22)

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
  alone through `validation.__main__.main([module], ROOT)`. (2026-11-20)
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
  it. `just test` merges `tests.json`; `just validate` rewrites only the
  rerun runners' results (`just validate-all` and `just verify` all of
  them): discard ULP diffs, commit `tests.json` when tests were added
  (ADR 0043). (2026-11-22)
- commitlint takes no scope but `hooks`, `site`, `deps`; header and body
  lines at most 72 characters. (2026-11-13)
- When the network drops mid-build, resume the same subagent (SendMessage
  to its id). Never kill a stray test run: wait on its PID. (2026-11-14)
- DuckDB hands `TIMESTAMP WITH TIME ZONE` to Python only through pytz (not
  installed): fetch zoned output as text. `just fmt` can pick up the
  tagger's frontmatter edits: commit them on their own (2026-11-27).
  (2026-11-11)
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

- clangd for the whole engine (`b85959f`), verified live through Claude
  Code's `clangd-lsp` plugin (2026-11-27): Homebrew clangd 23 runs (linked
  at `~/.local/bin/clangd`), an edit's errors come back from clang and
  clang-tidy, go-to-definition and find-references work, the index lands in
  `engine/build/llvm-dev/.cache/`, the deliberately broken tests are
  silenced. How to check it is in `docs/architecture/setup.md`.

- The validation documented, `docs/architecture/validation.md`
  (`c1811e8`): what it checks, the results, the data, the 24 runners
  (not 21, as the handoff and the spec had it), running it, when each
  reruns, what is planned. The tagger's frontmatter committed
  (`8df448a`); the "can wait" follow-ups filed as #86 (2026-11-27).
- Selecting by group (2026-11-27), merged into `main` as `d1a32ed` and pushed:
  the checks rerun only what a change affects. Spec
  `docs/specs/selection-by-group.md`, plan
  `docs/plans/2026-11-27-selection-by-group.md`, described in
  `docs/architecture/testing.md`. Proof on this machine: a comment edited within
  its line in `core`, and a comment line added to `engine/cmake/warnings.cmake`,
  each reran no library set, no runner, no docs and no sql (the tooling set
  reran for both: it reads the text). Probe commits and their reverts stay in
  the history.
- ADR 0072, benchmarks on Tomas's go-ahead (2026-11-27); the loaded pages
  rerun with their group (`gram-batches.md` at Phase 2's start).
- ADR 0071, FMA only on purpose (Tomas, 2026-11-27).
- ADR 0070 supersedes 0067 (Tomas, 2026-11-27): sqlearn is rewritten in
  C++, the Python library frozen and deleted group by group; `CLAUDE.md`,
  the spec, the docs and issues #79 to #82 follow it.
- `version.cpp` back in Mull's mutation testing (2026-11-26, `1302e68`).
- The crash handler's chaining confirmed, ADR 0069 (2026-11-26).
