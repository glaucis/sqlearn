---
type: adr
tags: [learned-state, learn, apply, cross-validation, cache, pipeline]
summary: "Records where learned values live: a store kept while the program runs, keyed by data, fold and steps, so nothing is learned twice and nothing is overwritten."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0003-scikit-learn-style-api.md, docs/questions/archived/earlier-attempts/README.md]
---
# 0014: Learned values live in a store while the program runs

Status: accepted (2026-11-04). The data part of the key is extended to in-memory
tables by [ADR 0021](0021-inputs-and-how-the-store-knows-them.md); the steps
part follows what a step reads, by
[ADR 0024](0024-store-keys-follow-what-a-step-reads.md). Archived (2026-11-27):
superseded by [ADR 0076](../0076-the-learning-store-and-its-keys.md), which
states the learning store and its keys in full.

## Context

`learn` produces values (an imputer's median, a scaler's mean, an encoder's
categories) and, from them, the SQL that `apply` runs
([ADR 0012](0012-static-and-dynamic-steps.md)). Earlier attempts kept these
values only on the step objects. Learning the same pipeline again, as
cross-validation does for each fold, overwrote them; a fold's values could be
applied to another fold; and every trial of a hyperparameter search learned
the same preparation steps again
([earlier attempts](../../questions/archived/earlier-attempts/README.md)).

## Decision

Every learning result goes into a **store** that lasts while the program runs.
An entry holds a step's learned values and its `apply` SQL. Its key is:

- **the data:** for a file, its path, size and modification time; for a
  table, its connection, name and row count;
- **the fold:** a fixed, seeded fold number per row, when folds are used;
- **the steps and their settings up to and including that step.**

Before learning, sqlearn looks in the store. An entry is reused only when its
data, fold and steps all match:

- changing a step's setting relearns that step and every step after it, and
  reuses the steps before it;
- changing only the model reuses all the preparation;
- changing the data matches nothing, so everything is learned again;
- after a restart the store is empty and everything is learned again, as in
  scikit-learn.

The pipeline the user holds points to its entries, so `pipe.learn(train)` then
`pipe.apply(test)` behaves as expected, and learned values are readable as
attributes ending in `_` (`pipe.steps[1].mean_`,
[ADR 0003](../0003-scikit-learn-style-api.md)). Learning the pipeline again on
other data points it at other entries; nothing is overwritten.

## Consequences

- Cross-validation and hyperparameter search learn each fold's preparation
  once, however many trials or models follow.
- The store holds values and SQL text, not data, so it stays small; it has no
  size limit for now.
- Folds must be a stored, seeded column, never recomputed with `RANDOM()`, or
  keys would not match from query to query.
- Saving the store to a file is a later idea that needs its own design
  ([issue #20](https://github.com/glaucis/sqlearn/issues/20)).
