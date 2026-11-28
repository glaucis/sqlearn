# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-28 · Branch: `benchmark-queue` (not pushed, 16 commits ahead
of `main`) · Last commit: `docs: close the benchmark queue`, after `a48e7c8` ·
Checks: passing (`just done`)

Verify with: `just done` (`just verify` is the release tier)

## In progress

None. [verified] The benchmark and profiling queue is built on branch
`benchmark-queue` (issue #88, plan
`docs/plans/archived/2026-11-28-benchmark-queue.md`); the branch awaits your
review and merge.

## Waiting on the user

- Review and merge `benchmark-queue` (16 commits, `git log --oneline
  main..benchmark-queue`); #88 closes on the merge.
- The first `just bench-queue` (ADR 0081): today it runs `bench_buffer` and
  its profile, seconds each, one core; it measures only on an idle machine.
  Awaits your go-ahead.
- The audit's first real run, `just audit-groups` (builds a second,
  coverage-instrumented wheel with DuckDB): awaits your go-ahead. Nothing
  claims Python tests or runners since ADR 0073, so it is due before the
  first group claims `PYTHON_TESTS` or `VALIDATION`; that plan carries the
  step. (since 2026-11-27)
- Benchmark reruns, `just benchmarks-due` then `just bench <name>` (ADR
  0072): awaits your go-ahead. Only the `engine/bench` programs are listed;
  the page scripts are in `old_python/`. (since 2026-11-27)

## Next up

- **The preparation before the rewrite, in this order** (Tomas, 2026-11-28:
  he prepares everything before starting, for a clear path):
  1. ~~The small tooling fixes~~: done (below, "Just finished").
  2. ~~The benchmark and profiling queue~~: built, on `benchmark-queue`
     (`docs/plans/archived/2026-11-28-benchmark-queue.md`, #88).
  3. **Next:** Phase 1 step 3, then step 4 (below).
  4. The audit's first run, on Tomas's go-ahead (above), before the first
     group claims Python tests or runners.
  5. Then the rewrite's first group, its plan first.
- `validate` is in neither `just affected` nor `just sweep`: add it when the
  first runner lands.
- #87: TypeSanitizer's intermittent report on `test_core` (needs-triage):
  decide whether it is TypeSanitizer's reading of reused heap memory or a
  real aliasing problem, then fix it or write a suppression. Until then a
  failing `just sanitize` on `tysan`'s `test_core` alone is that.
- When `pyright-lsp` is installed globally (not yet), turn it off here in
  `.claude/settings.json`: `"enabledPlugins":
  {"pyright-lsp@claude-plugins-official": false}`; ty and mypy are this
  project's type checkers (Tomas, 2026-11-27).
- #86's item 13 (a runner's claims match a module's last name part) waits for
  the first runner, beside `validate` joining `affected` and `sweep`.
- Phase 1 step 3: the release tier's workflows, started by hand, and the
  site's deploy (spec §3.5, §3.6; #4, #6); its plan first, with
  superpowers:writing-plans. Then step 4, the review and the measurements
  (spec §3.7). Step 3 also: detect LLVM's path for Linux (it is
  `/opt/homebrew` until then, Tomas, 2026-11-28); each release keeps its
  module's linker map (`build/<cache tag>/_duckdb.map`, for
  `just crash-report`), so a user's crash report can be read, and Linux
  gets its map and `addr2line` there; the release
  wheel stays built in isolation (`just build-package`, `--no-config`).
- The dependencies the old Python used: numpy (runtime, ADR 0057) and the
  test group's scikit-learn, pandas, polars, optuna, catboost, lightgbm,
  hypothesis, mpmath. Trim them when nothing active uses them
  (`validation/_cases.py` still imports numpy, pandas, mpmath). numpy leaves
  the runtime once XᵀX and `eigh` are C++ on Accelerate and OpenBLAS (ADR
  0063), with an ADR replacing 0057; Eigen stays out (MPL-2.0, ADR 0066).
