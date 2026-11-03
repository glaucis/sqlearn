---
type: question
tags: [fit, execution-model, sql, pipeline, duckdb]
summary: "Open questions on how fit executes in a SQL-based pipeline: one query or per-step aggregates, where learned state lives, and the scope of the one-query promise."
mdindex: [type=1f5087, tags=2d58d7, summary=db75b6, related=81cf72]
related: [docs/architecture/overview.md, docs/questions/earlier-attempts/README.md]
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

## What the earlier attempts show

Evidence from the ten earlier attempts ([the map](earlier-attempts/README.md),
with each review's citations); the decision is still open.

- **Batching every learning step's aggregates over one input is wrong.**
  Every attempt that designed a fit did it, so `Impute` then `Scale` scaled
  un-imputed data; it was diagnosed in writing in March and kept, and no test
  caught it because none compared a whole pipeline with scikit-learn's.
- **A later step must learn from an earlier step's output** whenever it reads
  a value that step changed, for set queries (`DISTINCT`) as well as
  aggregates. Substituting earlier expressions into later aggregates
  (`AVG(LN(x + 1))`) works for steps that learn nothing; for learning steps the
  earlier learned values must already be known.
- **That can still be one query.** Each stage's learned values as a one-row
  relation in a `WITH` clause, read by the next stage, gives scikit-learn's
  answer on DuckDB 2.0.0, and DuckDB materialises a stage read more than once
  (24 stages in 0.01 s). Marking stages `NOT MATERIALIZED` ran out of memory at
  12; chaining lazy relation objects doubles the work with each step.
- **Row filters must reach fit** as they reach transform, and `where=` on a
  learning step can mean fit scope (`AGG(x) FILTER (WHERE …)`).
- **Learned state:** Python values inlined as literals were the usual answer.
  Its failures: "not fitted" confused with "learned NULL", keys split on `__`,
  state on shared step objects overwritten by cross-validation folds, lazy
  relations as state refitting silently, float literals never checked
  (`44.2` is read as `DECIMAL(3,1)`; `inf` and `nan` are not literals). A
  relation of learned values (the `WITH` route, or a table) was designed only
  for cross-validation. DuckDB's parallel sums differ in the last digits from
  run to run, so learned values repeat exactly only at one thread.
- **Cross-validation in one scan:** `FILTER (WHERE fold != k)` per fold equals
  the aggregate over the subset for `AVG`, `STDDEV_POP`, `MEDIAN`,
  `QUANTILE_CONT` and `MODE … ORDER BY` (checked).
