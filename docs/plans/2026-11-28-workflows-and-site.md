---
type: task
tags: [ci, release, linux, macos, github-actions, documentation-site]
summary: "Implementation plan for step 3 of the native engine: GitHub release-tier workflows on macOS and Linux, plus the GitHub Pages documentation site."
related: [docs/specs/native-engine-phase-1.md, HANDOFF.md, docs/adr/0062-apple-silicon-first.md, docs/adr/0063-the-engines-compute-libraries.md, docs/adr/0071-fused-multiply-add-only-on-purpose.md, docs/adr/0065-safety-rules-for-the-cpp.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md]
mdindex: [type=0ebb42, tags=42c6c6, summary=98a63c, related=f8bc99]
---
# The workflows and the site: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 step 3 of the native engine. The release tier runs as
GitHub workflows started by hand, on macOS arm64 and Linux x86_64 and arm64.
It produces each platform's wheel and linker map. The documentation site
deploys to GitHub Pages on each push to `main`, which closes #4 and #6.

**Architecture:** Two workflow files under `.github/workflows/`, both calling
`just` recipes, so CI runs nothing a person can't run locally:
- `release-tier.yml` (`workflow_dispatch` only) has a macOS job group (the
  `just verify` parts, split into parallel jobs), a Linux job per
  architecture (GCC release build and tests, LLVM sanitizers, the Python
  suite on one Python), CodeQL, and the wheels. It also has a release job
  that attaches the wheels and maps to a GitHub Release, only when given a
  `vX.Y.0` tag.
- `site.yml` (push to `main` and `workflow_dispatch`) builds the Sphinx site
  with its doctests and publishes it at
  `https://glaucis.github.io/sqlearn/dev/`.

Before the workflows can pass on Linux, three pieces of the build stop
assuming macOS: where Homebrew LLVM lives, the linker map's format, and the
crash report's symboliser.

**Tech Stack:** GitHub Actions (`actions/checkout`, `astral-sh/setup-uv`,
`extractions/setup-just`, `actions/cache`, `pypa/cibuildwheel`,
`github/codeql-action`, `actions/upload-pages-artifact`,
`actions/deploy-pages`), CMake 4 and Ninja, GCC (manylinux_2_28), LLVM 23
(apt.llvm.org on Linux, Homebrew on macOS), Python 3.12 under uv, pytest.

**Spec:** `docs/specs/native-engine-phase-1.md` §3.4 (releases), §3.5 (CI
and the release tier), §3.6 (the site), §3.8 (each compiler's job), §6 (done
when, step 3). Also ADR 0062 (platforms, the public repository, Pages) and
`HANDOFF.md`'s step 3 extras.

**Scope decision (Tomas, 2026-11-28):** step 3 covers macOS and Linux.
Windows joins once it has its own crash handler and raw layer
(`engine/src/crash/`, `engine/src/raw/` are POSIX), as decided on
2026-11-26. Task 7 amends the spec's "done when" and opens the Windows
issue.

## Global Constraints

- Every task runs through `just`; Python through `uv run --locked`, never pip
  or a bare `python` (ADR 0001, 0008). A workflow step that is more than one
  line of shell calls a `just` recipe instead.
- No CI runs automatically before `1.0.0`: `release-tier.yml` has
  `on: workflow_dispatch` only. `site.yml` is the spec's one exception (push
  to `main`), and it runs no library tests (§3.5, §3.6).
- No release before `1.0.0`. A release is a `vX.Y.0` tag; a patch tag runs no
  release tier (§3.4).
- C++ flags unchanged: C++23, warnings as errors, no `-ffast-math`, FMA
  contraction off (ADR 0063, 0071). GCC builds the Linux release, Apple clang
  the macOS one, Homebrew or apt LLVM the sanitizer, fuzzing and tooling
  builds (§3.8).
- Nothing at run time needs the network (ADR 0006). The workflows download
  their tools; the wheel downloads nothing.
- Every workflow action is pinned to a full commit SHA, with its version in a
  trailing comment. Each job's `permissions:` lists only what it uses, and
  the default is `contents: read`.
- Runtime licences are unchanged. cibuildwheel (BSD-2-Clause) is a CI tool,
  not a runtime dependency.
- A refusal carries a `Fix:` line (ADR 0046).
- British English in prose, American spelling in identifiers (ADR 0010).
  commitlint takes no scope but `hooks`, `site` and `deps`.
