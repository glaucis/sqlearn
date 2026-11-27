# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-27 · Branch: `main` (one commit ahead of `origin/main`) ·
Last commit: `a452ea7 docs: plan the docs cleanup and hand it to a fresh
session` · Checks: passing (`just check`; `just done` last at `78f3ea6`)
Verify with: `just done` (`just verify` is the release tier)

## In progress

None. [verified]

## Waiting on the user

- The audit's first real run, `just audit-groups` (builds a second,
  coverage-instrumented wheel with DuckDB): awaits your go-ahead. Nothing
  claims Python tests or runners since ADR 0073, so it is due before the
  first group claims `PYTHON_TESTS` or `VALIDATION`; that plan carries the
  step. (since 2026-11-27)
- Benchmark reruns, `just benchmarks-due` then `just bench <name>` (ADR
  0072): awaits your go-ahead. Only the `engine/bench` programs are listed;
  the page scripts are in `old_python/`. (since 2026-11-27)

## Next up

- **Next: the docs cleanup**, in a fresh session (Tomas, 2026-11-27): plan
  `docs/plans/2026-11-27-docs-cleanup.md`, approved to start. Implemented
  plans, built or old-Python specs, answered questions and superseded ADRs
  move to an `archived/` folder beside them; ADR numbers never change;
  nothing is deleted. Task 1 adds a link check first. Task 2 stops after the
  classification list: show Tomas the counts and every "consolidate" row,
  and move nothing until he says go.
- Then the Bazel prototype (Tomas, 2026-11-27: one plan at a time):
  `docs/plans/2026-11-27-bazel-prototype.md`, in its own worktree; ask
  before installing bazelisk and before any timing.
- Ideas from the research (`docs/questions/test-selection.md`), none
  decided: a check that `DEPENDS` matches the headers a group includes, rules
  for which group may depend on which, `just affected` (what a change reruns
  and why), a full run at a set cadence compared with the selection.
- When `pyright-lsp` is installed globally (not yet), turn it off here in
  `.claude/settings.json`: `"enabledPlugins":
  {"pyright-lsp@claude-plugins-official": false}`; ty and mypy are this
  project's type checkers (Tomas, 2026-11-27).
- `engine/sqllogic/CMakeLists.txt` gives `sq_test_data(sqllogic ...)` only
  the `.test` files: add every file under `engine/extension/test` (a
  `GLOB_RECURSE`), or a data file beside a `.test` reruns the `sql` task
  while `_ctest` skips the label. Latent: one `.test` file today.
- #86 and #85: the "can wait" follow-ups of selecting by group and of Phase
  1 step 2's reviews, grouped by kind.
- Phase 1 step 3: the release tier's workflows, started by hand, and the
  site's deploy (spec §3.5, §3.6; #4, #6); its plan first, with
  superpowers:writing-plans. Then step 4, the review and the measurements
  (spec §3.7).
- The dependencies the old Python used: numpy (runtime, ADR 0057) and the
  test group's scikit-learn, pandas, polars, optuna, catboost, lightgbm,
  hypothesis, mpmath. Trim them when nothing active uses them
  (`validation/_cases.py` still imports numpy, pandas, mpmath). numpy leaves
  the runtime once XᵀX and `eigh` are C++ on Accelerate and OpenBLAS (ADR
  0063), with an ADR replacing 0057; Eigen stays out (MPL-2.0, ADR 0066).
- The engine's rebuild costs about 24 s after any commit: uv's isolated
  build has a new random path each time, so nanobind and every duckdb-python
  binding object miss ccache. Fix: no build isolation for sqlearn
  (`no-build-isolation-package`), or ccache path settings.
- The published validation pages (ADR 0016) are still to be built;
  `docs/validation/index.md` is a placeholder.
- Windows needs its own crash handler (no POSIX signals; the current one
  calls `sigaction`): when the Windows build starts (ADR 0069). macOS and
  Linux only for now (Tomas, 2026-11-26).
- `just done` runs `just place` before `check-lockfile`, so a stale lock
  fails with uv's error rather than the named check (fails safe).
- Open question: free-threaded Python,
  `docs/questions/free-threaded-python.md` (nanobind's stable ABI excludes
  it).
- After the rebuild: the rest of exploration (spec §8: target panel,
  outliers, normality, Kendall, sampling, time series), then the
  application; sqlearn's own models are Phase 5 (spec §3.9).
- #75 (Spearman's first scan reads every chosen column) is fixed in the
  C++, not in Python (Tomas, 2026-11-21): the scan carries each row's
  position, so the copy goes a column group at a time.

## Dead ends and traps

- A new source in `engine/src/bindings/`, `engine/extension/src/` or
  `engine/bench/` has no compile flags in clangd until `just tidy-engine`
  reruns. The plugin starts a bare `clangd`: name the binary with `lsof`.
  `clangd --check` counts failed refactoring tweaks as errors: read the
  `E[` lines. (2026-11-27)
- Selecting by group: an edit of `validation/__main__.py`, `_cases.py` or
  `_groups.py` reruns every runner, so group them into one commit. The
  first `just done` after a record's key changes reruns everything once.
  sqlearn's version carries the commit hash (`build_identity.hpp`,
  `-DEXT_VERSION_SQLEARN`, `sqlearn_describe.c`): fingerprint the build
  through `_groups.release()`, or every commit reruns everything. clang has
  no `-fpreprocessed`: `_groups.stripped()` uses `-Xclang -dump-raw-tokens`.
  (2026-11-27)
