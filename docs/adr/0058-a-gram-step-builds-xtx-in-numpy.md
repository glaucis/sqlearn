---
type: adr
tags: [execution, gram-matrix, streaming, numpy, step-contract, pca]
summary: "Records that a Gram step (PCA, later linear regression) learns from XᵀX of its centred columns, which the core builds in numpy from batches DuckDB streams, because XᵀX in SQL alone fails past a few hundred columns; amends ADR 0002."
related: [docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0057-numpy-is-a-runtime-dependency.md, docs/adr/0012-static-and-dynamic-steps.md, docs/specs/library-decomposition.md]
---
# 0058: A Gram step builds XᵀX in numpy

Status: accepted (2026-11-20), with the
[decomposition spec](../specs/library-decomposition.md). Chosen by Tomas on
2026-11-20. Amends [ADR 0002](0002-sql-on-duckdb-execution-engine.md).

## Context

ADR 0002 says no step may pull data into Python to compute something. PCA
learns from the covariance of every pair of its columns: p(p+1)/2
aggregates, 1,275 at 50 columns, 125,250 at 500. Measured on 2026-11-20 on
1M rows of 200 random columns (load average about 3 to 7):

| Columns | XᵀX in DuckDB SQL alone | DuckDB streams rows, numpy builds XᵀX |
|---|---|---|
| 50 | 1.4 s | 0.2 s |
| 200 | 26 s | 0.9 s |
| 500 | out of memory (12.7 GB) | 4.6 s |

Streaming works on data larger than memory: on 12.5M rows × 200 columns
(20 GB as doubles, on a machine with 17 GB of RAM) at a 2 GB DuckDB limit,
the learn took about 2 minutes at a peak of 3.0 GB for the whole process,
and agreed with DuckDB's `covar_pop` to 3e-14. With a fifth of the rows the
peak was 3.6 GB: memory does not grow with the data.

Two ways were weighed for the core: the core builds XᵀX and hands the step a
small matrix, or the step receives the batches and computes what it likes.

## Decision

- **A Gram step learns from XᵀX of its centred input columns.** SQL learns
  its means in the ordinary learn statement; the core then streams the
  step's centred rows from DuckDB in batches, builds XᵀX in numpy, and the
  step finishes from that matrix.
- **The core builds the matrix; the step never sees a row.** What the step
  returns is learned values like any other, so the learning store, saving
  and validation treat it as any step.
- **The rule of ADR 0002 holds for everything else:** data passes through
  Python only in a Gram learn, one batch at a time, and applying stays SQL.
- **The Gram step is internal for now**: declared on `sq.Step` (`gram`,
  `before_gram`, `learned_from_gram`), documented as internal; a user's
  step that sets it is unsupported. sqlearn's own steps use it, and it is
  opened to users' steps once linear regression has used it.

## Consequences

- PCA learns at any width the memory budget allows for the p × p matrix,
  on data larger than memory.
- A Gram step learns in its own run, after the steps it reads, since its
  input must reach the stream with constants.
- Methods that need more than XᵀX (k-means, iterative fits) need their own
  way to learn, decided when they come.
- Linear and ridge regression add Xᵀy to the same learn.