- Before each commit `just check` and `just test` pass. At the end
  `just done`. No benchmark runs (ADR 0072).

## Review Focus

1. **The same tree, rebuilt in CI:** a workflow that passes only because
   `build/` or ccache held an older module. The cache key includes the
   compiler stamp and the submodule commits, and the macOS checks job runs
   `just full` and never `just done`, so no "passed tree" record carries over
   (Task 5).
2. **A Linux build that compiles but hardens nothing:** the `_LIBCPP_*`
   macros do nothing on libstdc++. The Linux release must still get the
   standard library's checks (Task 2).
3. **A crash report read with the wrong map:** a map from another build names
   frames wrongly without failing. `just crash-report` checks the map's
   build line against the report's and refuses a mismatch (Task 3).
4. **A runner that silently skips:** a test skipped for want of a platform's
   reference build must show up, not vanish into a green run. Every pytest
   job runs with `-rs` and writes its skip lines to the job summary (Task 5).
5. **A site with broken links under `/dev/`:** relative links built for `/`
   break when served under the version folder. The site job builds with
   `html_baseurl` set and runs `just links` first. A test checks that the
   switcher's and the README's URLs share one base (Task 6).

---

### Task 1: Homebrew LLVM's path, found on macOS and Linux

**Files:**
- Modify: `engine/cmake/toolchain-llvm.cmake`
- Modify: `justfile` (the `llvm` variable, `doctor`, `probe-cxx26`)
- Test: `tests/engine/test_presets.py`

**Interfaces:**
- Produces: `SQ_LLVM_ROOT`, an environment variable and CMake cache
  variable, the LLVM prefix (the directory holding `bin/clang++`). Default:
  `/opt/homebrew/opt/llvm` on macOS, `/home/linuxbrew/.linuxbrew/opt/llvm`
  on Linux. The workflows set it to `/usr/lib/llvm-23`.
- Produces: justfile `llvm := env("SQ_LLVM_ROOT", <the per-OS default>) +
  "/bin"`.

- [ ] **Step 1: Write the failing tests** in `tests/engine/test_presets.py`:
  - `test_the_llvm_toolchain_reads_its_prefix_from_the_environment`: configure
    the `llvm-dev` preset into a temporary binary directory with
    `SQ_LLVM_ROOT=<tmp>/nowhere`. Assert a non-zero exit, and that the output
    contains `Fix:` and `SQ_LLVM_ROOT`.
  - `test_the_llvm_toolchain_asks_xcrun_only_on_macos`: read
    `toolchain-llvm.cmake`. Assert `xcrun` appears only inside an
    `if(APPLE)` block (parse the `if(APPLE)`/`endif()` spans).
  - `test_just_names_one_llvm_prefix`: `just --evaluate llvm` with
    `SQ_LLVM_ROOT=/x` gives `/x/bin`.
- [ ] **Step 2: Run them and watch them fail.**
  `uv run --locked pytest tests/engine/test_presets.py -k llvm -v`: the
  first fails because the message names no `SQ_LLVM_ROOT`, the second on
  `xcrun` outside `if(APPLE)`, the third because `/opt/homebrew/opt/llvm/bin`
  is fixed.
- [ ] **Step 3: Implement.** `toolchain-llvm.cmake` takes the cache variable,
  else `$ENV{SQ_LLVM_ROOT}`, else the per-OS default. Its failure message
  reads `Fix: brew install llvm, or set SQ_LLVM_ROOT to LLVM's prefix`.
  `xcrun`, `CMAKE_OSX_SYSROOT` and the libc++ rpath flags go under
  `if(APPLE)`. On Linux the toolchain links LLVM's own libc++ from
  `${SQ_LLVM_ROOT}/lib` the same way (`-stdlib=libc++` and the rpath), so the
  sanitizer builds keep the libc++ hardening modes. `doctor` and
  `probe-cxx26` use `{{ llvm }}`, and the probe's `-isysroot` only on macOS.
  The header comment says it is no longer Homebrew-only.
- [ ] **Step 4: Run the tests** (as Step 2): PASS. Then
  `just build-engine llvm-dev` still configures on this Mac (it is cached, so
  this costs seconds).
- [ ] **Step 5: Commit** `build: find LLVM's prefix on Linux too`.

