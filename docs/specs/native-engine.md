---
type: spec
tags: [native-engine, cpp, duckdb, python-bindings, phase-0]
summary: "Spec for porting sqlearn to a C++ library embedding DuckDB with Python bindings, recording the approved decisions and specifying Phase 0."
related: [docs/architecture/overview.md, ADR 0002, ADR 0058, ADR 0019, ADR 0007, ADR 0010, ADR 0015, docs/questions/multi-engine-support.md]
mdindex: [type=d4f02e, tags=9edc37, summary=8d4d0f, related=841d68]
---
# Native engine: the decisions, and Phase 0

A new part of [the overview](../architecture/overview.md): sqlearn becomes a
C++ library that embeds DuckDB, and Python becomes a thin layer of bindings
over it, as Polars is Rust with Python on top. This spec records the decisions
Tomas made with an agent on 2026-11-21, each of which becomes an ADR, and
specifies Phase 0. Each later phase gets a spec of its own.

Status: approved by Tomas on 2026-11-21; revised and approved again the same day
(Tomas: "all pure C++", Python and any later language as bindings); the revision
rewrote §1, §2, §3.1, §3.8, §4 and §5.3, and added to §3.2, §3.4 (Mojo) and
§3.6. Phase 0 is [#78](https://github.com/glaucis/sqlearn/issues/78).

## 1. Purpose

- **All of sqlearn in C++** (Tomas, 2026-11-21): the pipeline, the steps,
  the SQL it builds, the learning store, the search, saving, exploration,
  metrics, and later sqlearn's own models and GPU kernels. Python keeps no
  logic of its own, only bindings. Tomas's reasons:
  - if sqlearn becomes popular, bindings for other languages (Rust, R or
    others) can follow, each a wrapper over the same core, written once;
  - one language is easier and more uniform than logic split between Python
    and C++;
  - everything else is wrapping.
- **One engine.** Everything that computes still runs inside DuckDB (ADR
  0002): the steps' learning, statistics, sqlearn's own models, and later GPU
  kernels. No data is copied out, except to an outside model the user chose.
- **C++, not Rust,** because DuckDB's internals (physical operators,
  optimiser rules, a GPU executor) and Apple's Metal API are C++, and one
  native language is wanted, not Rust now and C++ later.
- **To Python users nothing changes:** they install and import sqlearn
  instead of scikit-learn, and `sq.` keeps its API (scikit-learn style, used
  in notebooks). The bindings carry the bridge to Python things: outside
  models, Optuna, users' own steps written in Python, hand-overs to pandas,
  Polars and Arrow.
- **Apple silicon first.** A Mac gets everything the chip has: CPU cores, the
  matrix units, the GPU, unified memory. Every other platform gets a safe CPU
  build. Tomas: data preparation on Apple silicon, with unified memory, is one
  of the best setups there is, and its users miss out today.
- **Memory safety** is the main worry about C++, so the safety rules bind
  from the first commit (§3.6).

