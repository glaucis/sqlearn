---
type: adr
tags: [sql, duckdb, execution-engine, sqlearn, preprocessing]
summary: "Decides that every sqlearn step is expressed as SQL and executed by DuckDB, noting amendments by ADR 0058 and ADR 0060."
related: [docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/questions/multi-engine-support.md, docs/questions/fit-execution-model.md]
mdindex: [type=0fc814, tags=ef3cdd, summary=20c5df, related=8171d4]
---
# 0002: SQL on DuckDB as the execution engine

Status: accepted (2026-11-03); amended by
[ADR 0058](0058-a-gram-step-builds-xtx-in-numpy.md) (2026-11-20): a Gram step
builds XᵀX in numpy from streamed batches. Amended by
[ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md) (2026-11-21):
sqlearn becomes a C++ library embedding DuckDB and Python its bindings;
its functions join DuckDB's own.

## Context

DataFrame-based ML preprocessing has two recurring problems:

- pandas keeps data in RAM, so large datasets fail or need workarounds.
- Polars has eager and lazy modes that execute the same steps differently.

## Decision

Every sqlearn step is expressed as SQL and executed by DuckDB. Steps compose
by composing SQL, so a whole pipeline can become one query that runs in one go.

DuckDB is the only supported engine for now. Supporting other engines later
is an open question:
[questions/multi-engine-support.md](../questions/multi-engine-support.md).

## Consequences

- No step may fall back to pulling data into Python to compute something.
  If a step can't be written in SQL, that is a design problem to solve, not a
  place for an exception.
- DuckDB handles memory, streaming and spilling to disk, so dataset size is
  limited by disk rather than RAM.
- The generated SQL is a first-class output that users can inspect and run.
- Learning statistics (`fit`) and applying them (`transform`) are both SQL,
  but they may need separate queries. See
  [questions/fit-execution-model.md](../questions/fit-execution-model.md).