### Task 2: The Linux release build hardens with libstdc++

**Files:**
- Modify: `engine/cmake/hardening.cmake`
- Test: `tests/engine/test_presets.py`

**Interfaces:**
- Produces: on a GCC (libstdc++) build, `release` and `profile` define
  `_GLIBCXX_ASSERTIONS`, and `dev`/`debug` define it too, where libc++ gets
  `extensive`. `_GLIBCXX_DEBUG` is never used, because it changes the ABI.
  The choice keys on the standard library (a `check_cxx_source_compiles`
  probe of `_LIBCPP_VERSION`), not on the compiler.

- [ ] **Step 1: Write the failing test**
  `test_every_flavour_hardens_whichever_standard_library_it_gets`: read
  `hardening.cmake` and assert that each flavour sets one hardening
  definition per standard library (`SQ_HARDENING_*` for libc++,
  `_GLIBCXX_ASSERTIONS` for libstdc++). On a Linux runner, also configure
  `release` with GCC and assert that `compile_commands.json` holds
  `-D_GLIBCXX_ASSERTIONS` for `engine/src/core/*.cpp`. Skip that part
  elsewhere, with the reason.
- [ ] **Step 2: Run it and watch it fail** (no `_GLIBCXX_ASSERTIONS` in the
  file).
- [ ] **Step 3: Implement** the probe and the per-library definition in
  `hardening.cmake`. The comment cites ADR 0065. This is the agent's call, and
  Task 7 records it for Tomas's ruling with step 4's measurement of the
  hardened library.
- [ ] **Step 4: Run it**: PASS. Then `just test-engine dev` on this Mac is
  unchanged (still libc++ `extensive`).
- [ ] **Step 5: Commit** `build: harden libstdc++ builds with its assertions`.

### Task 3: The linker map on Linux, and `just crash-report` there

