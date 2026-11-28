---
type: question
tags: [bazel, build-system, cmake, prototype, engine]
summary: "A Bazel prototype of sqlearn's engine checked item by item against today's home-made selection of checks, with the evidence, and whether to move from CMake."
related: [docs/plans/archived/2026-11-27-bazel-prototype.md, docs/questions/test-selection.md, docs/architecture/testing.md, engine/CMakeLists.txt, validation/_ctest.py, validation/_checks.py]
---
# Can sqlearn's engine move from CMake to Bazel now?

Open: the prototype has answered its questions, and the decision is Tomas's.
The prototype of 2026-11-27 and 28
([plan](../plans/archived/2026-11-27-bazel-prototype.md)) answers Tomas's
question "why not adopt Bazel from the start?" and part B of the
[test-selection research](test-selection.md). It was built on the branch
`claude/bazel-prototype-266e9b`, beside the CMake build, which it leaves
untouched; that branch is not merged. Bazel 9.3.3 through bazelisk 1.31.0, on
macOS 27.2 (Apple silicon), Apple clang 21.0.0.

Bazel is judged here on features, not speed (Tomas, 2026-11-28): accuracy is
the criterion everywhere, and the plan's
timings are left out. His aim, in his words: run linting, formatting, tests,
validation (and later profiling) only when it matters and when it is needed;
never on code where it has already passed, never when the code has not
changed, and always when the code has not changed but something it uses (an
include, an import, a function in another group) has. Each item below
compares Bazel with today's home-made selection (`validation/_checks.py`,
`validation/_ctest.py`, `just done`'s records and selecting by group,
[testing](../architecture/testing.md)) like for like.

Every Bazel run below is `bazel test //engine/...` (the dev flavour, the
default) or with `--config=release`, after a passed run, and "ran" lists the
tests not served from Bazel's cache; "compiled" lists the C++ compiles that
ran (from `--execution_log_json_file`). The prototype's Bazel targets are its
C++ groups and their tests, DuckDB's module, the wheel and one `py_test`;
nothing else was ported.

## The checklist

| Item | Bazel | Today's selection |
| --- | --- | --- |
| 1. A check that passed on this exact input runs nothing again | Yes, with `--disk_cache`; without it, partly, because only each test's last result is kept | Yes for every check (`just done`'s records); a C++ edit still recompiles, and only the newest records are kept |
| 2. A change reruns exactly what depends on it | Yes, finer: a `core` code change reran `core`'s tests alone | Partly, because a `core` code change reran `core`, `raw` and `crash` (the test programs link every `core` object) |
| 3. A change in something used reruns its users | Yes, for headers and imports Bazel is told of | Yes for C++ headers; a Python import reruns every Python set |
| 4. A comment-only or docs-only edit | C++: a comment within its lines reruns nothing; a comment adding a line reruns in dev. Python: any comment reruns its tests. Docs: nothing | More reruns for C++ comments (`core`'s C++ tests even for one within its lines); docs: `links` and `docs` |
| 5. An undeclared input is caught, on this Mac | Partly, because a relative read fails, an absolute one passes and goes stale | No: nothing checks a test's reads |
| 6. Every other check selected the same way | Partly, because each check can be selected as tightly as its inputs are declared, often tighter than today (clang-tidy, include-what-you-use, headers-alone, ty, mypy, the SQL tests per target or file), but only the C++ tests, `parse_headers` and `layering_check` were tried; the rest needs rules of ours or from the registry | Yes, every check, by its own records |
| 7. Identical product | No: the list below is not empty | The reference |
| 8. What it would replace | The CMake build, the C++ half of the selection, and the wheel's builder; it adds Bazel's files and knowledge | |
| 9. Benchmarks: knowing which are due | Partly, because Bazel can hash a benchmark's inputs, but the record of runs made on an idle machine stays ours | Yes (`just benchmarks-due`) |

## 1. A check that passed on this exact input runs nothing again

**Bazel: yes, with a disk cache.** After a passed run, the same tree again:
`Executed 0 out of 15 tests: 14 tests pass and 1 was skipped.` Without a
disk cache Bazel keeps only each target's last outputs, so going back to a
state that passed before reruns it: after an edit in `core/parse_version.cpp`
and its revert, `ran: //engine/fuzz:replay_parse_version`, `ran:
//engine/src/core:test_core`. With `--disk_cache=<dir>` the same sequence
(seed, edit, revert, edit again) gave, for the revert and for the second
edit, `compiled: nothing` and `Executed 0 out of 15 tests`: nothing was
compiled or run again, either way.

**Today: yes.** `just done` on a passed tree runs nothing
(`core: unchanged since a passed run`, `test: unchanged since a passed run`,
`sql: unchanged since a passed run`), and `validation._ctest` keeps the
newest records, so a reverted state it passed is "unchanged" too. But Ninja
recompiles a reverted C++ file (it compares times, not contents), and the
records kept are the newest ones only (`KEPT`, `_checks.py`).

## 2. A change reruns exactly what depends on it

**Bazel: yes, and finer than today.** A code change in `core`
(`rest.remove_prefix(offset_)` made `rest = rest.substr(offset_)` in
`core/parse_version.cpp`) gave, in dev,
`ran: //engine/fuzz:replay_parse_version`, `ran: //engine/src/core:test_core`,
`Executed 2 out of 15 tests`. `test_raw` and `test_crash` use `core`, and were
relinked, but came out byte for byte the same: Bazel links static archives, from
which a program takes only the objects it uses, and neither uses the parser. A
change to `crash` (a string of the macOS crash report) gave
`ran: //engine/src/crash:test_crash` alone, every `core` test cached; in release
also `ran: //engine/bazel/wheel:import_test`, since the one binary changed.

**Today: partly.** The same `core` change, then
`uv run --locked python -m validation._ctest dev`: `Linking CXX executable
test_core`, `test_raw`, `test_crash`, then `Test #1: test_core ... Passed`,
`Test #3: test_crash ... Passed`, `Test #2: test_raw ... Passed`
(`must_not_compile: unchanged since a passed run`). `_ctest` knows a program
by its bytes, as Bazel does, but CMake's groups are object libraries, so
every `core` object is linked into `test_raw` and `test_crash` and their
bytes change. Static libraries for the test programs might give CMake the
same as Bazel; not tried.

One result looked like a missed rerun and is not one (diagnosed 2026-11-28).
After swapping the two sides of an `||` in `core/parse_version.cpp`,
`validation._ctest` said `core: unchanged since a passed run` although
`test_core`'s bytes differed from the build before it (`md5` `2045707…`
before, `0ccd4a7…` after). The same swap had been made earlier in the
prototype, and `core`'s tests had run and passed on exactly those bytes. The
records keep every identity that passed, not only the last one, so the
second time the swap was rightly found already passed. Making one edit twice,
with a revert between, reproduces it: the first time `core` reruns, the
second time it is "unchanged", the program's bytes the same both times.

