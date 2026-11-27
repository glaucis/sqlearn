---
type: adr
tags: [learned-state, cache, store, dependencies, search, folds]
summary: "Records that a store entry's key holds only the steps whose output that step reads, so changing a step relearns only the steps that depend on it, and that a grid search prepares each fold once."
related: [docs/adr/archived/0014-learning-store.md, docs/adr/archived/0018-runs-follow-the-chains-between-steps.md, docs/adr/archived/0022-one-search-with-pluggable-methods.md]
---
# 0024: Store keys follow what a step reads

Status: accepted (2026-11-04). Supersedes the "steps up to and including that
step" part of the key in [ADR 0014](0014-learning-store.md); the rest of 0014
stands. Archived (2026-11-27): superseded by
[ADR 0076](../0076-the-learning-store-and-its-keys.md), which states the
learning store and its keys in full.

## Context

ADR 0014 keys a step's learned values on every step above it in the list.
Since [ADR 0018](0018-runs-follow-the-chains-between-steps.md) sqlearn knows
which columns each step reads and writes, so it knows which earlier steps can
change a step's answer.

```python
pipe = sq.Pipeline(
    [
        ("impute", sq.Impute(cols=["age", "income"], strategy="median")),
        ("onehot", sq.OneHot(cols=["city"])),
        ("scale", sq.Scale(cols=["age", "income"])),
    ]
)
```

Changing `impute__strategy` changes what Scale learns, never what OneHot learns:
OneHot reads only `city`. Under ADR 0014 OneHot learns again anyway; in a search
over 2 imputer settings and 5 folds it learns 10 times instead of 5.

## Decision

- A step's key holds the data, the fold, the step's own settings, and the
  settings of the steps whose output it reads, followed back through the graph
  of columns: only those steps, not every step above it.
- A step that changes rows (a filter, sampling, deduplication) changes what
  every later step sees, so every later step depends on it.
- A step whose inputs are not known depends on everything before it, as in
  ADR 0018.
- A column an earlier dynamic step takes away decides what a later selector
  matches, so a step whose selector could have matched it (by name, by kind,
  or every column) depends on that step and on what that step depends on.
- The key also holds the columns the step's selector resolved to on the data
  reaching it, so a step reading other columns never finds another's entry.

A grid search, which knows every setting up front, loops **fold first**: for
each fold it prepares the data once, hands it to every model and setting, and
drops it before the next fold. The data is transformed once per fold, not once
per training, and only one fold's data is in memory at a time. Methods that
pick settings one at a time (Optuna) loop setting first; keeping each fold's
prepared data for them is a later idea
([issue #25](https://github.com/glaucis/sqlearn/issues/25)).

## Consequences

- Changing a step relearns that step and the steps that read from it, and
  nothing else.
- Tests assert, for the slice's search, how many times each step learns and how
  many times the data is transformed.