**Files:**
- Modify: `engine/CMakeLists.txt:124-132` (the map's link option)
- Modify: `validation/_crash_report.py` (the map's two formats, `addr2line`,
  `--map`)
- Modify: `justfile` (`crash-report file *flags`)
- Modify: `docs/architecture/crash-reports.md`
- Test: `tests/engine/test_crash_report.py`, with fixtures in
  `tests/engine/data/`

**Interfaces:**
- Produces: `build/<cache tag>/_duckdb.map` on both platforms: ld64's format
  on macOS (`LINKER:-map,<path>`), GNU ld's on Linux
  (`LINKER:-Map=<path>`, which GCC's bfd and gold both write).
- Produces: `Map.read(path: Path) -> Map` detects the format from the
  first non-empty line (ld64: `# Path:`). It gives the same `Map` (code
  symbols by address, each with its object file) for both.
- Produces: `just crash-report <file> [--map <path>]`. `--map` reads a map
  downloaded from a release (Task 5 names it
  `sqlearn-<version>-<platform>.map`). Without it, the build directory's map
  is used, as today.
- Produces: on Linux, frames outside the module are named by
  `addr2line -f -C -e <image> <offset>`, offset = address − load address,
  the line the report already prints (`handler.cpp:178`).

- [ ] **Step 1: Write the failing tests:**
  - `test_a_gnu_map_names_the_same_frames_as_an_ld64_map`: two small fixture
    maps, `tests/engine/data/map_ld64.txt` and `map_gnu.txt`, cut by hand
    from real ones (a sqlearn symbol, a DuckDB symbol, nanobind, cpptrace),
    the same symbols at the same addresses. `Map.read` of each gives equal
    `(address, size, owner)` lists.
  - `test_a_report_from_another_build_is_refused`: a report whose build line
    differs from the map's gives exit 1 and a `Fix:` line naming `--map`.
    Find where the map's build identity is recorded first: if the map carries
    none, write `_duckdb.map.build` (the `sqlearn_describe` line) beside it at
    link time, as a CMake `POST_BUILD` step.
  - `test_linux_frames_outside_the_module_go_to_addr2line`: with
    `subprocess.run` patched, a Linux report calls
    `addr2line -f -C -e <image> <hex offset>` once per image. Assert the
    arguments.
- [ ] **Step 2: Run them and watch them fail**
  (`uv run --locked pytest tests/engine/test_crash_report.py -v`): no GNU
  parser, no `--map`, the `sys.platform != "darwin"` refusal.
- [ ] **Step 3: Implement.** Use `if(APPLE) … elseif(CMAKE_SYSTEM_NAME
  STREQUAL "Linux")` in `CMakeLists.txt` and drop its "step 3" comment.
  `_crash_report.py` gets the GNU parser, the build-line check, `--map`, and
  `addr2line` in place of `atos` on Linux. Remove its macOS-only refusal.
- [ ] **Step 4: Run the tests**: PASS. Then run `just crash-report` on the
  existing macOS fixture report, unchanged.
- [ ] **Step 5: Update `docs/architecture/crash-reports.md`**: Linux, `--map`,
  where a release's map is found. **Commit**
  `feat: read crash reports on Linux and with a release's map`.

### Task 4: The release wheels, built in isolation

**Files:**
- Modify: `pyproject.toml` (`[tool.cibuildwheel]`)
- Modify: `justfile` (`build-package` comment, a new `check-wheel`)
- Create: `validation/_wheel.py`
- Test: `tests/engine/test_package.py`

**Interfaces:**
- Produces: `[tool.cibuildwheel]`: `build = "cp312-*"` (one abi3 wheel),
  `skip = "*-musllinux_*"`, `manylinux-x86_64-image` and
  `manylinux-aarch64-image = "manylinux_2_28"`, `build-frontend = "build"`
  (pypa/build, isolated: it does not read `[tool.uv]`), and
  `test-command = "python -m validation._wheel {wheel}"`, run from the
  project root (`test-sources`).
- Produces: `just check-wheel <wheel>` → `validation/_wheel.py`, exit 0 when
  the wheel is sound:
  - its tag is `cp312-abi3-<platform>`, with `macosx_15_0_arm64` on macOS;
  - it holds `sqlearn/`, `duckdb/` and one `_duckdb` binary;
  - `abi3audit` finds nothing;
  - a fresh venv installing it answers `sq.version()` with the wheel's
    version, refuses no official `duckdb`, and loads the four official
    extensions without the network.
- Consumes: `just build-package` (unchanged: `uv build --wheel --no-config`)
  for macOS. cibuildwheel for Linux.

- [ ] **Step 1: Write the failing tests:**
  - `test_cibuildwheel_builds_one_abi3_wheel_in_isolation`: parse
    `pyproject.toml` and assert the keys above.
  - `test_check_wheel_refuses_a_wheel_without_the_module`: build a zip with
    a wheel's name and no `_duckdb`; `validation._wheel.main` returns 1 with
    `Fix:`.
  - `test_check_wheel_refuses_a_non_abi3_tag`: same, named `cp313-cp313-…`.
- [ ] **Step 2: Run them and watch them fail**
  (`uv run --locked pytest tests/engine/test_package.py -k wheel -v`).
- [ ] **Step 3: Implement** `validation/_wheel.py`
  (`main(argv: list[str]) -> int`), the recipe, and the cibuildwheel table.
  Add `abi3audit` to the `test` group with `uv add --group test`, and its
  licence to `THIRD_PARTY.md` if the licence check asks for it.
- [ ] **Step 4: Run the tests**: PASS. Ask Tomas before running
  `just build-package` here: it is a full isolated DuckDB build, many minutes
  and heavy, and the CPU is busy. Otherwise the wheel is first built in
  Task 5's workflow run.
- [ ] **Step 5: Commit** `build: check the release wheel and build Linux's
  with cibuildwheel`.

### Task 5: The release tier's workflow

**Files:**
- Create: `.github/workflows/release-tier.yml`
- Create: `.github/actions/setup/action.yml` (a composite: uv, just, the
  cache, the submodules)
- Modify: `justfile` (`verify-checks`, `verify-engine`, `verify-mutate`,
  `verify-linux`; `verify` calls the first three)
- Create: `tests/checks/test_workflows.py`
- Modify: `docs/architecture/workflow.md`, `docs/architecture/testing.md`

**Interfaces:**
- Consumes: `SQ_LLVM_ROOT` (Task 1), `_duckdb.map` (Task 3),
  `just check-wheel` and `[tool.cibuildwheel]` (Task 4).
- Produces: `just verify` = `verify-checks`, then `verify-engine`, then
  `verify-mutate`, the same steps in the same order as today:
  - `verify-checks`: lock check, every task with `just full`, `audit-groups`,
    `check-licences`, `test-all`, `test-python-versions`;
  - `verify-engine`: `sanitize`, `leaks-engine`, `fuzz 60`,
    `coverage-engine`;
  - `verify-mutate`: `mutate-engine`.

  Only `verify` remembers the tree.
- Produces: `just verify-linux` runs `test-engine release` (GCC), `dev`,
  `tsan` and `lsan` under LLVM (`validation._ctest --all`), and the Python
  suite on 3.12 with `-rs`. TypeSanitizer and Mull stay macOS-only
  (Mull's plugin is fetched for macOS; #87).
- Produces, in `release-tier.yml`:
  - `on: workflow_dispatch` with one input `tag` (string, optional);
  - `concurrency: release-tier-${{ github.ref }}`;
  - jobs `macos-checks`, `macos-engine`, `macos-mutate` (`macos-15`, each
    `timeout-minutes: 360`);
  - `linux` (matrix `ubuntu-24.04`, `ubuntu-24.04-arm`; LLVM 23 from
    apt.llvm.org's signed repository, `SQ_LLVM_ROOT=/usr/lib/llvm-23`);
  - `codeql` (`ubuntu-24.04`, `languages: c-cpp`, `build-mode: manual`,
    building `just build-engine release`; `security-events: write`);
  - `wheels` (matrix: `macos-15` runs `just build-package`; the two Linux
    runners run cibuildwheel), each running `just check-wheel` and uploading
    the wheel and `sqlearn-<version>-<platform>.map` as artifacts;
  - `release`: `needs` all the above, `if: inputs.tag != ''`; it refuses a
    tag not matching `^v[0-9]+\.[0-9]+\.0$` with a `Fix:` line, then
    `gh release create <tag> --verify-tag` with the artifacts
    (`contents: write`).
- Produces: the cache key is
  `<os>-<arch>-<hash of engine/.compiler-stamp, .gitmodules, the submodule
  commits (git submodule status), pyproject.toml>`, holding ccache's
  directory and `build/`. The jobs run `just full …`, never `just done`.

- [ ] **Step 1: Write the failing tests** in `test_workflows.py`. They parse
  the YAML with PyYAML; it is already in the lock through the docs group, so
  check with `uv tree` before adding anything:
  - `test_the_release_tier_starts_only_by_hand`: `on` has
    `workflow_dispatch` alone.
  - `test_every_action_is_pinned_to_a_commit`: every `uses:` in both
    workflows and the composite matches `@[0-9a-f]{40}`.
  - `test_every_job_names_its_permissions`: a top-level
    `permissions: {contents: read}`, and only `codeql`, `release` and the
    Pages jobs add more.
  - `test_the_release_job_takes_only_a_minor_tag`: the job's `if` and its
    refusal pattern accept `v1.0.0`, `v1.2.0` and refuse `v1.0.1`, `1.0.0`,
    `v1.0.0-rc1`. Extract the regex from the workflow, then match.
  - `test_verify_runs_its_three_parts_in_order`: `just --dry-run verify`
    lists `verify-checks`, `verify-engine`, `verify-mutate` in that order,
    and each part's recipes are those today's `verify` runs (compare with
    the list in this task).
  - `test_every_pytest_job_reports_its_skips`: each `pytest` invocation in
    the recipes the workflows call carries `-rs`.
- [ ] **Step 2: Run them and watch them fail** (no workflow file, no parts).
- [ ] **Step 3: Implement** the composite action, the workflow, the
  recipes, and the step that appends pytest's `SKIPPED` lines to
  `$GITHUB_STEP_SUMMARY`. Look up each action's latest release SHA with
  `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`.
- [ ] **Step 4: Run the tests**: PASS. Then run
  `actionlint .github/workflows/*.yml` (a `brew install actionlint` dev
  tool: add it to `doctor` as optional, the way samply is).
- [ ] **Step 5: Update** `workflow.md`'s release row (the three parts, the
  workflow, its link) and `testing.md`. **Commit**
  `ci: add the release tier's workflow, started by hand`.
- [ ] **Step 6: The first run.** Push the branch, then ask Tomas to start
  the workflow from the Actions tab, or to approve
  `gh workflow run release-tier.yml --ref <branch>`. It is outward-facing and
  takes hours of runner time. Fix each failure on the branch in its own
  commit, using mattpocock diagnosing-bugs for each one that isn't obvious.
  §3.5 accepts that GCC's differences surface here in a batch. A failure
  that needs a design choice goes to Tomas. Done when every job is green and
  each platform's wheel and map are artifacts of the run.

### Task 6: The site on GitHub Pages (#4, #6)

**Files:**
- Create: `.github/workflows/site.yml`
- Modify: `docs/conf.py` (`html_baseurl`)
- Modify: `docs/_static/switcher.json`
- Modify: `README.md:10-11`
- Create: `docs/_redirect/index.html` (the root's redirect to `dev/`)
- Test: `tests/docs/test_site.py`

**Interfaces:**
- Produces: `SITE = "https://glaucis.github.io/sqlearn/"`, the one base the
  tests compare. The `dev` site is at `SITE + "dev/"`, and the root redirects
  there, so `1.0.0`'s versions sit beside it later.
- Produces: `site.yml`: `on: push: branches: [main]` and
  `workflow_dispatch`; `concurrency: pages`, with no cancel in progress. A
  `build` job (`ubuntu-24.04`, the composite setup action and its cache)
  runs `just links`, then `just build-docs`, then assembles `_site/` (the
  HTML under `dev/`, the redirect at the root) and runs
  `actions/upload-pages-artifact`. A `deploy` job runs
  `actions/deploy-pages` (`pages: write`, `id-token: write`, environment
  `github-pages`).

- [ ] **Step 1: Write the failing tests** in `tests/docs/test_site.py`:
  - `test_the_switcher_points_at_the_dev_site`: `switcher.json`'s one entry
    has URL `SITE + "dev/"` (#6).
  - `test_the_readme_holds_no_relative_link`: every Markdown link in
    `README.md` is absolute (`https://`), because PyPI renders it without the
    repo (#4). The python-versions link is
    `SITE + "dev/architecture/python-versions.html"`.
  - `test_the_site_knows_its_base`: `docs/conf.py`'s `html_baseurl` equals
    `SITE + "dev/"`.
  - `test_the_site_deploys_from_main_and_runs_no_library_tests`: `site.yml`
    triggers on push to `main` and `workflow_dispatch` only, and no step runs
    `just test`, `pytest`, `validate` or `test-engine`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement** the files above.
- [ ] **Step 4: Run the tests**: PASS. Then `just links` and
  `just build-docs` (docs only: no engine build if the module is current).
- [ ] **Step 5: Commit** `site: deploy the documentation to GitHub Pages`,
  with `Closes #4` and `Closes #6` in the body.
- [ ] **Step 6: Turn Pages on.** This changes a repository setting, so ask
  Tomas first. Either he sets Settings → Pages → Source to "GitHub Actions",
  or on his yes run
  `gh api -X POST repos/glaucis/sqlearn/pages -f build_type=workflow`. The
  first deploy happens at the merge into `main`. Done when
  `https://glaucis.github.io/sqlearn/dev/` serves the site and the
  switcher's JSON loads there.

### Task 7: The records

**Files:**
- Modify: `docs/specs/native-engine-phase-1.md` §6 (step 3), §3.5
- Modify: `docs/adr/0065-*.md` (an "Amended by" line, if Task 2's
  libstdc++ choice counts as one)
- Modify: `HANDOFF.md`, `CLAUDE.md` (the native-engine sentence)
- GitHub: a new issue, "Windows: the crash handler, the raw layer and the
  MSVC build", on milestone "Native engine", `needs-triage`

- [ ] **Step 1:** Amend §6's step 3 to "passes on macOS arm64 and Linux
  x86_64 and arm64", and add a line to §3.5: Windows joins the workflow once
  its crash handler and raw layer exist (Tomas, 2026-11-28), with a link to
  the new issue.
- [ ] **Step 2:** In HANDOFF, record what Tomas must rule on: Task 2's
  libstdc++ hardening, to go with step 4's measurement of the hardened
  library. Move step 3 to "Just finished" with its commits and the first
  green run's URL. The next item is step 4. Drop the step 3 extras
  (LLVM path, map, isolation), which are done.
- [ ] **Step 3:** `git mv` this plan to `docs/plans/archived/`, run
  `just fmt` and `just done`, name every failure, and commit
  `docs: close the workflows and the site`. Update issues #79 (step 3 done),
  #4, #6 and the board (github-pm).