- The docs tagger's frontmatter is committed on its own (`docs: refresh the
  docs index frontmatter`) after checking every `related:` path exists; it
  has written paths that do not exist and names that are not paths. Left
  uncommitted it blocks `git switch`. It keeps a stale `summary` after a
  rewrite: edit `summary` and `tags` by hand, never `mdindex:`. `just fmt`
  can pick its edits up. (2026-11-27)
- commitlint takes no scope but `hooks`, `site`, `deps`; lines at most 72
  characters; a body line starting `word:` reads as a footer.
- ThreadSanitizer delivers signals late (the crash group's chaining cases
  failed, one hung 20 h); TypeSanitizer cannot see the kernel's writes of
  siginfo and ucontext. Every CTest test has a 300 s timeout. Run
  `just sanitize` and `just mutate-engine` after any new group or raw file.
  (2026-11-25)
- macOS drops `SA_RESETHAND` from what `sigaction` reports back. ccache's
  `compiler_check=mtime` serves an old compiler's objects behind `xcrun`:
  the presets check content. DuckDB 2.0.1 refuses `SELECT * FROM (t)`.
  (2026-11-24)
- Apple clang has no libFuzzer runtime and refuses `detect_leaks` on Apple
  silicon: use Homebrew LLVM with `-isysroot $(xcrun --show-sdk-path)`.
  `-std=c++26` is accepted with almost no C++26: test by `__cpp_*` macro.
  In zsh, `$flags` holding several flags is one word. (2026-11-21)
- MLX was weighed and left out: float64 only on its CPU, `exp` and `erf`
  in float32 there (`docs/questions/archived/engine-compute-libraries.md`).
  (2026-11-21)
- pytest-testmon misses code run at import, files read as data and
  compiled code: dropped for selection by group. A `-p` pytest plugin loads
  before coverage starts: import nothing of sqlearn in one. (2026-11-22)
- Subagents: they leave `tail -F`, `until` and `pgrep` wait loops unless
  told not to (check `ps -Ao command | grep "tail -F"` after each); skip
  watching a test fail unless asked for the RED output; invent reasons and
  attribute them to Tomas unless told "no reason the source does not give".
  One reporting BLOCKED while "waiting on its background work" can wake:
  stop it before dispatching another into the same worktree. One denied a
  `kill` asked the controller to do it: refuse, ask Tomas. When the network
  drops (ENOTFOUND), resume the same agent with SendMessage. (2026-11-22)
- While `just test` runs in a worktree, start no other `uv run` there: it
  reinstalls the editable sqlearn after a commit. The harness moves a long
  foreground command to the background after about 2 minutes: wait for its
  notification, never start a second copy. `just verify > log; rc=$?` keeps
  `just`'s exit. A wait loop on a log whose last line has no newline never
  ends: wait on the PID; `while pgrep -f name` matches itself. (2026-11-22)
- A failure that repeats exactly is not summation order: check the
  environment (an OS update changed Accelerate and `eigh`'s last digits;
  `environment.json` records `os_release` and `blas`). DuckDB sums doubles
  in thread-finish order: compare within a bound (ADR 0043). (2026-11-22)
- DuckDB 2.0 facts: no `log1p`; halves round away from zero (numpy: to
  even); a bare `1.0` or `-0.0` literal is DECIMAL; NaN sorts greatest;
  pandas hands NaN as NULL; `FILTER (WHERE ...)` copies inputs per
  aggregate outside `memory_limit` (write `agg(CASE ...)`); exact
  `quantile_cont` and `count(DISTINCT)` do not spill; parsing and binding
  are outside `memory_limit`; `TIMESTAMP WITH TIME ZONE` reaches Python
  only through pytz (fetch as text); a collated VARCHAR reports `VARCHAR`,
  a NULL-only column `"NULL"`; cast errors come at execution
  (`ConversionException`, `BinderException`); projecting columns by name
  loses one differing only by case; an unfinished `execute` result blocks
  the connection (`ResourceInUseException`); `profiling_output` keeps only
  the last statement. (2026-11-21)
- `sq.load` security (for its rewrite): whole-branch reviews found what
  per-task ones missed (#55, #65); values reach `Fraction` only as plain
  `int`/`float`, and the class lookup stays static. (2026-11-20)
- Medium refuses the web-fetch agent (403): ask Tomas to paste the text.
  BSD `sed -i` needs an extension and has no `\b`: use Edit or perl. macOS
  has no `timeout`. The git stash is shared by all worktrees: never a bare
  `git stash`. After `git merge`, `git branch -d` refuses when the upstream
  is behind: check `git merge-base --is-ancestor`, then `-D`. (2026-11-21)
- `gh issue create --project sqlearn` can leave an issue off the board: add
  it with `gh project item-add 6 --owner glaucis --url <url>`, then
  `gh-board status` (rerun once if it fails, then `GH_BOARD=glaucis/6
  gh-board audit`). (2026-11-21)
- Benchmarks: record `uptime` before and after; write large data as Parquet
  with `COPY`, one probe per subprocess. (2026-11-12)

## Just finished

- The old Python moved to `old_python/` (2026-11-27, ADR 0073, plan
  `docs/plans/2026-11-27-old-python.md`): `d4f7d3b` the move, `55cd48e` the
  docs, merged into `main` and pushed. Nothing there runs; `just validate`
  has no runner; `check-mirror` is gone; `tests/src/` is empty until the C++
  brings `sq.` back.
- The research on choosing what a change tests,
  `docs/questions/test-selection.md` (`9e5ce3f`), and the plans for the
  move, the Bazel prototype (`e5f2d73`) and the docs cleanup (`a452ea7`).
