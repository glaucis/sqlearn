# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-28 · Branch: `workflows-and-site` (local only, not
pushed; `main` is one commit ahead of `origin/main`, `40784ee`) · Checks:
`just check` and `just test` pass on each commit; `just done` not yet run on
the branch

Verify with: `just done` (`just verify` is the release tier)

## In progress

- **Phase 1 step 3, the workflows and the site** (plan
  `docs/plans/2026-11-28-workflows-and-site.md`, #79, #4, #6), on branch
  `workflows-and-site`. Tasks 1 to 6 are committed: `SQ_LLVM_ROOT` (LLVM's
  prefix on macOS and Linux, `validation/_llvm.py`); libstdc++ builds take
  `_GLIBCXX_ASSERTIONS`; GNU ld's map and `addr2line` for crash reports, and
  `just crash-report <report> --map <release map>`; `just check-wheel` and
  `[tool.cibuildwheel]`; `.github/workflows/release-tier.yml` (by hand only)
  with `verify` split into `verify-checks`, `verify-engine`,
  `verify-mutate`, and `verify-linux`; `.github/workflows/site.yml`. Left:
  the first workflow run and its fixes (Task 5 step 6), Pages turned on (Task
  6 step 6), then `just done`, the plan archived, the merge. The spec now says
  step 3 is macOS and Linux; Windows is #89. The rulings made while building
  are in the plan's ledger, `.superpowers/sdd/2026-11-28-workflows-and-site/
  progress.md` (git-ignored).

## Waiting on the user

- **Step 3's first run** (since 2026-11-28): push `workflows-and-site`, then
  start "Release tier" from the Actions tab on that branch (or approve
  `gh workflow run release-tier.yml --ref workflows-and-site`). Hours of
  runner time; the first Linux and GCC build will fail somewhere, as §3.5
  expects. Nothing has run on GitHub yet: the workflows are untested
  [assumed: the LLVM apt packages' names, libc++'s path under
  `/usr/lib/llvm-23/lib`, cibuildwheel copying `/project/build/*/_duckdb.map`,
  the GNU map parser on a real bfd map].
- **GitHub Pages on** (since 2026-11-28): Settings → Pages → Source "GitHub
  Actions", or your yes to
  `gh api -X POST repos/glaucis/sqlearn/pages -f build_type=workflow`. The
  first deploy is at the merge into `main`.
- **A ruling, with step 4's measurement of the hardened library** (ADR
  0065): Linux's libstdc++ builds define `_GLIBCXX_ASSERTIONS` in every
  flavour, release included (the agent's call, 2026-11-28; libc++ gets
  `fast` there).
- Optional: `brew install actionlint`, so the workflows can be linted here
  (`just doctor` lists it as optional); not installed without your yes.
- The first `just bench-queue` (ADR 0081): today it runs `bench_buffer` and
  its profile, seconds each, one core; it measures only on an idle machine.
  Awaits your go-ahead. It replaces running `just bench <name>` one at a
  time.
- The audit's first real run, `just audit-groups` (builds a second,
  coverage-instrumented wheel with DuckDB): awaits your go-ahead. Nothing
  claims Python tests or runners since ADR 0073, so it is due before the
  first group claims `PYTHON_TESTS` or `VALIDATION`; that plan carries the
  step. (since 2026-11-27)

## Next up

- **The preparation before the rewrite, in this order** (Tomas, 2026-11-28:
  he prepares everything before starting, for a clear path):
  1. ~~The small tooling fixes~~: done
     (`docs/plans/archived/2026-11-28-tooling-fixes.md`; #85 stays open for
     steps 3 and 4).
  2. ~~The benchmark and profiling queue~~: merged
     (`docs/plans/archived/2026-11-28-benchmark-queue.md`, #88).
  3. **Now:** Phase 1 step 3 (in progress, above), then step 4 (below).
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
- Phase 1 step 4, after step 3 merges: the review and the measurements
  (spec §3.7).
- The dependencies the old Python used: numpy (runtime, ADR 0057) and the
  test group's scikit-learn, pandas, polars, optuna, catboost, lightgbm,
  hypothesis, mpmath. Trim them when nothing active uses them
  (`validation/_cases.py` still imports numpy, pandas, mpmath). numpy leaves
  the runtime once XᵀX and `eigh` are C++ on Accelerate and OpenBLAS (ADR
  0063), with an ADR replacing 0057; Eigen stays out (MPL-2.0, ADR 0066).
- The published validation pages (ADR 0016) are still to be built;
  `docs/validation/index.md` is a placeholder.
- Windows needs its own crash handler, raw layer and MSVC build before it
  joins the release workflow: #89 (ADR 0069; Tomas, 2026-11-26 and
  2026-11-28).
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

- pytest's `-r` option replaces its default `fE`: `addopts` carries
  `-rfEs`, never a bare `-rs`, which hides the failures from the summary.
  commitlint's `site` is a scope: `ci(site): …`, never `site: …`. A new test
  that reads a file outside `TOOLING_INPUTS` fails
  `test_every_file_the_tooling_tests_read_is_a_tooling_input`: add the path
  there. `ruff check --fix` removes an import added before its first use:
  add the import with the code that uses it. (2026-11-28)
- The profiling queue (2026-11-28): on the first real profile, check that
  (i) a profile's wall time and cores are samply's whole run (start-up and
  symbolication included), not the program's alone: take the program's span
  from the profile if the numbers mislead; (ii) idle-thread samples may
  inflate `system`; (iii) whether samply's rusage covers the program. samply
  0.13.1 records on macOS without `samply setup`: never run `samply setup`
  (it codesigns and changes the system). A subagent that commits while its
  own `just done` runs leaves it "Not remembered": rerun it on the final
  tree before trusting "Checks: passing".
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
  `docs/specs/archived/benchmark-queue.md`, ADR 0081): merged into `main`
  (fast-forward), `93d69e9..35d42bd`. A benchmark run under load is
  recorded as loaded; profiles join `just benchmarks-due`; samply profiles
  are summarised and compared; `just bench-queue` runs every due item on one
  go-ahead, on an idle machine only. Not run yet (above). Pushed
  (`8984fdb`).
