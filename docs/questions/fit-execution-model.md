---
type: question
tags: [fit, execution-model, sql, pipeline, duckdb]
summary: "Open questions on how fit executes: one query versus ordered aggregates, where learned state lives, and what the single-SQL promise covers."
mdindex: [type=1f5087, tags=2d58d7, summary=d914af]
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