- The published validation pages (ADR 0016) are still to be built;
  `docs/validation/index.md` is a placeholder.
- Windows needs its own crash handler (no POSIX signals; the current one
  calls `sigaction`): when the Windows build starts (ADR 0069). macOS and
  Linux only for now (Tomas, 2026-11-26).
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

- The profiling queue (2026-11-28): on the first real profile, check that
  (i) a profile's wall time and cores are samply's whole run (start-up and
  symbolication included), not the program's alone: take the program's span
  from the profile if the numbers mislead; (ii) idle-thread samples may
  inflate `system`; (iii) whether samply's rusage covers the program. samply
  0.13.1 records on macOS without `samply setup`: never run `samply setup`
  (it codesigns and changes the system).
- C++ work (2026-11-28): while headers are half changed, build with
  `cmake --build --preset <p>`, not `uv run`, which rebuilds the wheel and
  fails mid-edit. Catch2 here cannot print a `string_view` comparison (it
  fails to link): compare `std::string`. A Catch2 assertion on another
  `std::thread` ends the program (`std::terminate`): collect, then check on
  the main thread. macOS refuses to disable a `sigaltstack` with a size
  below `MINSIGSTKSZ` (ENOMEM). A `constexpr const char *` to a literal
  differs by translation unit: compare a `std::to_array` object's `data()`.
  AddressSanitizer gives every thread a 512 KiB alt stack, so a sigaltstack
  test goes red only in `release`. `atos -o` names macOS's shared-cache
  libraries wrong: `atos -p <own pid>` (same boot).
- A worktree with submodules cannot be removed with plain
  `git worktree remove`: check `git -C <wt> status --porcelain -uall` and
  `git -C <wt> submodule foreach` show nothing, then `--force`. A new
  worktree needs `just setup` (submodules and the module build, minutes).
  After a fast-forward, `just done` on `main` runs nothing: the worktree's
  pass of the same tree counts. Subagents still reach for a `tail -f`
  Monitor while waiting: name it in their brief as forbidden. The docs
  tagger writes non-paths into `related:` (a branch name, "ADR 0001"):
  `just links` now refuses them. (2026-11-28)

- Bazel (the prototype, `claude/bazel-prototype-266e9b`): the registry's
  cpptrace compiles libdwarf (LGPL), so it is built from the submodule;
  rules_foreign_cc passes `--copt` into CMake's flags, so a define both set
  clashes (use `--per_file_copt`); apple_support's toolchain needs
  `--features=external_include_paths` or Catch2's headers fail our
  warnings, and `--macos_minimum_os=15.0` or libc++ refuses 10.11; rules_cc
  sets up no macOS toolchain without `BAZEL_USE_LEGACY_MACOS_TOOLCHAIN=1`;
  two toolchains need `--platform_suffix` or a switch rebuilds everything;
  a `cc_import(alwayslink)` loses to the same archive linked plainly (use
  `-force_load`). bazelisk is installed (`brew install bazelisk`, Tomas's
  yes of 2026-11-27). (2026-11-28)
- A new source in `engine/src/bindings/`, `engine/extension/src/` or
  `engine/bench/` has no compile flags in clangd until `just tidy-engine`
  reruns. The plugin starts a bare `clangd`: name the binary with `lsof`.
  `clangd --check` counts failed refactoring tweaks as errors: read the
  `E[` lines. (2026-11-27)
- Selecting by group: an edit of `validation/__main__.py`, `_cases.py` or
  `_version.py` reruns every runner (the selection modules in
  `_record.SELECTION` no longer do), so group them into one commit. The
  first `just done` after a record's key changes reruns everything once.
  sqlearn's version carries the commit hash (`build_identity.hpp`,
  `-DEXT_VERSION_SQLEARN`, `sqlearn_describe.c`): the fingerprints cut
  exactly sqlearn's installed version, so a build made outside uv (another
  version) over-runs. clang has no `-fpreprocessed`: `_groups.stripped()`
  uses `-Xclang -dump-raw-tokens`. (2026-11-28)
