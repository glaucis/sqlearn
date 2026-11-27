---
type: question
tags: [learning, fit, execution-model, static-steps, dynamic-steps, learned-state]
summary: "Answered: how learning runs (ADR 0012), the verbs (ADR 0013) and where learned state lives (ADR 0014); kept for its evidence until the earlier-attempt reviews are retired."
mdindex: [type=1f5087, tags=a75939, related=fa6ef0]
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/archived/0014-learning-store.md, docs/questions/archived/earlier-attempts/README.md]
---
# How does learning run? (answered)

Answered on 2026-11-04:

- how learning runs, and what static and dynamic steps are:
  [ADR 0012](../../adr/archived/0012-static-and-dynamic-steps.md);
- the verbs `learn`, `apply`, `train` and `predict`:
  [ADR 0013](../../adr/0013-learn-apply-train-predict.md);
- where learned values live, and when they are reused:
  [ADR 0014](../../adr/archived/0014-learning-store.md). Saving them to a file
  is a later idea ([issue #20](https://github.com/glaucis/sqlearn/issues/20)).

The evidence below stays until the earlier-attempt reviews are retired; this
file is deleted with them ([the plan](earlier-attempts/README.md)).

## What the earlier attempts show

Evidence from the ten earlier attempts ([the map](earlier-attempts/README.md),
with each review's citations); now decided in the ADRs above.

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
