---
type: adr
tags: [cpp, duckdb, nanobind, bindings, engine, architecture-decision]
summary: "Records that sqlearn becomes a C++ library embedding DuckDB with Python as thin nanobind bindings, its C++ API internal, its functions named sqlearn_ and living in engine/, and apply SQL free to call them where a benchmark shows it faster; amends ADR 0002."
related: [docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0015-duckdb-expressions-no-sqlglot.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/specs/native-engine.md, docs/questions/multi-engine-support.md]
---
# 0060: sqlearn is a C++ library, and Python its bindings

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.1). Amends
[ADR 0002](0002-sql-on-duckdb-execution-engine.md). Revised before merging
(2026-11-21), with the spec's revision: sqlearn becomes a C++ library
embedding DuckDB, and Python its bindings.

## Context

What there is today: 74 Python modules, about 31,500 lines with their
docstrings, and 27,400 lines of tests. Only the Gram learn sends data through
Python to compute something (ADR 0058). Everything else already runs in DuckDB
as SQL that Python builds, and Python finishes a few numbers (F scores,
skewness, PCA's `eigh`).

So the port rewrites the library's logic, the SQL builder above all, rather
than its computation. The engine adds kernels that SQL does badly (wide
aggregates such as XᵀX), functions DuckDB lacks (the distributions behind
p-values, linear algebra), and sqlearn's own models.

Tomas wants all of sqlearn in C++ (Tomas, 2026-11-21), with Python keeping no
logic of its own, only bindings. His reasons:

- if sqlearn becomes popular, bindings for other languages (Rust, R or
  others) can follow, each a wrapper over the same core, written once;
- one language is easier and more uniform than logic split between Python and
  C++;
- everything else is wrapping.

C++ was chosen, not Rust, because DuckDB's internals (physical operators,
optimiser rules, a GPU executor) and Apple's Metal API are C++, and one
native language is wanted, not Rust now and C++ later.

## Decision

- **The library is C++,** embedding DuckDB and written against DuckDB's
  internal C++ API. That API changes between releases, so sqlearn is built
  for one DuckDB version; Tomas accepts the exact pin and an upgrade per
  release (ADR 0061). Its kernels (XᵀX, the distributions, later the models
  and GPU kernels) are registered in DuckDB as functions and run inside its
  queries; the C++ library builds the SQL that calls them, as the Python does
  today.
- **Python is a thin layer of bindings,** written with nanobind (BSD-3): the
  lowest per-call cost of the C++ binding tools, smaller and faster to build
  than pybind11, by the same author; zero-copy numpy and Arrow arrays; and
  CPython's stable ABI from 3.12, so one build serves every Python from the
  floor (ADR 0007). DuckDB 2.0's own Python module is built with it. The
  bindings hold no logic: they convert arguments, hand Python objects
  (outside models, Optuna, users' own steps, data frames) to the C++ through
  interfaces the C++ defines, and keep `sq.`'s names, docstrings and errors.
  A call such as `learn` crosses into C++ once, never once per row.
- **The one seam to Python steps** (the agent's call): a step written in
  Python, built from DuckDB's Python expressions (today every step is; ADR
  0019 inspects an undeclared one by calling its `apply`), reaches the C++
  compositor through one interface the C++ defines. The bindings call the
  Python step's methods and hand its expressions over as DuckDB expressions,
  which cross unchanged because there is one DuckDB (ADR 0061). That seam
  lets the core be ported first while the built-in steps are still Python,
  and stays afterwards for the users' own steps: users keep writing their own
  steps in Python after the port (Tomas, 2026-11-21), and those run as fast
  as today, while sqlearn's own steps are C++.
- **Other languages bind later, when wanted** (Tomas, 2026-11-21): Python
  binds the C++ directly now. A small C layer over the C++ comes when a
  language that needs one (R, Rust) is wanted, and each such language binds
  that layer. Nothing in the C++ is rebuilt for it: the C layer sits on top.
- **The C++ API is internal** (Tomas, 2026-11-21): only Python's `sq.` is
  public, and the C++ names may change at any time until sqlearn is done,
  tested and verified. Publishing a supported C++ API, with stable names,
  documentation and versions, is a later ADR.
- **Its SQL functions start with `sqlearn_`:** fewer collisions later, and
  plainly sqlearn's in the generated SQL. Identifiers use American spelling
  (ADR 0010).
- **It lives in this repository, under `engine/`:** one version, one CI, one
  HANDOFF.
- **Inside sqlearn, speed comes first** (Tomas, 2026-11-21): a trained
  pipeline's apply and predict SQL may call sqlearn's functions wherever a
  benchmark shows them faster, not only where plain SQL cannot do the job.
  Two things keep other engines possible later, with nothing for them written
  now:
  - Each function used in apply keeps a plain-SQL twin where one exists. Its
    tests compare the function against the twin anyway. So sqlearn can still
    show or export SQL that runs in any DuckDB. A pipeline whose apply has no
    twin says it needs sqlearn's DuckDB.
  - The compositor stays the one place SQL is rendered (ADR 0015). A
    translator (sqlglot or another) can plug in there for a later
    `engine="postgresql"`
    ([multi-engine support](../questions/multi-engine-support.md)).
- **Amends 0002:** computation stays inside DuckDB, and sqlearn's functions
  join DuckDB's own. The glue that builds the SQL and finishes a few numbers
  is C++ instead of Python. The generated SQL can always be inspected; it
  runs in any DuckDB where its plain twin exists.

## Considered

- C++ only for the heavy parts, called from SQL that Python builds (the
  spec as first approved): two languages holding logic, and every other
  language would need the Python rewritten.
- Bindings only at the end, the C++ tested by C++ ports of the tests: a
  difference from today's answers shows up only at the end, across the whole
  library, and the tests are written twice (Tomas chose bindings from the
  start, 2026-11-21).
- A C layer from the start: more work now for languages not yet wanted.
- pybind11 (higher call cost, larger builds), Cython (a third language),
  CPython's C API by hand (much code, easy to get wrong).
- DuckDB's stable C API: one build loads into later DuckDB releases, but it
  offers functions only, no operators or optimiser rules, and its template is
  marked experimental.
- Rust: a second native language later.

## Consequences

- The library's logic is ported to C++ piece by piece (ADR 0067).
- There is one DuckDB in the process, sqlearn's, shared by the C++ library
  and Python (ADR 0061).
- Phase 1 builds the bindings.
- A pipeline whose apply calls a function with no plain twin says it needs
  sqlearn's DuckDB.
- The compositor stays the one renderer (ADR 0015), so no second renderer is
  written now.
- Each DuckDB release costs an upgrade branch for sqlearn (ADR 0061).
