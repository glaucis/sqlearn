---
type: note
tags: [bazel, build-system, cmake, prototype, engine]
summary: "Implementation plan for a throwaway Bazel prototype of the sqlearn engine to decide whether to move from CMake, reporting evidence to a questions doc."
related: [docs/questions/test-selection.md, docs/plans/archived/2026-11-27-old-python.md, engine/CMakeLists.txt, engine/cmake/pins.cmake, engine/cmake/warnings.cmake, engine/cmake/hardening.cmake]
mdindex: [type=edb465, tags=817fc2, summary=7eebe0, related=e06904]
---
# A Bazel prototype of the engine: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out, by building it, whether sqlearn's engine can move from
CMake to Bazel now, and write the answer with its evidence to
`docs/questions/bazel-prototype.md`, so Tomas can decide.

**Architecture:** A throwaway branch in its own worktree builds the three
existing groups (`core`, `raw`, `crash`) and their Catch2 tests with Bazel,
beside the CMake build, which stays untouched and keeps working. DuckDB is
wrapped as one CMake step (`rules_foreign_cc`), never given BUILD files of
our own unless the wrap fails. Each task answers one question with yes, no
or "partly, because"; the branch is never merged, only the report is.

**Tech Stack:** Bazel through bazelisk, Bzlmod (`MODULE.bazel`), rules_cc,
rules_foreign_cc, rules_python, nanobind_bazel; the Bazel Central Registry's
`catch2`, `rapidcheck`, `cpptrace`, `nanobind`.

**Spec:** Tomas's question of 2026-11-27, "why not adopt Bazel from the start?",
and the research in `docs/questions/test-selection.md` (part B §1.1, §7.2,
§7.4). Runs after the move of the old Python
(`docs/plans/archived/2026-11-27-old-python.md`), so only the C++ and the
bindings are left to build.

## Global Constraints

- Nothing on `main` changes until Tomas decides; the CMake build, the
  presets and every `just` recipe keep working on the branch.
- The DuckDB submodules under `engine/` are never edited: BUILD files for
  them, if any, live outside them.
- Nothing needs the network at run time; fetching Bazel and its modules is a
  development step. Ask Tomas before installing bazelisk
  (`brew install bazelisk`) or any other tool.
- No benchmark without Tomas's go-ahead: build and test timings (Task 6) are
  asked for first, with how long and how heavy.
- Runtime code: permissive OSI licences only. Bazel and its rules are
  development tools (Apache-2.0).
- C++23, warnings as errors, no `-ffast-math`, FMA contraction off: the
  Bazel build compiles with the same flags as `engine/cmake/warnings.cmake`
  and `hardening.cmake`, or the report says which it could not set.
- British English in the report; each claim with its evidence (a command and
  its output, or a source).

## Review Focus

1. **A prototype that passes by building less**: a flag dropped, a test
   skipped, a hardening option left out. The report lists every difference
   from the CMake build's flags and tests.
2. **Apple clang versus Homebrew LLVM**: the release build uses Apple clang;
   sanitizers, coverage and fuzzing need Homebrew LLVM. A yes needs both.
3. **The one binary**: sqlearn's C++ must end up inside DuckDB's `_duckdb`
   binary, with `duckdb/` and `sqlearn/` in one wheel. A separate `.so` is a
   no for that question, not a pass.
4. **Selection**: whether a change to `core` reruns only what depends on
   `core`, and whether a comment edit reruns anything (Bazel hashes raw
   contents; record what happens).
5. **macOS sandboxing**: whether an undeclared input is caught on this Mac,
   or only on Linux.

---

### Task 1: Bazel builds and tests `core`, `raw` and `crash`

**Files:**

- Create: `MODULE.bazel`, `.bazelversion`, `.bazelrc`, `engine/BUILD.bazel`,
  `engine/src/core/BUILD.bazel`, `engine/src/raw/BUILD.bazel`,
  `engine/src/crash/BUILD.bazel`, the tests' `BUILD.bazel` beside them
- Report: `docs/questions/bazel-prototype.md` (created here, one section per
  task)

- [ ] **Step 1:** Worktree and branch `bazel-prototype` from `main` after the
      old-Python move has merged.
- [ ] **Step 2:** `MODULE.bazel` with rules_cc and the registry's `catch2`,
      `rapidcheck`, `cpptrace` at the versions the CMake build pins
      (`engine/cmake/pins.cmake`); `.bazelversion` the current LTS.