## 3. A change in something used reruns its users

**Bazel: yes, for what it is told.** `raw/buffer.hpp` includes
`core/expects.hpp`. With `[[unlikely]]` taken out of `SQ_EXPECTS` in that
header alone: `compiled: engine/src/raw/buffer.cpp,
engine/tests/core/test_error.cpp, engine/tests/raw/test_buffer.cpp`, `ran:
//engine/src/raw:test_raw`, `Executed 1 out of 15 tests`: `raw`'s files did
not change, and its test reran. Bazel finds a C++ file's headers from the
compiler, among the headers the target declares. On the Python side a
`py_test` depends on the `py_library` targets it names, whole: adding a line
of code to `src/sqlearn/errors.py` gave `ran: //engine/bazel/wheel:import_test`.

**Today: yes for C++, coarser for Python.** The same header change, then
`validation._ctest dev`: the same three compiles, then `test_raw` and the
eight must-not-compile cases reran (they include `raw/buffer.hpp`, and
`_ctest` hashes what a compile reads). Bazel reran those eight compiles too,
and kept the tests' results because the outcomes were the same. The
`errors.py` change, then `just test`: `tooling: tests/checks tests/githooks
tests/validation tests/engine tests/docs tests/test_environment.py`, `443
passed, 9 skipped`: every Python test, since every set uses `src/`.

## 4. A comment-only or docs-only edit

| Edit | Bazel | Today ([testing](../architecture/testing.md), "What reruns for a change") |
| --- | --- | --- |
| a comment in `core/parse_version.cpp` within its lines | `compiled` that file, nothing ran (the object was the same) | `core`'s C++ tests, which read the text |
| a comment line added there | dev: `test_core` and the replay ran (the debug information moved); release: relinks, nothing ran | `core`'s tests and every Python set and runner |
| a comment added to `src/sqlearn/errors.py` | `ran: //engine/bazel/wheel:import_test` | per testing.md, a set's identity is its files' contents, so it reruns (not run here) |
| a line added to `docs/questions/README.md` | `compiled: nothing`, `Executed 0 out of 15 tests`, both flavours | `links` and `docs` |

Bazel hashes a file's bytes, so a comment in a Python file is a change; for
C++ it is the object's bytes that decide whether a test reruns. Docs are no
input of any Bazel target: if `links` and the site moved to Bazel they would
be, and would rerun as they do today.

## 5. An undeclared input is caught, on this Mac

**Bazel: partly.** Two temporary `sh_test` targets ran `head -c 40` on
`engine/src/core/version.cpp`, which neither declares. By its runfiles path:
`FAILED`, `head: engine/src/core/version.cpp: No such file or directory`
(the runfiles hold only what is declared, sandbox or not). By its absolute
path: `PASSED`, the darwin sandbox let the read through; after that file was
edited, `(cached) PASSED`: the result went stale. Linux was not tried. The
two tests are not on the branch.

