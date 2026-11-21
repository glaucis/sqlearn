---
type: adr
tags: [engine, cpp, duckdb, extension, execution, architecture-decision]
summary: "Records that sqlearn's native engine is C++, a DuckDB extension named sqlearn reached only through SQL, with sqlearn_ function names, living in engine/, and apply SQL may call it where a benchmark shows it faster; amends ADR 0002."
related: [docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0015-duckdb-expressions-no-sqlglot.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/specs/native-engine.md, docs/questions/multi-engine-support.md]
---
# 0060: A native engine in C++, inside DuckDB

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.1). Amends
[ADR 0002](0002-sql-on-duckdb-execution-engine.md).

## Context

What there is today: only the Gram learn sends data through Python to
compute something (ADR 0058). Everything else already runs in DuckDB as SQL,
and Python only finishes a few numbers (F scores, skewness, PCA's `eigh`).

So an engine moves little and adds most. SQL does some work badly: wide
aggregates such as XᵀX. DuckDB lacks some functions: the distributions
behind p-values, linear algebra. Later, sqlearn's own models need kernels
that SQL cannot express.

C++ was chosen because DuckDB's internals (physical operators, optimiser
rules, a GPU executor) and Apple's Metal API are C++, and one native
language is wanted.

Three other ways were weighed:

- **DuckDB's stable C API, called from C++.** One build would load into
  later DuckDB releases. But it offers functions only, no operators or
  optimiser rules, and its template is marked experimental.
- **Rust.** It would be a second native language later, beside C++.
- **A Python binding layer.** It is another boundary to keep safe.

## Decision

- **The engine is C++:** a DuckDB extension named `sqlearn`, written against
  DuckDB's internal C++ API. That API changes between releases, so the engine
  is built for one DuckDB version. Tomas accepts the exact pin and an upgrade
  per release.
- **Python reaches it only through SQL.** sqlearn calls the engine's
  functions in the SQL it already builds. No pybind11 or nanobind layer,
  unless a later ADR shows that SQL cannot carry something.
- **Its SQL functions start with `sqlearn_`:** fewer collisions later, and
  plainly sqlearn's in the generated SQL. Identifiers use American spelling
  (ADR 0010).
- **It lives in this repository, under `engine/`:** one version, one CI, one
  HANDOFF.
- **Inside sqlearn, speed comes first** (Tomas, 2026-11-21): a trained
  pipeline's apply and predict SQL may call the engine's functions wherever
  a benchmark shows them faster, not only where plain SQL cannot do the job.
  Two things keep other engines possible later, with nothing for them
  written now:
  - Each engine function used in apply keeps a plain-SQL twin where one
    exists. Its tests compare the engine against the twin anyway. So
    sqlearn can still show or export SQL that runs in any DuckDB. A pipeline
    whose apply has no twin says it needs sqlearn's DuckDB.
  - The compositor stays the one place SQL is rendered (ADR 0015). A
    translator (sqlglot or another) can plug in there for a later
    `engine="postgresql"`
    ([multi-engine support](../questions/multi-engine-support.md)).
- **Amends 0002:** computation stays inside DuckDB, and the engine's
  functions join DuckDB's own.

## Consequences

- The generated SQL can always be inspected. It runs in any DuckDB where its
  plain twin exists.
- A pipeline whose apply calls a function with no plain twin says it needs
  sqlearn's DuckDB.
- The compositor stays the one renderer (ADR 0015), so no second renderer is
  written now.
- Each DuckDB release costs an upgrade branch for the engine (ADR 0061).
