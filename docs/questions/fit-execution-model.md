---
type: question
tags: [fit, execution-model, pipeline, sql, duckdb]
summary: "Open questions on how fit executes across pipeline steps: one query or ordered aggregates, where learned state lives, and what one-query promise covers."
mdindex: [type=1f5087, tags=0b2585, summary=318dcc, related=3d8346]
related: [docs/architecture/overview.md]
---
# How does `fit` execute?

`transform` is a SQL expression applied to rows, so a pipeline's transforms
compose naturally into one query. `fit` is different: it learns statistics
(means, category lists, quantiles) with aggregate queries, and a later step's
statistics can depend on an earlier step's output. For example, a scaler after
an imputer must see the imputed values.

Open points:

- Can a whole pipeline's `fit` be one query, or does it take one aggregate
  query per step, run in order?
- Where is learned state kept: in Python attributes, as values embedded in the
  generated SQL, or in DuckDB tables?
- What does "one massive SQL" promise users exactly: `transform` only, or
  `fit` as well?

Proposed in [the overview](../architecture/overview.md) (3.2): the user writes
steps in order and sees results when asked; how much of a pipeline runs as one
query is the library's concern, never the user's. The core's spec answers the
points above within that rule.
