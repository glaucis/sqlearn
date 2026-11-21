---
type: spec
tags: [native-engine, c++, duckdb, apple-silicon, sqlearn]
summary: "Spec for moving sqlearn's computation into a C++ engine compiled into its own DuckDB build, with the decisions and Phase 0 plan."
related: [docs/architecture/overview.md, docs/questions/multi-engine-support.md, ADR 0058, ADR 0002, ADR 0060, ADR 0061, ADR 0005, ADR 0006]
mdindex: [type=d4f02e, tags=bc1538, summary=bda23d, related=a01efa]
---
# Native engine: the decisions, and Phase 0

A new part of [the overview](../architecture/overview.md): sqlearn's
computation moves into a C++ engine compiled into sqlearn's own DuckDB build.
This spec records the decisions Tomas made with an agent on 2026-11-21, each
of which becomes an ADR, and specifies Phase 0. Each later phase gets a spec of
its own.

Status: approved by Tomas on 2026-11-21. Phase 0 is
[#78](https://github.com/glaucis/sqlearn/issues/78).

## 1. Purpose

- **One engine.** Everything that computes runs inside DuckDB: the steps'
  learning, statistics, sqlearn's own models, and later GPU kernels. No data
  is copied out to Python or to other libraries.
- **C++, compiled into DuckDB.** C++ was chosen over Rust because DuckDB's
  internals (physical operators, optimiser rules, a GPU executor) and Apple's
  Metal API are C++, and one native language is wanted, not Rust now and C++
  later.
- **sqlearn stays the product:** the Python library users install and import
  instead of scikit-learn. Python stays the API (scikit-learn style, used in
  notebooks) and the bridge to Python things: outside models, Optuna, users'
  own steps, hand-overs to pandas, Polars and Arrow, saving to JSON.
- **Apple silicon first.** A Mac gets everything the chip has: CPU cores, the
  matrix units, the GPU, unified memory. Every other platform gets a safe CPU
  build. Tomas: data preparation on Apple silicon, with unified memory, is one
  of the best setups there is, and its users miss out today.
- **Memory safety** is the main worry about C++, so the safety rules bind
  from the first commit (§3.6).

What there is today: only the Gram learn sends data through Python to compute
something (ADR 0058). Everything else already runs in DuckDB as SQL, and
Python only finishes a few numbers (F scores, skewness, PCA's `eigh`). So the
engine moves little and adds most: kernels that SQL does badly (wide
aggregates such as XᵀX), functions DuckDB lacks (the distributions behind
p-values, linear algebra), and sqlearn's own models.

## 2. What it looks like

```text
uv add sqlearn            installs sqlearn and sqlearn's DuckDB build together

sqlearn                   Python: the API, the pipeline, the SQL it builds
sqlearn's DuckDB build    the `duckdb` module: DuckDB from its official
                          source, the extensions sqlearn needs, and the
                          engine (the `sqlearn` extension, C++)
```

```python
import duckdb  # sqlearn's build, with the engine inside
import sqlearn as sq

duckdb.sql("SELECT sqlearn_version()")  # the engine answers (Phase 1)
pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(n_components=3)])
pipe.learn("big/*.parquet")  # XᵀX built inside DuckDB (Phase 2)
```

```sql
-- the SQL sqlearn generates stays readable (ADR 0002)
SELECT sqlearn_gram([a - 1.5, b - 2.0, c - 0.3]) FROM data
```

## 3. Decisions

Each subsection becomes one ADR; the numbers are proposed. "Considered" names
what was weighed and why it lost.

### 3.1 The engine (ADR 0060; amends 0002)

- The engine is C++: a DuckDB extension named `sqlearn`, written against
  DuckDB's internal C++ API. That API changes between releases, so the engine
  is built for one DuckDB version; Tomas accepts the exact pin and an upgrade
  per release (§3.2).
- Python reaches it only through SQL: sqlearn calls the engine's functions in
  the SQL it already builds. No pybind11 or nanobind layer, unless a later ADR
  shows that SQL cannot carry something.
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
- Amends 0002: computation stays inside DuckDB, and the engine's functions
  join DuckDB's own. The generated SQL can always be inspected; it runs in any
  DuckDB where its plain twin exists.
- Considered: DuckDB's stable C API, called from C++ (one build loads into
  later DuckDB releases, but functions only, no operators or optimiser rules,
  and its template is marked experimental); Rust (a second native language
  later); a Python binding layer (another boundary to keep safe).

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
  requires its exact version. A Python-only fix then ships without rebuilding
  DuckDB, and Python changes never set off the C++ build. Shipping both in one
  package instead holds the identical program, so it would not be faster.
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
  all, with maximum optimisation and speed, because he uses it. The other
  platforms are built at the same time, on the CPU only, with general
  optimisations. Accuracy is never traded for speed: no `-ffast-math`, because
  a machine learning library has to be exact. Fine-grained tuning is welcome
  where it squeezes out more.
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

### 3.8 How computation moves (ADR 0067)

- `main` stays green. Each phase has its own spec, plan and branch in a
  worktree, and Tomas merges it; `just verify` passes on `main` after every
  merge.
- **The Python API and its tests are the contract:** about 3,190 tests and
  the validation runners (ADR 0016). A piece moves when its C++ version passes
  the same tests unchanged and its benchmark is not slower; only then is its
  Python computation deleted. A test of the public API changes only with an
  ADR saying why the behaviour changes. A test of an internal that the move
  deletes (the numpy Gram batches, say) goes with it, and the phase's spec
  names it.
- **Move by evidence, then by the vision:** profile where time and memory go
  before choosing what moves next (§5.3).
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
expression objects), 0016, 0043 (order-free exact sums noted as a later option,
about 6 times the cost of XᵀX), and 0058, which Phase 2 supersedes, not Phase 0.

