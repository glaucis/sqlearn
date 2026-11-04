---
type: adr
tags: [sql, representation, duckdb, sqlglot, expressions, multi-engine]
summary: "Records that steps build their SQL from DuckDB's own expression objects, assembled by sqlearn into one query; no sqlglot, DuckDB only until other engines are requested."
related: [docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0012-static-and-dynamic-steps.md, docs/questions/multi-engine-support.md]
---
# 0015: DuckDB's expression objects, no sqlglot

Status: accepted (2026-11-04)

## Context

Every step contributes a piece of SQL, and sqlearn stacks the pieces into one
query of `WITH` stages ([ADR 0012](0012-static-and-dynamic-steps.md)). The
pieces need a representation: something steps build and sqlearn composes.

Most earlier attempts used sqlglot, chosen for "multi-database from day one".
It cost version pins (one release produced 292 type errors), relaxed type
checking, and SQL trees corrupted by reused nodes; its translation to other
engines is syntax, not meaning (`STDDEV` is the sample form in DuckDB and the
population form in MySQL), and no attempt ever ran on a second engine
([earlier attempts](../questions/earlier-attempts/README.md)). Plain SQL text
leaves quoting, number literals and NaN to every step, and hand-written rules
for them drifted.

DuckDB 2.0's Python package has its own expression objects (columns,
constants, functions, `CASE`, `COALESCE`, arithmetic). They print as DuckDB
SQL with identifiers quoted (`"order"`), floats typed (`44.2::DOUBLE`) and NaN
written safely (`'NaN'::DOUBLE`); checked on 2.0.0.

## Decision

- Each step builds its column expressions from DuckDB's expression objects.
- sqlearn's own small compositor assembles the whole query: the `WITH` stages,
  their joins and the final `SELECT`. It is the one place that turns pieces
  into SQL text, for `learn` and for `apply` alike.
- Where the expression objects cannot say something (a window, a subquery),
  the compositor writes that piece itself, quoting identifiers through one
  helper, never by hand in each step.
- sqlglot is not used, and sqlearn targets DuckDB only.

## Consequences

- No runtime dependency beyond `duckdb`
  ([ADR 0005](0005-runtime-dependencies.md)).
- The SQL is DuckDB's. Other engines are future work, planned only if users ask
  for them; the compositor is the one place a translator or a second renderer
  would plug in
  ([questions/multi-engine-support.md](../questions/multi-engine-support.md)).
- DuckDB's expression API can change between releases; a test covers the
  printed SQL of each expression form sqlearn relies on, so a change shows on
  upgrade.