What there is today: 74 Python modules, about 31,500 lines with their
docstrings, and 27,400 lines of tests. Only the Gram learn sends data through
Python to compute something (ADR 0058); everything else already runs in DuckDB
as SQL that Python builds, and Python finishes a few numbers (F scores,
skewness, PCA's `eigh`). So the port rewrites the library's logic, the SQL
builder above all, rather than its computation, and the engine adds kernels
that SQL does badly (wide aggregates such as XᵀX), functions DuckDB lacks
(the distributions behind p-values, linear algebra), and sqlearn's own models.

## 2. What it looks like

```text
uv add sqlearn            installs sqlearn and sqlearn's DuckDB build together

sqlearn (C++)             the library: pipeline, steps, the SQL it builds,
                          store, search, saving, explore, metrics, models;
                          its kernels registered in DuckDB as `sqlearn_*`
sqlearn (Python)          thin nanobind bindings: `import sqlearn as sq`
sqlearn's DuckDB build    the `duckdb` module: DuckDB from its official
                          source and the extensions sqlearn needs; the
                          same DuckDB the C++ library runs in
later                     a C layer over the C++, for languages that need
                          one (R, Rust), and their bindings
```

```python
import duckdb  # sqlearn's build: one DuckDB, shared with the C++ library
import sqlearn as sq

sq.version()  # answered by the C++ library (Phase 1)
pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(n_components=3)])
pipe.learn("big/*.parquet")  # one call into C++; XᵀX built inside DuckDB
```

```sql
-- the SQL sqlearn generates stays readable (ADR 0002)
SELECT sqlearn_gram([a - 1.5, b - 2.0, c - 0.3]) FROM data
```

## 3. Decisions

Each subsection becomes one ADR; the numbers are proposed. "Considered" names
what was weighed and why it lost.

### 3.1 sqlearn is a C++ library; Python is its bindings (ADR 0060; amends 0002)

- **The library is C++**, embedding DuckDB and written against DuckDB's
  internal C++ API. That API changes between releases, so sqlearn is built
  for one DuckDB version; Tomas accepts the exact pin and an upgrade per
  release (§3.2). Its kernels (XᵀX, the distributions, later the models and
  GPU kernels) are registered in DuckDB as functions and run inside its
  queries; the C++ library builds the SQL that calls them, as the Python
  does today.
- **Python is a thin layer of bindings**, written with nanobind (BSD-3): the
  lowest per-call cost of the C++ binding tools, smaller and faster to build
  than pybind11, by the same author; zero-copy numpy and Arrow arrays; and
  CPython's stable ABI from 3.12, so one build serves every Python from our
  floor (ADR 0007). DuckDB 2.0's own Python module is built with it. The
  bindings hold no logic: they convert arguments, hand Python objects
  (outside models, Optuna, users' own steps, data frames) to the C++ through
  interfaces the C++ defines, and keep `sq.`'s names, docstrings and errors.
  A call such as `learn` crosses into C++ once, never once per row.
- **The one seam to Python steps** (the agent's call): a step written in
  Python, built from DuckDB's Python expressions (today every step is; ADR
  0019 inspects an undeclared one by calling its `apply`), reaches the C++
  compositor through one interface the C++ defines: the bindings call the
  Python step's methods and hand its expressions over as DuckDB expressions,
  which cross unchanged because there is one DuckDB (§3.2). That seam lets
  the core be ported first while the built-in steps are still Python, and
  stays afterwards for the users' own steps: users keep writing their own
  steps in Python after the port (Tomas, 2026-11-21), and those run as fast
  as today, while sqlearn's own steps are C++.
- **Other languages bind later, when wanted** (Tomas, 2026-11-21): Python
  binds the C++ directly now. A small C layer over the C++ comes when a
  language that needs one (R, Rust) is wanted, and each such language binds
  that layer. Nothing in the C++ is rebuilt for it: the C layer sits on top.
- **The C++ API is internal** (Tomas, 2026-11-21): only Python's `sq.` is
  public, and the C++ names may change at any time until sqlearn is done,
  tested and verified. Publishing a supported C++ API, with stable names,
  documentation and versions, is a later ADR ("better to be safe than let
  users down").
- Its SQL functions start with `sqlearn_` (fewer collisions later, and plainly
  sqlearn's in the generated SQL); identifiers use American spelling (ADR
  0010).
- It lives in this repository, under `engine/`: one version, one CI, one
  HANDOFF.
- **Inside sqlearn, speed comes first** (Tomas, 2026-11-21): a trained
  pipeline's apply and predict SQL may call the engine's functions wherever a
  benchmark shows them faster, not only where plain SQL cannot do the job.
  Two things keep other engines possible later, with nothing for them written
  now:
  - each engine function used in apply keeps a plain-SQL twin where one
    exists (its tests compare the engine against it anyway), so sqlearn can
    still show or export SQL that runs in any DuckDB; a pipeline whose apply
    has no twin says it needs sqlearn's DuckDB;
  - the compositor stays the one place SQL is rendered (ADR 0015), so a
    translator (sqlglot or another) can plug in there for a later
    `engine="postgresql"`
    ([questions/multi-engine-support.md](../questions/multi-engine-support.md)).
- Amends 0002: computation stays inside DuckDB, and sqlearn's functions
  join DuckDB's own; the glue that builds the SQL and finishes a few numbers
  is C++ instead of Python. The generated SQL can always be inspected; it runs
  in any DuckDB where its plain twin exists.
- Considered:
  - C++ only for the heavy parts, called from SQL that Python builds (this
    spec as first approved): two languages holding logic, and every other
    language would need the Python rewritten.
  - Bindings only at the end, the C++ tested by C++ ports of the tests: a
    difference from today's answers shows up only at the end, across the
    whole library, and the tests are written twice (Tomas chose bindings
    from the start, 2026-11-21).
  - A C layer from the start: more work now for languages not yet wanted.
  - pybind11 (higher call cost, larger builds), Cython (a third language),
    CPython's C API by hand (much code, easy to get wrong).
  - DuckDB's stable C API (one build loads into later DuckDB releases, but
    functions only, no operators or optimiser rules, and its template is
    marked experimental); Rust (a second native language later).

### 3.2 sqlearn's own DuckDB build (ADR 0061; amends 0005, 0006, 0057)

- sqlearn bundles its own DuckDB, built from the sources of DuckDB and of its
  Python package at a release tag: git submodules, never a fork, so an upgrade
  is a tag change. The engine and the extensions sqlearn needs are compiled
  in: today `core_functions`, `parquet`, `json` and `icu`, as in the official
  build (checked on 2.0.0), and later what sqlearn needs.
- **It installs as the `duckdb` module**, in place of the official package (a
  "drop-in"). Users' code, sqlearn's code and the tests keep `import duckdb`
  and get one DuckDB, shared. The official package cannot be installed beside
  it, since both are the `duckdb/` folder; in sqlearn's own environment
  nothing else needs it (checked with `uv tree --invert`).
- **It ships as a second package**, installed by the same `uv add sqlearn`
  (name chosen in Phase 1; `sqlearn-duckdb` is a placeholder). sqlearn
  requires its exact version. A change to sqlearn then ships without
  rebuilding DuckDB. Shipping both in one package instead holds the identical
  program, so it would not be faster.
- **One DuckDB in the process** (added by the revision): the `duckdb` module
  and sqlearn's C++ library must run in the same DuckDB, so that a user's
  connection (`sq.set_config(connection=con)`) and the data frames they hand
  in reach the C++ as they are, and the C++ is handed the C++ connection
  behind the Python one. Two copies of DuckDB linked into two binaries would
  be two databases that cannot see each other's data. Phase 1 decides how:
  both packages linking one shared DuckDB library, or the C++ library
  compiled into the DuckDB build's package. If the second, the two packages
  become one, and the reason above for two lapses; §2 and Phase 1 name two
  packages only as the default.
- **At start, sqlearn checks that `duckdb` is its build** (the engine
  answers). If another package has replaced it with the official one, sqlearn
  refuses with its `Why:` and `Fix:` lines.
- **Accepted cost** (Tomas: "who needs 2 installs of duckdb?"): a package that
  needs the official `duckdb` (dbt-duckdb, Ibis, jupysql, sqlmesh, dlt and
  others) cannot share an environment with sqlearn. The installer puts both in
  without a conflict; they overwrite each other's files, and removing either
  breaks the other. The start-up check catches the case where the official
  one won; its `Fix:` says to reinstall sqlearn's DuckDB, and that such a
  package needs an environment of its own for now. Ways round, if users ask:
  the same build also served under the name `duckdb` with a local version
  (`2.0.1+sqlearn.1`) from sqlearn's own package index, as PyTorch serves its
  CUDA builds (never on PyPI), or an override in the user's own uv project.
- **Pinned to one DuckDB release**, 2.0.1 first (a long-term-support line, to
  at least October 2027). Each new release gets an upgrade branch: read the
  release notes and the changes in what sqlearn uses (the C++ headers the
  engine includes, the Python API sqlearn calls), move the pin, rebuild, run
  `just verify` and the benchmarks before and after, and re-test each DuckDB
  workaround sqlearn carries. Each workaround gets a canary test that fails
  the day DuckDB fixes it and names the workaround to delete. A `just` recipe
  lists the DuckDB releases newer than the pin.
- **Nothing downloads by itself.** The official build installs and loads
  extensions from the network when a query needs one
  (`autoinstall_known_extensions` is on); sqlearn's build turns that off and
  compiles in what sqlearn needs (amends 0006's consequences).
- **A user may still install an extension by asking for it** (`INSTALL
  spatial`, or httpfs for `s3://` files, excel, iceberg; Tomas, 2026-11-21):
  they chose it, and nothing sqlearn does needs the network (ADR 0006). Phase
  1 tests that DuckDB's official extensions load and work in sqlearn's build,
  which is compiled differently; one that fails is refused with a `Fix:`
  until it works.
- **A user's own DuckDB is not supported**, and is added only if users ask:
  then the same engine is also built as a loadable extension for the official
  package, which needs an exact version match and signing (DuckDB 2.0's
  repositories trusted with a publisher's own key, to be tested then).
- **Runtime dependencies** (amends 0005 and 0057): sqlearn's DuckDB build
  replaces `duckdb` from PyPI. numpy stays until the engine's linear algebra
  (Phase 3), when ADR 0057 is decided again.
- Considered:
  - The official DuckDB with the engine loaded into it. That needs signing
    (`allow_unsigned_extensions` can only be set when a database opens; the
    community build needs a public repository and follows only DuckDB's
    latest release) and a version match with whatever DuckDB the user has.
  - Our build under a private name inside sqlearn: two DuckDBs in one
    process, data that cannot cross between them, and 42 test files to
    change.
  - One package holding both: every Python fix ships DuckDB again.

### 3.3 Platforms (ADR 0062)

- **Apple silicon first:** macOS 15 or later on Apple silicon (M1 onwards)
  gets the tuned build. Apple-only, granular optimisations are welcome
  wherever a benchmark proves the gain and the tests prove the same answers:
  compiler settings for Apple's chips, link-time and profile-guided
  optimisation, Accelerate on the matrix units, Metal kernels, and DuckDB
  allocating page-aligned memory so the GPU reads its columns in place.
- **Every other platform gets the safe default CPU build:** Linux x86_64 and
  arm64 (glibc) and Windows x86_64 and arm64. Intel Macs get none (DuckDB's
  own extension builds treat them as best-effort in 2.0 and drop them in
  2.1). Nor does musl Linux (Alpine) for now: DuckDB itself ships no musl
  build, and the sanitizers do not support it; it comes when users ask
  (Tomas, 2026-11-21). The safe build still takes general optimisations:
  full compiler optimisation, link-time optimisation, and faster
  instructions (AVX2 or AVX-512 on x86_64) chosen at run time where the
  running processor has them. The condition is Apple's: a benchmark proves
  the gain and the tests prove the same answers (Tomas, 2026-11-21).
- **Why Apple silicon leads (Tomas, 2026-11-21):** it is the priority above
  all, with maximum optimisation and speed, because he uses it. Accuracy is
  never traded for speed: no `-ffast-math`, because a machine learning
  library has to be exact.
- **One ready-made build per platform** serves every Python from 3.12, on
  CPython's stable ABI as DuckDB's own wheels are (`cp312-abi3`; ADR 0007
  unchanged). CI builds them and attaches them to GitHub Releases. PyPI comes
  later, once sqlearn runs (Tomas: no unready product goes out). On a
  platform with no ready-made build, installing compiles from the source
  package; users need no script of their own.
- **GPU: Apple only for now.** NVIDIA, AMD and others come when someone asks
  and they can be tested.
- The repository is public (Tomas, 2026-11-21), so CI runs free on every
  platform, and code scanning of the C++ is free too.
- Considered: macOS 14 (Accelerate's per-thread setting needs macOS 15, so a
  second code path); macOS 26 (leaves out companies a year behind); scripts
  that compile on the user's machine (a C++ compiler and a long build for
  every user).

### 3.4 Compute libraries (ADR 0063; answers questions/engine-compute-libraries.md)

- **float64 runs on the CPU, everywhere.** On macOS: Accelerate's BLAS,
  LAPACK (3.12, with 64-bit indices) and vForce (`exp`, `log`, `expm1`,
  `log1p`, `pow` over arrays), single-threaded inside each DuckDB thread
  (`BLASSetThreading`, macOS 15+). Elsewhere: OpenBLAS (BSD-3).
- **Special functions** (`erf`, the incomplete gamma and beta functions): the
  C library, Boost.Math (BSL-1.0, header-only, tested first), or our own,
  each validated against mpmath. Never Numerical Recipes' code, whose licence
  forbids it.
- **No MLX.** Measured on the M3: its float64 runs on the CPU only, and there
  its `exp` and `erf` are computed in float32 (`exp(1.0)` 1.86e8 ULPs off,
  `exp(100)` infinite); its GPU built XᵀX of 400,000 × 200 in 36 ms against
  Accelerate's 19 ms, both in float32; its kernels weigh 214 MB.
- **GPU kernels are written in Metal**, through metal-cpp (Apache-2.0), and
  compiled ahead of time into a `.metallib` (Xcode's Metal toolchain on the
  build machine), with binary archives for the chips we know, so nothing
  compiles at start. Without an archive the first use of a kernel took 44 ms
  and later uses 0.5 ms (measured on the M3). Kernels use only what every
  Apple GPU has, from the M1; per-chip variants or tuning are chosen at run
  time, each where a measurement shows it pays.
- **Mojo is tried beside Metal** when the GPU kernels are benchmarked (Phase
  6, #77; Tomas, 2026-11-21). Mojo 1.0 (August 2026) is open source under
  Apache-2.0 with LLVM exceptions, compiler included, and compiles GPU
  functions for Apple silicon to the same intermediate form as Metal (AIR).
  It also compiles the same kernel for NVIDIA and AMD GPUs, so one source
  could serve every GPU sqlearn supports later, with no second and third
  version to maintain (Tomas, 2026-11-21); NVIDIA's GPUs have float64, which
  Apple's lack. **If Mojo matches Metal on Apple silicon, Mojo becomes the
  language of sqlearn's GPU kernels**, and Metal stays only where Mojo falls
  short. Phase 6 decides it, by testing, against these conditions, all
  measured:
  - as fast as the Metal version on Apple silicon, within the run-to-run
    spread;
  - answers bit for bit the CPU's (§3.5), on each GPU it runs on;
  - compiled ahead of time, with nothing compiled at start and no runtime
    added beyond what the kernels need;
  - callable from the C++ library through a plain C interface;
  - everything that ships under it permissive (ADR 0066).

  Otherwise C++ and Metal stay the native languages, as §1 wants. Either way
  the GPU stays Apple's only until another vendor's can be tested (§3.3).
- **No `-ffast-math`** anywhere, since it swaps in less accurate routines;
  Metal kernels compile in safe math mode (Metal's default is fast).
- Considered: MLX (above); cross-platform GPU layers (WebGPU, Vulkan, SYCL,
  Halide, IREE: float32 in practice, no linear algebra, some compile at run
  time); Eigen (MPL-2.0); JAX and XLA (compile at the first call, and
  Python).

### 3.5 When the GPU runs (ADR 0064; amends 0046)

- On Apple silicon, a kernel runs on the GPU by itself when its answer is bit
  for bit the CPU's and the job is above the kernel's measured size;
  otherwise it runs on the CPU. Apple GPUs have no float64 at all (Metal
  Shading Language 4.1, §2.1).
- Can meet the rule: counts, histograms, sorting and ranking (float64 keys
  sorted by their bits), fixed-point sums and means, naive Bayes fitting,
  boosting histograms. Cannot: `eigh`, solve, `exp` and `log`, k-means
  distances in floating point. Those stay on the CPU; a float32 GPU version
  runs only when the user asks for it (`sq.set_config(...)`), with bounds of
  its own.
- The user can see which device ran, and force one.
- The tests require exact equality between a kernel's CPU and GPU versions.
- Each kernel's size threshold comes from benchmarks
  ([#77](https://github.com/glaucis/sqlearn/issues/77)).
- Amends 0046: choosing the device when the answer is identical is not
  "changing the method"; anything that changes the answer still needs the
  user's choice.
- Considered: opt-in for everything (ADR 0046 as it stands: most users would
  never get the speed); the GPU always (answers would change with the
  machine).

### 3.6 Safety rules for the C++ (ADR 0065)

Binding from the first commit.

- **Coding:** the C++ Core Guidelines. No raw `new` or `delete`
  (`unique_ptr`, RAII); `std::span` and `std::vector`, never C arrays. Raw
  memory (DuckDB's vectors, Metal buffers) lives only in one thin, named
  layer, reviewed hardest.
- **Compiler:** `-Wall -Wextra -Wconversion -Werror`, and the MSVC
  equivalent. No `-ffast-math`.
- **Static analysis:** clang-tidy (`bugprone-*`, `cppcoreguidelines-*`,
  `performance-*`) and the Clang static analyser in CI; a finding fails the
  build.
- **Hardened standard library** (libc++ hardening, or `_GLIBCXX_ASSERTIONS`)
  in every build, release included, unless a benchmark proves a cost and an
  ADR accepts it. Phase 1 measures the cost; Tomas rules.
- **Sanitizers on every CI run:** AddressSanitizer with
  UndefinedBehaviorSanitizer, and ThreadSanitizer as a separate run, wherever
  the tools exist: all three on Linux (glibc) and macOS, AddressSanitizer on
  Windows (MSVC has no others). The same code is sanitized there, and every
  other build is built and tested (the agent's call).
- **Fuzzing:** libFuzzer on each function's pure core (random, NaN, ±inf,
  empty and huge inputs), in CI.
- **C++ tests** of the C++ library's internals, beside the Python tests that
  check its behaviour (§3.8); the framework is Phase 1's choice (a permissive
  one, ADR 0066).
- **SQL-level tests:** DuckDB sqllogictest files for every function.
- **Numerics:** the ADR 0016 method (exact values from mpmath or `Fraction`,
  bounds in ULPs per ADR 0043), run from Python against the built engine.
- **No crash reaches the user:** every entry point catches exceptions and
  returns a DuckDB error worded with sqlearn's `Why:` and `Fix:` lines.

### 3.7 Licences (ADR 0066; amends 0004)

- Runtime code may carry any permissive licence the Open Source Initiative
  approves: MIT, BSD, Apache-2.0, PSF, Boost, zlib, Unicode, ISC. Never
  copyleft. A library offered under a choice takes the permissive one (zstd:
  BSD; mbedtls: Apache-2.0).
- A third-party file lists every compiled-in library with its version,
  licence and licence text. `NOTICE` arrives with the first build that ships
  third-party code (Phase 1), keeping each library's notices and marking any
  file sqlearn changed, for example code adapted from Sirius (Apache-2.0).
- What DuckDB 2.0.0 brings (read from its source package): 26 libraries that
  ship, plus ICU. MIT 13, BSD 6 (jemalloc on Linux only), Apache-2.0 5, Boost
  1, zlib 1; Catch and the IMDB data are test-only. Where ICU's source comes
  from in 2.0, and its exact licence, Phase 1 confirms.
- Considered: keeping ADR 0004's four licences, which would rule out bundling
  DuckDB as it is.

### 3.8 How the library is rewritten (ADR 0070, superseding 0067)

Revised 2026-11-27 (Tomas): ADR 0067 ported the library under its Python
tests, unchanged; ADR 0070 replaces that with a rewrite.

- **The whole library is rewritten in C++**, one group of the inventory
  (§5.3) at a time, in its order, each group designed for C++ rather than
  translated from the Python. At the end no library logic is left in
  Python, only the bindings and the seam for users' own steps (§3.1). Each
  phase has its own spec, plan and branch in a worktree, and Tomas merges
  it; `main` stays green, and `just verify` passes on it after every merge.
- **The Python library is frozen:** no new features, fixes only where a bug
  blocks the work.
- **A group's gate:** its C++ tests pass, every validation runner it touches
  passes (ADR 0016), and its benchmark, on the same data and machine with
  the load recorded, is not slower than the Python it replaces (a difference
  within the run-to-run spread of two runs counts as not slower). In the
  same merge its Python is deleted with every test of it.
- **Tests:** behaviour inside the library is tested in C++, behaviour seen
  through `sq.` in Python against the bindings. A Python test is kept,
  changed or deleted on its merits; tests of a deleted Python internal are
  deleted, not rewritten. Each group's spec lists the tests it deletes and
  adds.
- **The `sq.` API may be improved before `1.0.0`** in the commit that needs
  it, recorded in `tests/public_api.txt`, the docs and the changelog; a
  departure from scikit-learn's conventions still needs an ADR (0003).
- **Saving:** files saved before the rewrite need not load after it.
  `sq.load`'s security rules hold in C++ (a static class lookup; values reach
  exact arithmetic only as plain numbers), and the saving group gets a
  whole-branch security review of its own, as #55 and #65 did.
- **Users' own steps:** see §3.1.
- **What stays Python:** the bindings, the seam for users' steps, and the
  development tools, none of which ship: the validation that compares sqlearn
  with scikit-learn (itself Python), the benchmarks, `devdata/` and the
  checks.
- **Measure honestly,** by HANDOFF's rules: `uptime` before and after, one
  probe per subprocess, large data written as Parquet with `COPY`, peak memory
  read twice.

### 3.9 sqlearn's own models (ADR 0068; amends 0017)

- sqlearn's own models become a goal: trained inside DuckDB on data larger
  than memory, with no hand-over, and predicting in plain SQL where the model
  allows. Outside models stay supported, and the hand-over stays.
- The order, one spec each: linear and ridge regression (gram plus solve;
  predict is one SQL expression), logistic regression (IRLS passes), k-means,
  naive Bayes, histogram gradient boosting. Each is validated against
  scikit-learn (ADR 0016) and benchmarked against it on the same data. Prior
  art first: Apache MADlib (Apache-2.0) and LightGBM's histogram algorithm.
- Replacing Optuna and the outside models with sqlearn's own is a later
  choice, and needs no C++: a search's cost is its trials' training.

### 3.10 ADRs checked and unchanged

0001 (uv: the DuckDB build is a uv workspace member, built with
scikit-build-core), 0003, 0007 (stable-ABI builds keep the 3.12 floor), 0008
(new recipes, same runner), 0009 (Pages, now from the public repository; ADR
0062 adds an Amended-by line), 0010, 0015 (our build has the same Python
expression objects; once the compositor is ported, it is the one place SQL
is rendered in C++), 0016, 0043 (order-free exact sums noted as a later option,
about 6 times the cost of XᵀX), and 0058, which Phase 2 supersedes, not Phase 0.

## 4. The phases

| Phase | What | Done when |
|---|---|---|
| 0 | This spec: the decisions as ADRs, the inventory (the port's order), the backup, the issues | §5 |
| 1 | sqlearn's DuckDB build, the C++ library's skeleton and its Python bindings, CI | `sq.version()` answers from the C++ on every platform's build, one DuckDB in the process, the safety stack runs in CI |
| 2 | `sqlearn_gram`, and PCA's learn on it | its C++ tests and `validate_pca` pass, not slower, numpy Gram path removed |
| 3 | Numeric functions | each function validated against mpmath; PCA's `eigh` in C++ |
| 4 | The rest of the library, in the inventory's order, one spec per group | each group's gate passes (§3.8) and its Python is deleted; no library logic left in Python |
| 5 | sqlearn's own models, one spec each | each validated and benchmarked against scikit-learn |
| 6 | Apple GPU kernels | one kernel at a time, each faster where it runs (#77) |

- **Phase 1:**
  - `engine/` with DuckDB and its Python package as submodules at 2.0.1, built
    as sqlearn's DuckDB (scikit-build-core, stable ABI);
  - the C++ library's skeleton in the same DuckDB (§3.2's "one DuckDB in the
    process"), with nanobind bindings: `sq.version()` answered from C++ in a
    test, a user's connection passed through to C++, and the start-up check;
  - no automatic downloads;
  - the safety stack in CI on every platform;
  - ready-made builds from CI;
  - `just` recipes (`build-engine`, `test-engine`) folded into `just check`,
    `just test` and `just verify`;
  - the checks redesigned for two languages and for speed (Tomas, 2026-11-21): a
    test reruns only when something it depends on changed (its code; a change it
    now meets, as when a merge to `main` combines two; a declared dependency the
    selection cannot see, such as the native module, `uv.lock`, `devdata/` or
    the test settings; or a new place to run: another Python, platform or DuckDB
    build). So only the checks a change affects run (each check selected by its
    inputs' digests, Phase 1 spec §3.1; CTest for C++), in parallel, and none
    for a docs-only commit; a push runs no full suite, and a fast-forward merge
    of a tree that passed runs nothing more. The full suite, on every Python and
    platform with the sanitizers, the docs build, and the validation run only at
    a release. Validation runners record their verdicts with the code they
    covered and rerun when it changes. `just` stays the one entry point, calling
    CMake (with Ninja, ccache and presets) for the C++;
  - the libraries sqlearn and its tooling use reviewed, kept or replaced
    (Tomas, 2026-11-21);
  - how the C++ is documented: comments in Doxygen's format, the site staying
    on Sphinx (Breathe if the internals are ever published);
  - the third-party file and `NOTICE`;
  - our build benchmarked against the official one on sqlearn's benchmarks,
    and the hardened standard library's cost measured.

  With CI in place, the site's deploy can follow
  ([#4](https://github.com/glaucis/sqlearn/issues/4),
  [#6](https://github.com/glaucis/sqlearn/issues/6)).
- **Phase 2:**
  - XᵀX and Xᵀy of centred columns as a parallel aggregate: Accelerate on
    macOS, OpenBLAS elsewhere;
  - PCA moved onto it;
  - benchmarked against
    [gram-streaming](../benchmarks/gram-streaming.md) and
    [gram-batches](../benchmarks/gram-batches.md) on the same data;
  - the numpy Gram path removed (ADR 0058 superseded).
- **Phase 3:**
  - the normal, t, chi² and F distribution functions;
  - small linear algebra: solve, inv, cholesky, `eigh`;
  - average ranks for Spearman, if profiling still shows them a cost.

  It unlocks the p-value selectors (`SelectFpr`, `SelectFdr`, `SelectFwe`),
  a 3.3 area of their own, and settles numpy's place (ADR 0057).
- **Phase 4:** the rest of the library, in groups from the inventory, each
  with its own spec: for example the expression and naming layer, the
  compositor and planner, the step framework and the steps, the store,
  saving, explore, metrics, model selection, and the hand-overs to Python
  libraries through the bindings. Its specs may split it into several
  numbered phases.
- **Phase 6** may start sooner for one kernel a model needs (boosting's
  histograms in Phase 5), if the evidence says so.
- **After the port:** the C layer and other languages when wanted (§3.1),
  and the decision to publish a C++ API.

**The order of work** (Tomas, 2026-11-21): the port comes first, planned from
start to end over sqlearn's whole current state, and done group by group with
`main` green. From Phase 1 all of sqlearn's SQL runs in sqlearn's DuckDB build
and the Python package loads the C++ library's bindings, calling the C++ for
each group already rewritten and the frozen Python for the rest; Phases 2 to 4
rewrite the library (ADR 0070); the inventory (§5.3) is the port's full map,
module by module. Before Phase 1, HANDOFF's three small queued fixes land (the
one-line `profile` fix, #75, #76; the agent's call). New library areas wait
until the port is done, and work that needs an engine function (p-values,
normality tests) waits for the phase that brings it.

## 5. Phase 0's deliverables

### 5.1 The backup

Before any engine work, the branch `main_python` and the annotated tag
`python-final` at `main`'s tip (`ca2b720`, pure Python), pushed with `main`
on Tomas's word (2026-11-21).

### 5.2 The ADRs

ADRs 0060 to 0068 as in §3, each with an "Amended by" line added to every ADR
it amends (0002, 0004, 0005, 0006, 0009, 0017, 0046, 0057), and grouped in
`docs/adr/index.md` under a topic of their own. The revision rewrites 0060 and
0067 in place, since neither has reached `main` yet (the agent's call): a
superseding ADR on their first day would only add a record of a draft. It
also updates, as they follow:

- ADR 0061 (one DuckDB in the process, and the second package as the
  default), 0065 (the C++ tests) and 0068 (models in Phase 5);
- `CLAUDE.md`'s rules from 0060 and 0067, the overview (§2, part 3.10 and
  its "done when", the models' phase in §3.3), `GLOSSARY.md` (the engine,
  sqlearn's C++ library, the bindings) and `layout.md`;
- the GitHub issues (§5.5);
- plan 0b's inventory task, for §5.3's new columns.

### 5.3 The inventory

`docs/architecture/engine-inventory.md`, the port's map: every module of
`src/sqlearn`, with:

- the **phase** that ports it (2, 3, or 4 with its group), and the C++ that
  replaces it: a kernel (`sqlearn_gram`), a numeric function, or a part of
  the C++ library;
- what **stays in the bindings** from it, if anything: the `sq.` names and
  docstrings, and the bridge to Python objects (outside models, Optuna,
  users' own steps, data frames);
- what it **depends on** among the other modules, since a module is ported
  after what it calls, or the bindings carry the seam between them;
- the **evidence**: the profiling page's numbers, where there are any.

The draft order, to be confirmed by the dependencies and the profiling:

| Area | Modules | Ported in |
|---|---|---|
| The Gram learn | `_gram.py` | Phase 2: `sqlearn_gram` |
| PCA | `decomposition/pca.py` | its learn with the Gram learn (Phase 2), its `eigh` (Phase 3), the rest in Phase 4 |
| Feature scores | `feature_selection/_scores.py` | Phase 4; gains p-values from Phase 3 |
| The core | `_pipeline`, `_compose`, `_plan`, `_step`, `_store`, `store`, `_inputs`, `_selectors`, `_names`, `_expr`, `fn`, `agg/*`, `_group`, `_config`, `_diagnose`, `_errors`, `errors`, `_output`, `out` | Phase 4, first: everything else builds on it |
| Steps | `preprocessing/*`, the rest of `feature_selection/*` | Phase 4, after the core; an exact median that spills (`quantile_cont` does not) is a kernel candidate |
| Exploration | `explore/*` | Phase 4; Spearman's ranks and `profile`'s moments become kernels if the profiling shows a cost; `histogram`'s counts are a GPU candidate (Phase 6) |
| Metrics | `metrics/*` | Phase 4 |
| Model selection | `model_selection/*` | Phase 4; Optuna stays Python, reached through the bindings |
| Hand-overs | `_feed`, `_model`, `_memory` | Phase 4; the Python side of a hand-over stays in the bindings |
| Saving | `_saving/*` | Phase 4: the same JSON, so files saved before the port still load |

The profiling, at the least:

- the Gram learn (PCA) at 50, 200 and 500 columns of 1,000,000 rows;
- Spearman correlations at 50 and 200 columns;
- the widest steps' learn at 200 and 500 columns: `scale.standard`,
  `impute.median`, `select.variance` and `explore.profile`.

For each: wall time, peak memory (read twice), where DuckDB spends the time
(its per-operator profile), and Python's share (cProfile), with `uptime`
before and after. The profiling measures `main` as it stands; Spearman's
numbers are labelled as taken before #75 changes its first scan (the agent's
call). The numbers go on a benchmark page
(`docs/benchmarks/engine-profile.md`, with its script under
`validation/benchmarks/`) that the inventory cites.

### 5.4 The research

[`docs/questions/engine-compute-libraries.md`](../questions/engine-compute-libraries.md):
the three research reports of 2026-11-21 merged, with their sources and the
measurements on the M3. It is committed as ADR 0063's evidence and marked as
answered by it.

### 5.5 GitHub

- The milestone "Native engine" (created on 2026-11-21).
- One issue per phase, 0 to 6, on the board: #78 to #84, each blocked by the
  one it follows (Phase 6 by Phase 1). The revision retitles three of them:
  #79 (sqlearn's DuckDB build, the C++ library's skeleton and its Python
  bindings), #82 (Phase 4: the rest of the library ported) and #83 (Phase 5:
  sqlearn's own models, from the old Phase 4); the old Phase 5, the pipeline
  compiler in C++ for non-Python clients, is now part of Phase 4.
- [#77](https://github.com/glaucis/sqlearn/issues/77) as a sub-issue of
  Phase 6's issue, #84.

### 5.6 The docs

- **The overview:** a new part, 3.10 Native engine, with its place in §4.
  §2's constraints change: Python, C++ and DuckDB; sqlearn's own DuckDB build;
  the widened licences; the public repository.
- **`CLAUDE.md`:** the rules from the new ADRs, changed in the same commit as
  the ADRs, and the paragraph saying what is done and what is next.
- **`HANDOFF.md`.**
- **`docs/architecture/layout.md`:** `engine/`, and `.github/` arriving with
  Phase 1.
- **`docs/questions/site-hosting.md`:** answered (the repository is public,
  and the site goes on Pages), so its answer moves where the convention says.
- **`GLOSSARY.md`:** the terms the ADRs settle, such as the engine, a kernel,
  and sqlearn's DuckDB build.

### 5.7 How it is done

On its own branch in a worktree, merged by Tomas. `just verify` passes on the
branch; `HANDOFF.md` is updated in the merge; Phase 0's issue closes.

## 6. Not in this spec

Phase 1's code and every later phase; the exploration app's front end
([questions/application-front-end.md](../questions/application-front-end.md));
the workflow editor; replacing Optuna; PyPI; GPUs other than Apple's; the C
layer, other languages' bindings, and a public C++ API; the review of the
docs, after the port, when they describe what exists.

## 7. Left to the builder

- The ADRs' titles and wording, within §3.
- The inventory's layout.
- More steps to profile, beyond §5.3's minimum.
- The probe scripts.
- The glossary's wording.
- The issues' bodies.

## 8. Done when

- ADRs 0060 to 0068 and the amendments are merged, 0060 and 0067 as
  revised.
- The inventory gives every module its phase and cites the profiling page.
- The milestone holds one issue per phase.
- The overview, `CLAUDE.md`, `HANDOFF.md`, the layout page and the glossary
  are updated.
- The backup branch and tag exist.
- `just verify` passes on `main` after the merge.
