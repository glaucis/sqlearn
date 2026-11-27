---
type: adr
tags: [pipeline, static-steps, dynamic-steps, planner, learning]
summary: "ADR 0074 decides how a pipeline learns: static vs dynamic steps, each step in its earliest run, runs along the column graph; supersedes ADRs 0012, 0018, 0026."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/archived/0018-runs-follow-the-chains-between-steps.md, docs/adr/archived/0026-a-step-without-cols-works-on-every-column.md, docs/adr/0075-the-contract-of-a-users-own-step.md, docs/adr/0076-the-learning-store-and-its-keys.md, docs/adr/0020-column-selectors.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/architecture/overview.md]
mdindex: [type=0fc814, tags=295a48, summary=9a79dc, related=51574e]
---
# 0074: How a pipeline learns: static and dynamic steps, and its runs

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27, in the docs
cleanup. Supersedes [ADR 0012](archived/0012-static-and-dynamic-steps.md),
[ADR 0018](archived/0018-runs-follow-the-chains-between-steps.md) and
[ADR 0026](archived/0026-a-step-without-cols-works-on-every-column.md).

## Context

Before a pipeline can apply its steps, they learn values from the data (an
imputer's median, a scaler's mean and spread, an encoder's categories), and
order matters: a scaler after an imputer must learn from the imputed values.
The rule for how this runs was spread over three records. ADR 0012 split every
step into static or dynamic and had learning run once, plus once per dynamic
step whose output a later step learns from. ADR 0018 superseded that run
count: each step goes in the earliest run its own input columns allow, so the
planner works on a graph of columns. ADR 0026 then said what a step given no
columns works on, and how the planner treats it. How a user's own step is
classed static or dynamic is
[ADR 0075](0075-the-contract-of-a-users-own-step.md).

## Decision

- **Every part of a pipeline is a step, and every step is static or dynamic**
  (ADR 0012).
  - **Static:** the step's SQL can be written, and chained with the steps
    around it, before any learned value is known. A log transform is static;
    so are `sq.impute` and `sq.scale.standard`, because their learned values
    are computed earlier in the same SQL and referenced from there.
  - **Dynamic:** the step's SQL cannot be written until its learned values
    are known, because they decide its shape. `sq.encode.onehot` is dynamic:
    its output columns depend on the categories it learns.
- **Each step reads the output of the step before it**, so every learned
  value comes from the data as the earlier steps left it. While learning, a
  static step's values are referenced inside the SQL, never written into it as
  literal numbers (ADR 0012).
- **Steps that change rows** (filters, sampling, deduplication) are part of
  the chain during `learn` as during `apply` (ADR 0012).
- **`learn` and `apply` agree on what the earlier steps did:** the SQL for
  both is built the same way (ADR 0012).
- **Built-in steps declare their class**, and a test checks each declaration
  against what the step actually learns. A class may depend on a step's
  settings: a step splitting a string into a set number of columns is static,
  and one told to learn how many columns to make is dynamic (ADR 0012). How a
  user's step is classed is ADR 0075's.
- **A step that cannot be proved static is treated as dynamic.** A wrong
  "dynamic" costs one extra run; a wrong "static" gives wrong results
  (ADR 0012).
- **Everything goes in one SQL tree; a run is split only where it is forced**
  (ADR 0018).
- **Each step goes in the earliest run its own inputs allow**, not after every
  step before it in the list. A step is forced into a later run only when it
  reads a column whose existence or shape depends on a dynamic step's learned
  values (a one-hot encoding's `x_red`, `x_blue`), or a value only a later run
  produces (ADR 0018). So a one-hot encoding of `x` and one of `y` both learn
  in the first run, and scaling each one's new columns learns and applies in
  the second, which also hands the data to the model: two runs, not three.
- **The model counts as a reader:** data handed to a model that needs a
  dynamic step's new columns is produced by the run after that step learns
  (ADR 0018).
- **Every step declares the columns it reads and the columns it writes**, as
  the overview also asks for the node editor. A dynamic step declares the
  **types** of the columns it will create even while their names are unknown
  (a one-hot encoding: some integer columns), so a selector that cannot match
  them ([ADR 0020](0020-column-selectors.md)) does not wait for it
  (ADR 0018).
- **A step whose columns are not known depends on everything before it** (it
  works on every column, or a user's step does not say). A wrong guess costs
  a run, never a wrong result (ADR 0018).
- **A step given no columns works on every column reaching it**, in schema
  order, columns created by earlier steps included. The planner counts it as
  reading columns it cannot know in advance, so it depends on every step
  before it: a step after a dynamic one waits for it (ADR 0026). What this
  means for its learning-store key is
  [ADR 0076](0076-the-learning-store-and-its-keys.md)'s.
- **The number of runs** is the length of the longest chain of dynamic steps
  that depend on each other, plus one when the model needs a dynamic step's
  columns. A pipeline with no dynamic step learns, applies and feeds the model
  in one run; `predict` on new data is always one run, since every learned
  value is known (ADR 0018).
- **One run is one query, not one read of the data:** to impute with a
  median, DuckDB reads the data before it fills the first gap, and plans
  those reads itself (ADR 0018).
- **The mechanics are the C++ group's design
  ([ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md)).** The old Python built
  each run as one `WITH` query of stages from a single compositor, left
  learning stages to DuckDB's default or marked them `MATERIALIZED` (never
  `NOT MATERIALIZED`, never chained lazy relation objects, whose cost doubled
  with each step), and wrote steps' SQL with `duckdb.FunctionExpression` and
  the other expression objects; its planner and compositor are now in
  `old_python/src/sqlearn/` (`_plan.py`, `_compose.py`).

## Consequences

- A whole pipeline compared with scikit-learn's (at least an imputer then a
  scaler) is a required test, not only each step alone (ADR 0012).
- The planner works on a graph of columns, not a list of steps; the pipeline
  is already a graph for the node editor
  ([overview](../architecture/overview.md), 3.2) (ADR 0018).
- Tests assert the number of runs as well as the results, for every
  combination that can be built: independent dynamic steps sharing a run,
  chains that force a split, steps that read everything, user steps without
  declarations (ADR 0018).
- Inside a run, a dynamic step whose output were a single list column
  (`x_onehot = [0, 1]`) instead of named columns would need no split at all;
  that is a later optimisation
  ([issue #22](https://github.com/glaucis/sqlearn/issues/22)) (ADR 0018).
- A step given no columns relearns whenever any earlier step changes; naming
  its columns narrows that (ADR 0026).
- ADRs 0012, 0018 and 0026 are archived in `archived/` and keep their
  numbers.