- [ ] **Step 3:** One `cc_library` per group with the group's `SOURCES` and
      `DEPENDS` from `engine/CMakeLists.txt`; one `cc_test` per group's
      test program with its `DATA` as `data`, its timeout as
      `timeout`/`size`.
- [ ] **Step 4:** `.bazelrc` sets the flags of `warnings.cmake` and
      `hardening.cmake` for our code only.
- [ ] **Step 5:** `bazel test //engine/...`: expect every test the CMake
      build runs to run and pass. Record the command, the test count beside
      `ctest -N`'s, and every flag that could not be set.

### Task 2: Both compilers

- [ ] **Step 1:** Default toolchain: confirm `bazel test //engine/...` used
      Apple clang (`bazel aquery` shows the compiler path).
- [ ] **Step 2:** A Homebrew LLVM toolchain (`/opt/homebrew/opt/llvm`, with
      `-isysroot $(xcrun --show-sdk-path)`), selected by a `--config=llvm`.
- [ ] **Step 3:** `--config=asan` (AddressSanitizer and UBSan) on the LLVM
      toolchain: expect the groups' tests to pass, and the crash group's
      chaining cases to behave as under `just sanitize`. Record each
      sanitizer tried, and which failed to build.
- [ ] **Step 4:** Source-based coverage: `bazel coverage` on the LLVM
      toolchain, then `llvm-cov report` on its output. Record whether per
      group coverage comes out.

### Task 3: DuckDB inside Bazel

- [ ] **Step 1:** Wrap DuckDB's CMake build (`engine/duckdb-python` and its
      DuckDB) with `rules_foreign_cc`'s `cmake()`, as the shared part is
      today: one opaque step.
- [ ] **Step 2:** Build it. Record: success or the first error, and the cold
      build's wall time only if Tomas has said yes to timing (Task 6).
- [ ] **Step 3:** If the wrap fails, write down why and stop this task: BUILD
      files of our own for DuckDB are out of the prototype's scope, and the
      report says what they would take.

### Task 4: The one binary and the wheel

- [ ] **Step 1:** Link the groups' objects into DuckDB's `_duckdb` module
      (as `sq_add_to_module` does), with nanobind_bazel for the bindings.
- [ ] **Step 2:** Build a wheel holding `duckdb/`, `sqlearn/` and the one
      `_duckdb` binary (rules_python's `py_wheel`).
- [ ] **Step 3:** In a fresh uv environment, install it and run
      `uv run python -c "import sqlearn as sq; print(sq.version())"`;
      expect one line naming sqlearn, DuckDB and the compiler.
- [ ] **Step 4:** Run `tests/engine` against that wheel with `py_test`;
      expect the same results as `just test`.

### Task 5: What a change reruns

- [ ] **Step 1:** After a passed `bazel test //...`, edit a function body in
      `engine/src/core/`; run `bazel test //...` and record which targets
      reran.
- [ ] **Step 2:** Revert, then edit only a comment in the same file; record
      which reran (sqlearn's checks rerun nothing for it today).
- [ ] **Step 3:** Edit `engine/src/crash/`; record whether `core`'s tests
      were cached.
- [ ] **Step 4:** Add a test reading a file it does not declare; record
      whether the macOS sandbox fails it.
- [ ] **Step 5:** Record whether a `py_test` can depend on one group alone
      while it loads the one binary, or only on the whole binary.

### Task 6: Timings, on Tomas's go-ahead

- [ ] **Step 1:** Ask Tomas: cold build, rebuild after a one-line change in
      `core`, and a no-change `bazel test //...`, each against the same
      operation with CMake and `just`; about how long and how heavy.
- [ ] **Step 2:** On his yes only: run each with `uptime` before and after,
      and record the numbers with the load.

### Task 7: The report and the recommendation

- [ ] **Step 1:** `docs/questions/bazel-prototype.md`: a table of the
      questions (Tasks 1 to 6) with yes, no or "partly, because", each with
      its evidence; then what moving would replace (`engine/CMakeLists.txt`,
      `engine/cmake/`, the presets, the `just` recipes, `validation/_groups.py`,
      `_ctest.py`, `_checks.py`'s records) and what it would keep.
- [ ] **Step 2:** A recommendation in one paragraph: move now, move later at
      a named sign, or keep CMake with groups. No reason the evidence does
      not give.
- [ ] **Step 3:** On `main`, commit only the report (`just fmt`,
      `just done`): `docs: report what a Bazel build of the engine showed`.
      The prototype branch stays unmerged until Tomas decides.