**Today: no.** A CTest test's identity (`_identities` in
`validation/_ctest.py`) is its CTest entry, the bytes of the files its
command names, the libraries a program of the build loads and its
`REQUIRED_FILES`; a file it reads without declaring is in none of them, and
nothing runs a test in a sandbox.

## 6. Every other check, selected the same way

Built under Bazel: the C++ groups' tests, the must-not-compile cases, the
canaries, the corpus replay and one `py_test`. Two features of Bazel's C++
toolchains were also tried on the groups: `parse_headers` and
`layering_check` (below). Everything else is what it would take, not tried.

How Bazel selects a check: a check is an action or a test whose declared inputs
are hashed; it reruns when one of them changes and not otherwise. So a check can
be selected **as tightly as its inputs are declared**: per file if it gets one
action per file, per target if it runs per target. Today, each task of
`validation/_checks.py` names its inputs as git pathspecs and runs per file
(`format`, `lint`, `docstrings`) or whole (the others); the C++ and Python tests
have records of their own ([testing](../architecture/testing.md)).

"Tighter" below means fewer reruns for the same change, with nothing missed.

### Format

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| ruff format | per file | as tight (per file) | rules_lint's formatters run on the working tree directly ("Can format files not known to Bazel"), not as cached actions; a check that a file is formatted, cached, would be a test per file of ours |
| Markdown wrap (rumdl) | per file | as tight | a test per file of ours; rules_lint has no rumdl |
| clang-format | per file | as tight | rules_lint (C/C++ formatter), with the same caveat as ruff format |
| gersemi | per file | gone | it formats CMake files; a move leaves only the DuckDB step's `CMakeLists.txt` |

### Lint

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| ruff | per file | as tight, or per target | rules_lint's ruff linter, an aspect over `py_library` targets |
| markdownlint (rumdl check) | per file | as tight | a test per file of ours |
| typos | per file | as tight | a test per file of ours, over every file a target declares; files no target declares need a filegroup |
| clang-tidy with the static analyser | whole engine, when any of its inputs changed | tighter: per target, rerun when a file or header of it changes | rules_lint's clang-tidy aspect, with our `.clang-tidy` files and the LLVM toolchain; today's `validation/_tidy.py` builds one compile database, which Bazel does not write |
| include-what-you-use | whole engine | tighter, partly replaced | no rule found in the registry: an aspect of ours. `layering_check` (tried) covers part of it: `bazel build --features=layering_check //engine/src/... //engine/fuzz/...` first failed `test_core` (`does not depend on a module exporting 'catch2/catch_test_macros.hpp'`) and `test_raw` (`engine/tests/raw/test_buffer.cpp:3:10: error: module //engine/src/raw:test_raw does not depend on a module exporting 'core/error.hpp'`): includes that reach a header only through another target. With the tests given their group's direct dependencies, as CMake's `DEPENDS` does, it passes. It checks that what is included is declared; it does not check, as include-what-you-use does, that what is used is included |
| headers-alone | whole engine, every header | tighter: per header | rules_cc's `parse_headers` feature (tried): `bazel build --features=parse_headers` on the three groups built, and `bazel aquery` shows 4 header actions for `raw`'s 4 headers, each compiled alone and cached per header. The bindings' headers would need the release configuration |

### Types and docs in code

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| ty | whole program | tighter, per target | rules_lint's ty linter, over `py_library` targets |
| mypy strict | whole program | tighter, per target | rules_mypy (registry 0.41.0), which runs mypy per target on its dependencies' results |
| numpydoc | per file under `src/` | as tight | a test per file of ours |
| pydoclint (`check-docstring-args`) | per file under `src/` | as tight | rules_lint's pydoclint linter |
| check-stubs | by hand (`just check-stubs`) | as tight, or selected | a test on the stubs and the module it checks, rerun when either changes |
| the public API snapshot | by hand (`just api-snapshot`), checked by `tests/engine/test_package.py` | as tight | that test as a `py_test`, with `tests/public_api.txt` as data |