- sqlearn builds without isolation, so `uv lock`, `uv lock --check` and
  `uv add` need the build group installed: in an empty environment run
  `just build-tools` first (`check-lockfile` and `upgrade-dependencies` do).
  `uv build` follows `no-build-isolation-package` too: `just build-package`
  passes `--no-config` to stay isolated. A plain `uv sync --only-group`
  uninstalls the rest: `--inexact`. `[tool.uv.dependency-metadata]` for the
  project itself drops its dependency groups, and
  `extra-build-dependencies` keeps the random build path. CMake's
  `string(JSON SET)` pretty-prints: the groups manifest escapes by hand
  (`sq_json_string`). (2026-11-28)
- A session isolated in a worktree refuses compound `git` commands: run
  plain ones from the worktree. A subagent's sandbox can refuse
  `git submodule update`. A subagent's commit can be refused without its
  noticing: check `git log` and `git status` after each report.
  (2026-11-28)
- The docs tagger writes `related:` entries that are no paths (`ADR-0029`,
  `docs/adr/0070.md`, a bare page name), even into new files: `just links`
  names each, so fix them before its frontmatter commit. (2026-11-27)
- The docs tagger's frontmatter is committed on its own (`docs: refresh the
  docs index frontmatter`) after checking every `related:` path exists; it
  has written paths that do not exist and names that are not paths. Left
  uncommitted it blocks `git switch`. It keeps a stale `summary` after a
  rewrite: edit `summary` and `tags` by hand, never `mdindex:`. `just fmt`
  can pick its edits up. It rewrites frontmatter while `just done` runs, which
  then says "Not remembered": commit its edit on its own, rerun. (2026-11-28)
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

- **The benchmark and profiling queue** (2026-11-28, issue #88, plan
  `docs/plans/archived/2026-11-28-benchmark-queue.md`, spec
  `docs/specs/archived/benchmark-queue.md`, ADR 0081): on `benchmark-queue`,
  `93d69e9..a48e7c8` and the closing commit. A benchmark run under load is
  recorded as loaded; profiles join `just benchmarks-due`; samply profiles
  are summarised and compared; `just bench-queue` runs every due item on one
  go-ahead, on an idle machine only. Not run yet (above).
- **The tooling fixes, closed** (2026-11-28, plan
  `docs/plans/archived/2026-11-28-tooling-fixes.md`, all merged into `main`
  and pushed; #85 stays open for steps 3 and 4, its comments list what each
  task did):
  - Tasks 1 to 12 (`ce3d768..cd40339`): the SQL label hashes every file
    under `engine/extension/test`; `just test` and `just full` write the
    compiler stamp; `just done` checks the lockfile first; #86's follow-ups
    (#86 closed); #85's that needed no decision; a whole-branch review's
    fixes.
  - Task 4 (`a490fa0`): sqlearn builds in the project environment, so a
    rebuild after a commit compiles only what changed (2 of 3 objects
    missed ccache, where 56 of 68 did).
  - Tasks 13 to 21, Tomas's answers to the 13 decisions: a patched
    submodule fails the configure (`58aceb1`); the stubs test is back
    (`93b1c45`); an extension the user installs loads (`1159a23`); our
    compile lines carry the flavour's levels alone (`f9eebd9`); the
    bindings' headers build alone with LLVM (`5b04967`); the fuzz corpus is
    capped (`409e07f`); licence texts are pinned by SHA-256 (`d88c16e`); the
    crash handler reports a stack overflow on the installing thread, keeps
    its image names and finishes its report (`40d556e`); `just crash-report`
    names a report's frames from the module's linker map and says whose
    code crashed (`36be38c`).
- #87 opened (2026-11-28): found while running `just sanitize`, outside the
  tooling fixes (above, "Next up").
