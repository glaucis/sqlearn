---
type: question
tags: [learned-state, fit, execution-model, duckdb, sql, cross-validation]
summary: "Open question on where learned state is kept once learning has run, and how it is saved; how learning runs is decided in ADR 0012."
mdindex: [type=1f5087, tags=f635d0, related=5dc381]
related: [docs/adr/0012-static-and-dynamic-steps.md, docs/questions/earlier-attempts/README.md]
---
# Where is learned state kept?

How learning runs is decided in
[ADR 0012](../adr/0012-static-and-dynamic-steps.md): static steps chain into
one SQL tree, learning runs once per dynamic step, and inside a run a static
step's learned values are referenced, never written in as literals. `apply` is
one query.

Still open: once a run ends, where are the learned values kept (Python
attributes, values written into the `apply` SQL, DuckDB tables), how are they
saved and loaded, and how are they kept apart from the step objects so that
cross-validation folds and refits cannot overwrite each other?

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
