---
type: architecture
tags: [sqlearn, duckdb, sql, scikit-learn, pipelines, design]
summary: "Describes sqlearn's direction: a scikit-learn-style ML ecosystem that compiles pipeline steps into SQL executed on DuckDB, with links to its ADRs."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/questions/multi-engine-support.md, docs/adr/0001-uv-for-python-packaging.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, ADR 0003]
mdindex: [type=4ca303, tags=0c89c0, summary=30f46d, related=18b77e]
---
# Overview

Status: direction only. Nothing described here is built yet.

## What sqlearn is

A machine-learning ecosystem in the shape of scikit-learn: pipelines,
transformers, encoders, scalers and, later, models. It is an independent
project, not a wrapper around scikit-learn.

## The difference

Every step runs as SQL on DuckDB. The user writes familiar
scikit-learn-style Python; sqlearn turns it into SQL and DuckDB executes it.

Because each step is SQL, a whole pipeline can be combined into one SQL query
and executed in one go.

## Why SQL

- **No RAM ceiling.** pandas holds the whole frame in memory. DuckDB streams
  and can spill to disk, so data larger than RAM still works.
- **One execution model.** Polars runs eager and lazy code differently, so the
  same steps can behave differently. Here everything is a SQL query, and that
  query is the only way anything executes.
- **Whole-pipeline optimisation.** One combined query lets DuckDB's optimiser
  plan the full pipeline, rather than running each step separately.
- **Inspectable.** The generated SQL can be read, logged, and run on its own.

## API

User-facing behaviour follows scikit-learn conventions (`fit`, `transform`,
`fit_transform`, `Pipeline`, hyperparameters in `__init__`, learned state in
attributes ending in `_`) so scikit-learn users feel at home. Where
scikit-learn's API has known weak spots, sqlearn may improve on it. Each such
change is recorded as an ADR. See [ADR 0003](../adr/0003-scikit-learn-style-api.md).

## Later

- Other database engines (Postgres and others) by transpiling the generated
  SQL, possibly with sqlglot. See
  [questions/multi-engine-support.md](../questions/multi-engine-support.md).

## Decisions so far

- [0001: uv for Python packaging](../adr/0001-uv-for-python-packaging.md)
- [0002: SQL on DuckDB as the execution engine](../adr/0002-sql-on-duckdb-execution-engine.md)
- [0003: scikit-learn-style API](../adr/0003-scikit-learn-style-api.md)
