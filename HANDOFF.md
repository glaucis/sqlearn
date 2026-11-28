# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-28 · Branch: `claude/tooling-fixes` (not pushed; level with
`main` plus the plan and the fixes) · Last commit: `fix: name the wheel
rebuild in the loose tests' Fix line` · Checks: passing (`just done`)
Verify with: `just done` (`just verify` is the release tier)

## In progress

The small tooling fixes, plan `docs/plans/2026-11-28-tooling-fixes.md`, on
`claude/tooling-fixes`: Tasks 1 to 3 and 5 to 12 done and reviewed, Task 4
blocked (below). [verified]

## Waiting on the user

- Task 4 (no build isolation for sqlearn, so the 24 s rebuild after a commit
  goes): blocked, nothing committed. Without isolation `uv lock` fails:
  sqlearn's version is dynamic, so resolving needs its metadata built before
  uv's two-phase install, with no scikit_build_core in the environment.
  Baseline counted: 56 misses and 11 hits of 67 objects after a cache-key
  touch. Choose: `[tool.uv.extra-build-dependencies]`,
  `[tool.uv.dependency-metadata]`, or leave the rebuild.
- The plan's "Decisions for Tomas" table (13 #85 items, each with a
  recommendation): none is built until you answer; a yes adds a task. See the
  plan's section of that name.
- Merging `claude/tooling-fixes` into `main`.
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
  1. **The small tooling fixes** are built on `claude/tooling-fixes`; what
     remains is Task 4 and the plan's decisions (both above, waiting on
     you), then the merge.
  2. A benchmark and profiling queue: profiling joins `just benchmarks-due`,
     and one command runs the whole queue on Tomas's go-ahead, when the
     machine is idle (ADR 0072 unchanged: nothing runs by itself).
  3. Phase 1 step 3, then step 4 (below).
  4. The audit's first run, on Tomas's go-ahead (above), before the first
     group claims Python tests or runners.
  5. Then the rewrite's first group, its plan first.
- `validate` is in neither `just affected` nor `just sweep`: add it when the
  first runner lands.
- When `pyright-lsp` is installed globally (not yet), turn it off here in
  `.claude/settings.json`: `"enabledPlugins":
  {"pyright-lsp@claude-plugins-official": false}`; ty and mypy are this
  project's type checkers (Tomas, 2026-11-27).
- #86's item 13 (a runner's claims match a module's last name part) waits for
  the first runner, beside `validate` joining `affected` and `sweep`.
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
  binding object miss ccache. Task 4's choice (above) decides it.
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
  `_groups.py` reruns every runner, so group them into one commit. The
  first `just done` after a record's key changes reruns everything once.
  sqlearn's version carries the commit hash (`build_identity.hpp`,
  `-DEXT_VERSION_SQLEARN`, `sqlearn_describe.c`): fingerprint the build
  through `_groups.release()`, or every commit reruns everything. clang has
  no `-fpreprocessed`: `_groups.stripped()` uses `-Xclang -dump-raw-tokens`.
  (2026-11-27)
- The docs tagger writes `related:` entries that are no paths (`ADR-0029`,
  `docs/adr/0070.md`, a bare page name), even into new files: `just links`
  names each, so fix them before its frontmatter commit. (2026-11-27)
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

- The small tooling fixes (2026-11-28, branch `claude/tooling-fixes`,
  `ce3d768..1ce87c9`, plan `docs/plans/2026-11-28-tooling-fixes.md`): the
  SQL label hashes every file under `engine/extension/test` (`e71fb01`,
  `9d0a394`); `just test` and `just full` write the compiler stamp
  (`6882a40`); `just done` checks the lockfile first (`a76612e`); group
  objects stay out of the link line's fingerprint (`01829d4`); the selection
  modules stay out of a runner's identity and `main` fingerprints once after
  its runners (`6b4f91f`); the group checks name what they could not read,
  and the manifest escapes quotes (`c7d6369`); group fingerprints hash what
  the build reads, pins come from the checked-out HEADs, the version cut is
  sqlearn's own, `_bench run` refuses a stale program (`d52ebfe`,
  `8a74800`); missing programs and corrupt outputs give `Fix:` lines
  (`1cbe000`); link options only on targets that link (`f7fe1b2`); setup
  fetches only the submodules the build uses (`95bcb54`); a C++ exception is
  named by its demangled type (`1ce87c9`). Task 4 is not done.
