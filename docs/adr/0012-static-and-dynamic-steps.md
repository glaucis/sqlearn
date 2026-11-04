---
type: adr
tags: [fit, learn, pipeline, sql, static, dynamic]
summary: "Records how learning runs: every step is static or dynamic, and learn chains static steps into one SQL tree, running once per dynamic step."
related: [docs/questions/fit-execution-model.md, docs/questions/earlier-attempts/README.md, docs/adr/0002-sql-on-duckdb-execution-engine.md]
---
# 0012: Static and dynamic steps decide how learning runs

Status: accepted (2026-11-04)

## Context

Before a pipeline can transform data, its steps learn values from it: an
imputer's median, a scaler's mean and spread, an encoder's categories. Each is
an aggregate query, and order matters: a scaler after an imputer must learn
from the imputed values.

Every earlier attempt that designed this computed the learning steps' values
side by side over the raw input, so `Impute` then `Scale` scaled un-imputed
data, and no test caught it
([earlier attempts](../questions/earlier-attempts/README.md)). They used
"static" and "dynamic" in two incompatible senses
([how the terms were used](../questions/earlier-attempts/static-dynamic.md)).
Checked on DuckDB 2.0.0: a chain of stages in one `WITH` query gives
scikit-learn's answer and stays fast (24 stages in 0.01 s), because DuckDB
materialises a stage read more than once.

## Decision

Every part of a pipeline is a **step**, and every step is either static or
dynamic.

- **Static:** the step's SQL can be written, and chained into one SQL tree with
  the steps around it, before any learned value is known. `Log10` is static;
  so are `Impute` and `Scale`, because their learned values are computed in an
  earlier stage of the same SQL and referenced from there.
- **Dynamic:** the step's SQL cannot be written until its learned values are
  known, because they decide its shape. `OneHot` is dynamic: its output
  columns depend on the categories it learns.

`learn` builds one SQL tree through the steps up to the first dynamic step,
including that step's own learning, and runs it. With those values known it
builds the next tree up to the next dynamic step, and so on. A pipeline
therefore learns in one run, plus one for each dynamic step whose output a
later step learns from.

Inside a run, each step reads the output of the step before it, so every
learned value comes from the data as the earlier steps left it. While
learning, a static step's values are referenced inside the SQL, never written
into it as literal numbers. Steps that change rows (filters, sampling,
deduplication) are part of the chain during `learn` as during `apply`.

How a step's class is decided:

- Built-in steps declare their class, and a test checks each declaration
  against what the step actually learns. A class may depend on constructor
  arguments: `StringSplit(max_parts=3)` is static, while
  `StringSplit(max_parts="auto")` is dynamic, because it must learn how many
  columns to make.
- A step that cannot be proved static is treated as dynamic. A wrong
  "dynamic" costs one extra run; a wrong "static" gives wrong results.

## Consequences

- One composer builds the SQL for `learn` and for `apply`, so the two cannot
  disagree about what the earlier steps did.
- A whole pipeline compared with scikit-learn's (at least `Impute` then
  `Scale`) is a required test, not only each step alone.
- Learning stages are left to DuckDB's default or marked `MATERIALIZED`; never
  `NOT MATERIALIZED`, and never built by chaining lazy relation objects, whose
  cost doubles with each step.
- Where learned values are kept once a run ends is a separate decision
  ([ADR 0014](0014-learning-store.md)).
