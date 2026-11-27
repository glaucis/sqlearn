---
type: adr
tags: [learn, pipeline, sql, static, dynamic, runs, columns]
summary: "Records how many runs learning takes: each step goes in the earliest run its own input columns allow, so independent dynamic steps share a run and only chains between steps force a new one."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/archived/0014-learning-store.md, docs/adr/0020-column-selectors.md, docs/architecture/overview.md]
---
# 0018: Runs follow the chains between steps

Status: accepted (2026-11-04). Supersedes the run count in
[ADR 0012](0012-static-and-dynamic-steps.md) ("one run, plus one for each
dynamic step whose output a later step learns from", built "up to the first
dynamic step"); the rest of 0012 stands. Archived (2026-11-27): superseded by
[ADR 0074](../0074-how-a-pipeline-learns.md), which states how a pipeline learns
in full.

## Context

ADR 0012 splits learning at each dynamic step in pipeline order. That
overcounts: dynamic steps on different columns do not depend on each other.

```python
sq.OneHot(cols=["x"])  # dynamic
sq.Scale(cols=["x_*"])  # reads x's new columns
sq.OneHot(cols=["y"])  # dynamic, does not touch x
sq.Scale(cols=["y_*"])  # reads y's new columns
model
```

Splitting at the first column that is not yet known gives three runs. Both
`OneHot` steps can learn in the first run, and both `Scale` steps can learn and
apply in the second, which also hands the data to the model: two runs.

## Decision

- Everything goes in one SQL tree; a run is split only where it is forced.
- Each step goes in the **earliest run its own inputs allow**, not after every
  step before it in the list. A step is forced into a later run only when it
  reads a column whose existence or shape depends on a dynamic step's learned
  values (OneHot's `x_red`, `x_blue`), or a value only a later run produces.
- The model counts as a reader: data handed to a model that needs a dynamic
  step's new columns is produced by the run after that step learns.
- Every step declares the columns it reads and the columns it writes; the
  overview already asks this, for the node editor. A dynamic step declares the
  **types** of the columns it will create even while their names are unknown
  (OneHot: some integer columns), so a selector that cannot match them
  ([ADR 0020](../0020-column-selectors.md)) does not wait for it.
- Where a step's columns are not known (it works on "all columns", or a user
  step does not say), it depends on everything before it. A wrong guess costs a
  run, never a wrong result.

So the number of runs is the length of the longest chain of dynamic steps that
depend on each other, plus one when the model needs a dynamic step's columns.
A pipeline with no dynamic step learns, applies and feeds the model in one run;
`predict` on new data is always one run, since every learned value is known.

One run is one query, not one read of the data: to impute with a median DuckDB
reads the data before it fills the first gap, and plans those reads itself.

## Consequences

- The compositor works on a graph of columns, not a list of steps; the pipeline
  is already a graph for the node editor (overview 3.2).
- Tests assert the number of runs as well as the results, for every
  combination that can be built: independent dynamic steps sharing a run,
  chains that force a split, steps that read everything, user steps without
  declarations.
- Inside a run, a dynamic step whose output were a single list column
  (`x_onehot = [0, 1]`) instead of named columns would need no split at all;
  that is a later optimisation
  ([issue #22](https://github.com/glaucis/sqlearn/issues/22)).