### Tests

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| the C++ groups (Catch2) | each group, by its program's bytes | tighter (item 2), built | built |
| the must-not-compile tests | one unit, by what their compiles read | as tight, each case alone | built (`engine/bazel/compile_test.bzl`) |
| the Python sets: fast, serial, slow | by set (`tooling`, a group's, `unclaimed`), each by its identity | as tight as the targets: per test file, if each is its own `py_test` with its imports declared; never below the one binary | pytest under rules_python's `pip.parse` and a lock of the test group; `tags = ["exclusive"]` for serial, a tag and `--test_tag_filters` for slow; the imports declared by hand or generated (Gazelle's Python extension, not tried) |
| the SQL tests (`just sql`) | whole, when the extension, our C++, DuckDB's pin or the compiler changed | tighter: per `.test` file, with its data | DuckDB's `unittest` as a second CMake step (the `sqllogic` preset), and one `sh_test` per `.test` file with its data files declared; this also closes HANDOFF's gap of data files beside a `.test` |
| the hook tests | in the `tooling` set | as tight | a `py_test` with `.githooks/` and `commitlint.config.mjs` as data |
| the Python version matrix | by hand (`just test-python-versions`) | can be selected, per version | rules_python registers several interpreters; a `py_test` per version (the version as a configuration). Every Python test runs on the one binary, so each still depends on all of it |

### Validation

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| the runners (none exist now) | per runner, by its imported modules, its groups' fingerprints and `uv.lock` | as tight, if declared | a runner is a `py_test` (or a `py_binary` and a test of its output): its imports as `deps` on `py_library` targets, its data files as `data`, and the one binary; a runner that measures one group still depends on the whole binary, as the Python tests do |
| `audit-groups` | by hand: a coverage wheel shows which groups each Python test and runner uses, checked against their claims | still needed, changed | under Bazel the claims would be the declared `deps`, and the audit the check that what runs matches them; `layering_check` does that for C++ includes, nothing does it for Python imports or for code reached through the binary. It stays a script of ours |

### Docs

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| the site build and the doctests | whole, when `docs/`, `src/` or the module changed | as tight (whole) | one action running `sphinx-build` with `docs/`, `src/` and the wheel as inputs; no Sphinx rules found in the registry, so a rule of ours. Sphinx reads the whole site at once, so it cannot be finer |
| `just links` | whole, every Markdown file | as tight, or per file | a `py_test` with every Markdown file as data, as today; per file would also need every file a link names |

### Hygiene

| Check | Today | Under Bazel | What it would take |
| --- | --- | --- | --- |
| gitleaks | the files a commit holds (pre-commit hook) | as tight, but it belongs to the commit | it reads what is staged, which is no build input: it stays a git hook |
| check-lockfile | every `just done` | as tight | an action on `pyproject.toml` and `uv.lock` running `uv lock --check` |
| check-licences | by hand (`just verify`) | can be selected | an action on `uv.lock`, `THIRD_PARTY.md` and the installed packages' metadata |
| check-no-devdata | every `just done`, the whole of `src/` | as tight, or per file | a test over `src/sqlearn` |
| commitlint | each commit message (commit-msg hook) | not a build check | the message is no build input: it stays a git hook |

### The release tier, run in full by hand

Bazel only has to run each one:

| Check | Under Bazel |
| --- | --- |
| the sanitizers | `--config=asan` (the default here), `tsan`, `lsan` built and passed; `tysan` written, not run |
| the leak check of the release build (`leaks --atExit`) | an `sh_test` wrapping each program under `--config=release`; not built |
| fuzzing | rules_fuzzing (registry 0.8.0) builds libFuzzer targets; not tried. The corpus replay is built |
| the C++ coverage gate | `bazel coverage` gives the per-group lines (built); the 95 % gate would be a script of ours on its lcov output |
| mutation testing (Mull) | a configuration passing Mull's plugin (`-fpass-plugin`) and a run of `mull-runner` on the programs; not tried |

## 9. Benchmarks and profiling: knowing which are due

Bazel never runs them: they stay a separate task Tomas starts on an idle
machine (ADR 0072). The question is whether Bazel can say which are due,
meaning their inputs changed since their last recorded run, as
`just benchmarks-due` does today.

**Partly, because** Bazel knows a benchmark's inputs but keeps no record of
a run it did not make. Today `validation/_bench.py` gives each benchmark an
identity (its script or program source, the identity of the C++ groups it
measures, the Python it times) and lists it as due when no record of a run
has it; the records (`bench-<name>`) hold each run's wall time, cores,
memory and load. Under Bazel a benchmark would be a target tagged `manual`
(so `bazel test //...` never runs it), and its identity could be an
action's output: a small rule of ours that hashes the target's declared
inputs (or the built program's bytes), cached and rerun only when they
change. The "due" step, comparing that identity with the recorded runs,
stays a script of ours, since the runs happen outside Bazel. Not tried.

## 7. Identical product

**No.** Our own targets get every flag of `warnings.cmake` and
`hardening.cmake` (C++23, the warnings as errors, no `-ffast-math`,
`-ffp-contract=off`, the dev and release flavours' options and libc++
modes); Apple clang by default and Homebrew LLVM by `--config=llvm`, with
ASan and UBSan, TSan, LSan and source-based coverage; and the one binary
inside one wheel. The differences from the CMake build:

| Difference | Where | Effect |
| --- | --- | --- |
| apple_support's toolchain adds `-fstack-protector -fcolor-diagnostics -Wall -Wthread-safety -Wself-assign -fno-omit-frame-pointer` to every compile | all targets | stricter or equal; `-fstack-protector` is weaker than release's `-fstack-protector-strong`, which comes after it and wins |
| `-O0 -DDEBUG` (fastbuild) before our `-O1` in dev; `-g0 -O2 -DNDEBUG` (opt) before ours in release | all targets | ours come later and win; `DEBUG` is defined in dev, which no source reads |
| `-D_FORTIFY_SOURCE=1` outside the sanitizer builds | third-party code in release | CMake gives theirs none; ours undefine it and set 3 |
| `--macos_minimum_os=15.0` | all targets | CMake leaves the SDK's own (macOS 27); apple_support's default, 10.11, is refused by libc++. 15 is ADR 0062's floor |
| the third-party libraries compile as `-std=c++17` (toolchain default) | cpptrace, RapidCheck, Catch2 | CMake: RapidCheck `gnu++11`; cpptrace and Catch2 get no `-std`, so the compiler's default (`gnu++17`) |
| `-D__DATE__="redacted"` and its kin, `-fdebug-prefix-map` | all targets | Bazel's reproducibility; none of our code reads them |
| other repositories' headers come in as `-isystem` through `--features=external_include_paths` | all targets | the same as CMake's `SYSTEM` property; without it Catch2's headers fail our `-Wunsafe-buffer-usage` |
| the sanitizers through the toolchain's `asan` and `ubsan` features | every target in dev | the same flags as `sq_flavor_everywhere`, with the feature's `-gline-tables-only` before our `-g`; the raw `--copt=-fsanitize` route collides with the toolchain's `_FORTIFY_SOURCE=1` |
| the toolchain's `-std=c++17` before our `-std=c++23` | our targets too | ours comes later and wins |
| `-fno-sanitize-recover=all` stays on every release compile; `-DNS_BLOCK_ASSERTIONS=1` (an Objective-C macro) in release | all targets | no sanitizer runs in release, and no source reads the macro |
| the toolchain's `-fno-omit-frame-pointer` in release | all targets | not stricter: frame pointers kept, a possible cost in speed the release flavour does not have under CMake |
| the must-not-compile cases' compiles (`compile_test.bzl`) take `--copt` but not `--per_file_copt` | those cases | they compile without `_LIBCPP_HARDENING_MODE`, which CMake's `sq_target_options` gives them |
| the DuckDB step gets apple_support's flags as `CMAKE_CXX_FLAGS_INIT`: `-D_FORTIFY_SOURCE=1 -fstack-protector -fno-omit-frame-pointer -Wall -Wthread-safety -O2 -DNDEBUG -DNS_BLOCK_ASSERTIONS=1`, the `__DATE__` redaction and `-fno-sanitize-recover=all` | DuckDB, duckdb-python, nanobind, the extension | the wheel's CMake build compiles them without these, so they are not the same compiles |

In the module and the wheel:

- the module's version line says `0+unknown` (the CMake step is given no
  sqlearn version; scikit-build-core gives CMake setuptools-scm's);
- undefined Python symbols are left to the loader with `-undefined
  dynamic_lookup`, where CMake gives nanobind's list
  (`darwin-ld-cpython.sym`);
- the module is linked as a dynamic library (`-shared`), not a bundle
  (`-bundle`), which Python loads alike;
- libc++'s fast mode reaches cpptrace, which the wheel compiles without it;
- the CMake step finds Python, numpy and nanobind 3.1.0 in the project's
  `.venv`, outside Bazel's inputs.

Left out of the build:

No flag of `warnings.cmake` or `hardening.cmake` was left out for our
targets. Left out of the build itself: the fuzz target's source, which
CMake compiles in every preset so it cannot rot (`engine/fuzz`; Bazel
builds only the replay); the headers-alone targets (`headers_alone.cmake`),
the bindings' among them, which the wheel's build compiles; and
`cpptrace.cmake`'s guard that fails the build if libdwarf or zstd is
configured. The `profile`, `debug`, `tsan`, `lsan`, `tysan`, `fuzzing` and
`mutate` flavours were not ported; the LLVM ones are under "Both compilers".

And under Homebrew LLVM: the `llvm-dev` preset's 15th test, `canary.lsan`
(the proof that the leak check is on), and the tsan, lsan and tysan
canaries are not ported; TypeSanitizer was not run.

Most rows could be closed with more configuration (the toolchain's
defaults by features, the version passed in, nanobind's list given to the
link); the DuckDB step's flags are the hardest, since rules_foreign_cc hands
the toolchain's flags to CMake.

## 8. What it would replace, and what it would add

Deleted, for the C++ and the wheel:

- `engine/CMakeLists.txt` and `engine/cmake/` (`groups.cmake`,
  `warnings.cmake`, `hardening.cmake`, `cpptrace.cmake`, `ccache.cmake`,
  `duckdb_package.cmake`, `headers_alone.cmake`, `toolchain-llvm.cmake`,
  `pins.cmake`, `build_identity.hpp.in`'s writer), the CMake files of
  `engine/tests/`, `engine/fuzz/` and `engine/bench/`, and
  `engine/CMakePresets.json` (each preset a `.bazelrc` config).
- scikit-build-core as the wheel's builder (`pyproject.toml`'s
  `[tool.scikit-build]`), by `py_wheel`; `uv sync` would install a wheel Bazel
  built.
- `validation/_ctest.py`, the CMake half of `validation/_groups.py` (the
  manifest, the fingerprints from `compile_commands.json`) and
  `validation/_checks.py`'s records for the `test` task's C++ part; the
  recipes that drive CMake (`build-engine`, `test-engine`,
  `test-engine-changed`, `sanitize`, `leaks-engine`, `coverage-engine`,
  `mutate-engine`, `fuzz`, `bench-engine`, `headers-alone`) would become
  one-line `bazel` calls.

Kept: the C++ and the Python; `just` as the one entry point (ADR 0008); the
submodules and their pins; uv for the environment; `_checks.py` for every
check not moved (format, lint, types, docs, links, until rules_lint and
rules_mypy take them); and the CMake build of DuckDB itself, run inside
Bazel. Not shown to move: clang-tidy, clangd and include-what-you-use
(they read `compile_commands.json`, which Bazel does not write), Mull,
libFuzzer, the SQL tests (DuckDB's `unittest`), the nanobench programs,
Linux and Windows.

Added, on the branch: `MODULE.bazel` (and its lock), `.bazelversion`,
`.bazelrc`, `.bazelignore`, a root `BUILD.bazel`, `engine/BUILD.bazel`,
`engine/bazel/` (`flags.bzl`, `identity.bzl`, `compile_test.bzl`,
`pins.bzl`, BUILD files for cpptrace, RapidCheck and duckdb-python, the
DuckDB step's `CMakeLists.txt`, the wheel's targets) and a `BUILD.bazel`
in each group, test directory and `engine/fuzz`. The knowledge they need:
Starlark rules (the build identity and the must-not-compile rule are two),
toolchains and their features (apple_support's defaults, rules_cc's local
toolchain for LLVM), configurations (`--config`, `--platform_suffix`,
`--per_file_copt`), Bzlmod and the registry, rules_foreign_cc, rules_python,
and how Bazel links (archives, `alwayslink`, `-force_load`). Each pitfall
the prototype hit is in "How the prototype was built" below.

## Recommendation

**Keep CMake with the home-made selection for now; move later if, once the
groups' test programs link static libraries, today's selection still reruns
tests whose inputs did not change or misses ones whose inputs did.** On Tomas's
aim, Bazel did as well as today's checks on items 1 and 3 and better on item 2
(a `core` change reran `core` alone, where today reruns `raw` and `crash` too),
and caught some undeclared reads where today catches none (item 5). But the
finer item 2 comes from how the test programs are linked, which CMake might
match (not tried); item 6 is shown for the C++ tests only: Bazel could select
clang-tidy, include-what-you-use, headers-alone, the type checkers and the SQL
tests more tightly than today, and its `layering_check` found two includes the
tests did not declare, but each of those needs rules not tried, and the Python
tests still depend on the whole binary; item 9 still needs our own record of
benchmark runs; and item 7 is not met: the library Bazel builds differs from
CMake's in the list above, DuckDB's part most of all. A move would trade a
selection that covers every check for one that covers the C++ tests well and the
rest only after more rules are written. The sign to move would be today's
selection failing Tomas's aim on its own, a missed rerun above all. The one
result that looked like one (item 2) was diagnosed and is not: those exact
bytes had passed before.

## How the prototype was built

The evidence for item 7, and the pitfalls, in the plan's order.

### The groups and their tests

**Yes.** `bazel test //engine/...` builds the three groups and runs every
test CTest runs in the `dev` preset, and all pass: 14 Bazel tests against
`ctest --preset dev -N`'s 14 (the three group programs, the eight
must-not-compile cases and controls, the two canaries, the corpus replay).
The Catch2 counts match program by program: `test_core` 18 cases and 76
assertions, `test_raw` 26 cases (one skipped, as under CMake) and 97
assertions, `test_crash` 18 cases and 66 assertions, the `[signals]` cases
included. `bazel test --config=release //engine/...` runs the same 12
outside the canaries (which, as in CMake, exist in the dev flavour alone),
and with `import_test` 13, and passes.

What it took (files on the branch):

- `MODULE.bazel`, `.bazelversion`, `.bazelrc`, `.bazelignore`;
  `engine/BUILD.bazel` (the flavour flag); `engine/bazel/` (the flags, the
  pins, the build identity, a compile test); one `BUILD.bazel` per group,
  per test directory and for `engine/fuzz`.
- Catch2 3.16.1 comes from the Bazel Central Registry: it is the pinned
  commit. **cpptrace and RapidCheck do not**: the registry's cpptrace
  1.0.4 compiles libdwarf (LGPL-2.1, never in what ships, ADR 0066) and
  unwinds with `execinfo`, which is not signal-safe, and its RapidCheck is
  2023.12.14, not the pinned commit of 2026-10-05. Both are built from
  their submodules with BUILD files of ours outside them
  (`engine/bazel/third_party/`), with the back-ends
  `engine/cmake/cpptrace.cmake` chooses (libdl symbols, libunwind on
  macOS). The globs give the same 45 cpptrace sources as its CMake list.
- `build_identity.hpp` is written by a rule that runs the toolchain's own
  compiler for its version: `AppleClang 21.0.0.21000401`, the string the
  CMake build writes.
- The must-not-compile cases have no Bazel equivalent of "this target must
  fail to build". A rule of ours (`engine/bazel/compile_test.bzl`) compiles
  the file in a build action that records the exit code, and the test reads
  it. Its first version passed every must-fail case for the wrong reason
  (`-fsyntax-only` beside the toolchain's `-c` is an unused-argument
  error); the controls failed, as they are there to, and caught it.

The flags and every difference from the CMake build are in item 7.

### Both compilers

**Yes, with three caveats.**

- **Apple clang is the default.** The default C++ toolchain is
  apple_support's (pulled in by rules_cc), whose `wrapped_clang_pp` runs
  `/usr/bin/xcrun clang++`; `bazel aquery` shows it, and the build identity
  it writes is `AppleClang 21.0.0.21000401`, as CMake's.
- **Homebrew LLVM is `--config=llvm`.** rules_cc's toolchain for a local
  compiler, with `CC` and `CXX` set to `/opt/homebrew/opt/llvm/bin/clang`
  and `clang++`, apple_support's set aside
  (`BAZEL_NO_APPLE_CPP_TOOLCHAIN=1`, and `BAZEL_USE_LEGACY_MACOS_TOOLCHAIN=1`,
  without which rules_cc configures no toolchain on macOS), chosen by
  `--extra_toolchains`, and the SDK through `SDKROOT` from
  `xcrun --show-sdk-path` (as `toolchain-llvm.cmake`'s `-isysroot`). The
  identity says `Clang 23.1.6`, and `otool -L` shows the test programs
  linked to Homebrew's `libc++.1.dylib` and its ASan runtime. All 14 tests
  pass under it, with `ASAN_OPTIONS=detect_leaks=1` as the `llvm-dev`
  preset sets; that preset has 15, its `canary.lsan` (the proof that the
  leak check is on) not ported.
- **Sanitizers on LLVM:** `--config=tsan` (ThreadSanitizer, the crash
  group's `[signals]` cases left out, 9 of its 18 cases run, as CMake's
  `tsan` flavour), `--config=lsan` (LeakSanitizer alone) and the default
  ASan with UBSan: each runs the four group and replay tests and passes,
  and `otool -L` shows each one's runtime linked. TypeSanitizer
  (`--config=tysan`) is written but was not run: its flavour builds the
  crash group without its tests, which the prototype's `sq_group` does
  not do. The canaries were ported for the dev flavour alone (ASan,
  UBSan); the `tsan`, `lsan` and `tysan` canaries were not.
- **Coverage:** `bazel coverage //engine/src/... //engine/fuzz/...` on the
  LLVM toolchain, at `-O0` with Clang's source-based instrumentation,
  `engine/src` alone instrumented, gives an lcov report
  (`bazel-out/_coverage/_coverage_report.dat`) with each file's lines, so
  per group coverage comes out: core 100 % (168 of 168 lines), raw 95.8 %
  (136 of 142), crash 91.7 % (200 of 218), the crash group's forked
  children writing their profile first through `SQ_COVERAGE`, as CMake
  sets it. It is lcov, not `llvm-cov report`'s regions and branches: that
  would need Bazel's raw profiles kept, which was not tried.

The caveats. First, both toolchains wrote the same output directory
(`darwin_arm64-fastbuild`), so a switch between `--config=llvm` and the
default recompiled everything (252 compiles after the switch back); with
`--platform_suffix` giving each LLVM configuration its own directory, a
switch back and forth runs nothing again ("Executed 0 out of 14 tests",
three switches in a row). Second, the LLVM toolchain reads `SDKROOT` from
the environment, which every command must export. Third, rules_cc's toolchain
repository records Homebrew LLVM's include directories by their versioned
path (`/opt/homebrew/Cellar/llvm/23.1.6/...`), so a `brew upgrade llvm`
needs it fetched again. A hermetic toolchain
(toolchains_llvm) would remove that, but it downloads its own LLVM rather
than using Homebrew's.

### DuckDB inside Bazel

**Yes, as one opaque step, with a cost.** `bazel build --config=release
//engine/bazel/duckdb` runs rules_foreign_cc's `cmake()` on a small CMake
project of ours outside the submodules (`engine/bazel/duckdb/CMakeLists.txt`),
which adds `engine/duckdb-python` as the wheel's build does (the official
four extensions, sqlearn's extension from `engine/extension`, the pins'
version and commit) and installs, in a component of its own, the archives
the module links (DuckDB, its zstd, httplib and extension loading, the five
extensions, nanobind's abi3 library, duckdb-python's binding objects as one
archive, the generated static extension loader) and one directory of the
headers the bindings compile against. It built, on the fourth try:

1. A glob crossed into packages of ours (Bazel globs stop at a package).
2. The extension failed with `_LIBCPP_HARDENING_MODE` redefined:
   rules_foreign_cc hands Bazel's `--copt` to CMake as `CMAKE_CXX_FLAGS`,
   where it meets `hardening.cmake`'s own definition. Bazel's
   everywhere-defines moved to `--per_file_copt`, which reaches Bazel's own
   compiles and not the CMake step.
3. `libduckdb_zstd.a` was not installed (named by hand afterwards).

What it costs:

- **Any change to a flag Bazel passes reruns the whole DuckDB build.**
  The step's inputs are its source tree (about 18 000 files) and the
  toolchain's flags; Bazel cannot see inside it, so it caches the step whole
  or not at all. Retries 1 and 2 each recompiled DuckDB from scratch. The
  CMake build has ccache under it (`engine/cmake/ccache.cmake`); the
  prototype's step does not set it up, and runs unsandboxed
  (`tags = ["no-sandbox"]`) so as not to link 18 000 files into a sandbox.
- The step finds Python, numpy and nanobind 3.1.0 in the project's `.venv`
  (`uv sync`), outside Bazel's inputs: not hermetic, as the wheel's build
  takes them from its build environment.
- The prototype's copy of the pins (`engine/bazel/pins.bzl`) duplicates
  `engine/cmake/pins.cmake`.

BUILD files of our own for DuckDB, the alternative the plan left out, were
not needed for a build; they would be what lets Bazel cache DuckDB per file,
and would mean keeping about 18 000 files' worth of build rules in step with
each DuckDB release.

### The one binary and the wheel

**Yes.**

- **The one binary.** `//engine/src/bindings:_duckdb.abi3.so` is one
  `cc_binary` (`linkshared`) that links every object of the groups (each
  group's `<name>_module` copy, `alwayslink`, so `-force_load`ed as
  `sq_add_to_module` puts every object in), the bindings and the CMake
  step's archives: `nm` shows `PyInit__duckdb` and
  `PyInit__native` in it, 55.6 MB against the CMake module's 53.8 MB. The
  bindings use the nanobind the CMake step builds (one nanobind in the
  binary, `NB_DOMAIN=duckdb`), so nanobind_bazel was not used: it would
  compile a second nanobind beside duckdb-python's. Two pitfalls on the
  way: duckdb-python's archive must be `-force_load`ed (nothing references
  `PyInit__duckdb`), and a `cc_import(alwayslink = True)` of it lost to the
  same archive reaching the link plainly, so the first link had no
  `PyInit__duckdb`. A fresh review found two more, fixed since: the groups
  reached the module as plain archives (only the objects something used),
  and the module's crash group carried `SQ_CRASH_TEST_HOOKS`, which CMake
  gives a preset's build alone. The groups' copies for the module
  (`<name>_module`) fix both; the package tests below were rerun on the
  fixed wheel.
- **The wheel.** rules_python's `py_wheel` builds
  `sqlearn-0+bazel-cp312-abi3-macosx_15_0_arm64.whl` with `sqlearn/`,
  `duckdb/` (its `_version.py` and `_build_info.py` generated as
  `duckdb_package.cmake` does), `adbc_driver_duckdb/`, `_duckdb-stubs/` and
  the one `_duckdb.abi3.so`.
- **It imports.** In a fresh uv environment (`uv venv`, then `uv pip install` of
  the wheel): `python -c "import sqlearn as sq; print(sq.version())"` prints
  `sqlearn 0+unknown, DuckDB 2.0.1 (8d78114e90), AppleClang 21.0.0.21000401, Release`,
  and `SELECT sqlearn_version()` gives the same line.
- **The package's tests pass.** The seven files of `tests/engine` that test
  the package rather than the CMake build (`test_bindings`,
  `test_bound_types`, `test_crash_report`, `test_extension`,
  `test_package`, `test_raw_layer`, `test_steady_memory`), run in the
  repository with that fresh environment's Python: 18 passed, 1 deselected
  (the slow tier), as with the CMake build in the project's environment.
  The other eight test the CMake build itself (presets, pins, tidy,
  sanitizers, coverage, the manifest) and would be rewritten for Bazel.
- **A `py_test`.** `//engine/bazel/wheel:import_test` runs on rules_python's
  own CPython 3.12 with the packages and the binary gathered into one
  directory, and passes. pytest was not brought into Bazel (rules_python's
  `pip.parse` and a lock of the test group would): the `tests/engine` run
  above is outside Bazel.

Differences from the wheel's CMake build: the module's version line says
`0+unknown` (the step is given no sqlearn version; scikit-build-core gives
CMake setuptools-scm's); undefined Python symbols are left to the loader
with `-undefined dynamic_lookup` where CMake gives nanobind's list
(`darwin-ld-cpython.sym`); libc++'s fast mode reaches cpptrace too, which
the wheel compiles without it; and the module links with `-dead_strip -x
-S` as CMake's, but as a dynamic library (`-shared`), not a bundle (`-bundle`),
which Python loads alike.