- The selection, strengthened (2026-11-28, ADR 0080): the groups' test
  programs link static libraries, so a `core` edit no longer reruns
  `test_raw` and `test_crash` (`2ea9fcb`, `4a6ef34`); a check that each
  group's `DEPENDS` matches what it includes, with the layering rules
  (`5de91a7`, `465ad02`); `just affected`, what a change reruns and why
  (`eb8f3a3`, `bae1373`); `just sweep`, every check in full compared with
  what the selection chose, every 7 days (Tomas), `just done` warning when
  it is older (`c670a08`, `7ade7b4`); then the fixes of a whole-branch
  review (`fix: find a missed rerun per test unit in the sweep`): the sweep
  compares `test` unit by unit, `affected` and `sweep` write the compiler
  stamp first, and the layering check skips git-ignored files and refuses
  `..` includes.
- The Bazel decision (2026-11-28): the engine stays on CMake for now,
  ADR 0080, with the signs to look again; the report is answered and in
  `docs/questions/archived/`. A fresh clone no longer fails the `related:`
  check: it now counts a path git ignores as missing, and
  `docs/architecture/writing.md` lost `docs/_static/mathjax`.
- The possible missed rerun the Bazel prototype reported (item 2) is not
  one (2026-11-28): the same `||` swap had passed earlier on exactly those
  bytes, and `_ctest`'s records keep every identity that passed. Making one
  edit twice, with a revert between, reproduces it. No code changed.
- The Bazel prototype (2026-11-27 and 28, plan
  `docs/plans/archived/2026-11-27-bazel-prototype.md`): on the branch
  `claude/bazel-prototype-266e9b`, `c589f90` the groups and their tests
  (Apple clang, Homebrew LLVM, sanitizers, coverage), `8822816` DuckDB as one
  CMake step, the one binary and the wheel, then the report
  `docs/questions/archived/bazel-prototype.md`, rewritten as an 8-item checklist
  when Tomas dropped speed as a criterion (the timings run before that are
  left out of it), then a fix of what a whole-branch review
  found (the module now takes every group object and no test hooks). Not
  merged, not pushed.
- The review of ADRs 0074 to 0079 (2026-11-27; Tomas left it to the
  session): each restates the records it supersedes faithfully. Their status
  lines now say they were written on Tomas's decision to consolidate and take
  no new decision; 0075 leaves how an undeclared step is inspected
  (placeholders in the old Python) to the C++ group; 0079 lets the C++ saving
  group rename or extend the value tags. 0078's shared sort was already
  mechanics.
- The docs cleanup (2026-11-27, plan and list now in
  `docs/plans/archived/`): `305f313` and `4d2fa4c` the link check and the
  `related:` paths it named; `4811972` and `0f8a393` the list and your
  answers; `ab421ee` the moves into `archived/` folders (`docs/adr/`,
  `specs/`, `plans/`, `questions/`, `benchmarks/`); `1267423` `just links`,
  a check of its own on every Markdown file; `1792390` ADRs 0074 to 0079,
  the twenty they supersede archived, the amended ADRs' status lines, the
  index and the stale active pages; then the archiving rule in `CLAUDE.md`
  and `workflow.md`. Nothing was deleted; no ADR was renumbered.
- The old Python moved to `old_python/` (2026-11-27, ADR 0073, plan
  `docs/plans/archived/2026-11-27-old-python.md`): `d4f7d3b` the move, `55cd48e`
  the docs, merged into `main` and pushed. Nothing there runs; `just validate`
  has no runner; `check-mirror` is gone; `tests/src/` is empty until the C++
  brings `sq.` back.
- The research on choosing what a change tests,
  `docs/questions/test-selection.md` (`9e5ce3f`), and the plans for the
  move, the Bazel prototype (`e5f2d73`) and the docs cleanup (`a452ea7`).