## 4. The phases

| Phase | What | Done when |
|---|---|---|
| 0 | This spec: the decisions as ADRs, the inventory, the backup, the issues | §5 |
| 1 | The engine's skeleton and sqlearn's DuckDB build | `sqlearn_version()` answers from Python on every platform's build, the safety stack runs in CI |
| 2 | `sqlearn_gram`, and PCA on it | every PCA test and `validate_pca` pass unchanged, not slower, numpy Gram path removed |
| 3 | Numeric functions | each function validated against mpmath; PCA's `eigh` in the engine |
| 4 | sqlearn's own models, one spec each | each validated and benchmarked against scikit-learn |
| 5 | The pipeline compiler in C++ | only when a non-Python client (the apps, DuckDB-WASM) needs it |
| 6 | Apple GPU kernels | one kernel at a time, each faster where it runs (#77) |

- **Phase 1:**
  - `engine/` with DuckDB and its Python package as submodules at 2.0.1, built
    as sqlearn's DuckDB (scikit-build-core, stable ABI), the `sqlearn`
    extension compiled in;
  - `sqlearn_version()` loaded from Python in a test, and the start-up check;
  - no automatic downloads;
  - the safety stack in CI on every platform;
  - ready-made builds from CI;
  - `just` recipes (`build-engine`, `test-engine`) folded into `just check`,
    `just test` and `just verify`;
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
- **Phase 6** may start sooner for one kernel a model needs (boosting's
  histograms in Phase 4), if the evidence says so.

**The order of work** (Tomas, 2026-11-21): the migration comes first, planned
from start to end over sqlearn's whole current state, and done piece by piece
with `main` green. From Phase 1 all of sqlearn's SQL runs in sqlearn's DuckDB
build; Phases 2 and 3 move what Python and numpy still compute; the inventory
(§5.3) is the migration's full map, module by module. Python stays the API
(§1). Before Phase 1, HANDOFF's three small queued fixes land (the one-line
`profile` fix, #75, #76; the agent's call). New library areas wait until the
migration is done, and work that needs an engine function (p-values,
normality tests) waits for the phase that brings it.

## 5. Phase 0's deliverables

### 5.1 The backup

Before any engine work, the branch `main_python` and the annotated tag
`python-final` at `main`'s tip (`ca2b720` today, pure Python), local only;
pushed when Tomas says.

### 5.2 The ADRs

ADRs 0060 to 0068 as in §3, each with an "Amended by" line added to every ADR
it amends (0002, 0004, 0005, 0006, 0009, 0017, 0046, 0057), and grouped in
`docs/adr/index.md` under a topic of their own.

### 5.3 The inventory

`docs/architecture/engine-inventory.md`: every module of `src/sqlearn` in
one of three groups, with its reason:

- **moves to C++**, naming the phase and the function;
- **stays Python**, saying why;
- **later**, saying what would trigger it.

The draft grouping, to be confirmed by the profiling:

| Area | Modules | Group |
|---|---|---|
| The Gram learn | `_gram.py` | moves: `sqlearn_gram` (Phase 2) |
| PCA | `decomposition/pca.py` | its learn moves with the Gram learn (Phase 2) and its `eigh` (Phase 3); its settings, learned values and apply SQL stay |
| Feature scores | `feature_selection/_scores.py` | stays (finishes a few numbers); gains p-values from Phase 3 |
| Exploration | `explore/*` | stays SQL; Spearman's ranks and `profile`'s moments move only if profiling shows a cost; `histogram`'s counts are a GPU candidate (Phase 6) |
| Steps | `preprocessing/*`, the rest of `feature_selection/*` | stays: the SQL already runs in DuckDB; an exact median that spills (`quantile_cont` does not) is a later candidate |
| Metrics | `metrics/*` | stays: one aggregate query each |
| Model selection | `model_selection/*` | stays: it orchestrates runs and Optuna |
| The core | `_pipeline`, `_compose`, `_plan`, `_step`, `_store`, `store`, `_inputs`, `_selectors`, `_names`, `_expr`, `fn`, `agg/*`, `_group`, `_config`, `_diagnose`, `_errors`, `errors`, `_output`, `out` | stays until Phase 5: it builds SQL once per run, never per row |
| Hand-overs | `_feed`, `_model`, `_memory` | stays: the bridge to Python libraries; sqlearn's own models (Phase 4) skip it |
| Saving | `_saving/*` | stays: JSON |

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
  one it follows (Phases 5 and 6 by Phase 1).
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
the workflow editor; replacing Optuna; PyPI; GPUs other than Apple's.

## 7. Left to the builder

- The ADRs' titles and wording, within §3.
- The inventory's layout.
- More steps to profile, beyond §5.3's minimum.
- The probe scripts.
- The glossary's wording.
- The issues' bodies.

## 8. Done when

- ADRs 0060 to 0068 and the amendments are merged.
- The inventory groups every module and cites the profiling page.
- The milestone holds one issue per phase.
- The overview, `CLAUDE.md`, `HANDOFF.md`, the layout page and the glossary
  are updated.
- The backup branch and tag exist.
- `just verify` passes on `main` after the merge.
