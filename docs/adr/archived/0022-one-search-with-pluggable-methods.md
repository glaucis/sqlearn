---
type: adr
tags: [search, model-selection, hyperparameters, folds, optuna, defaults, api]
summary: "Records the search over settings: one sq.Search whose method (grid by default, random, Optuna and others) plugs in through ask and tell, with sqlearn's own params form and defaults that let it run with nothing specified."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/archived/0014-learning-store.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md]
---
# 0022: One search, with pluggable methods

Status: accepted (2026-11-04). Departs from scikit-learn in two ways, as
[ADR 0003](../0003-scikit-learn-style-api.md) asks to record: one class instead
of `GridSearchCV`, `RandomizedSearchCV` and the rest, and a search that runs
without `params` (scikit-learn's `param_grid` is required). Archived
(2026-11-27): superseded by [ADR 0077](../0077-the-search.md), which states the
search in full.

## Context

A search tries settings of a pipeline over folds and keeps the best.
scikit-learn has a class per method, and outside optimisers such as Optuna have
their own interfaces. Users should not need to remember which search classes
exist, and should be able to bring the optimiser they know. Each trial's
preparation is reused from the learning store
([ADR 0014](0014-learning-store.md)), which is what makes a search on sqlearn
fast.

## Decision

One class, `sq.Search`. A pipeline ending in a model has `train` and `predict`
([ADR 0013](../0013-learn-apply-train-predict.md)), so the search does too:

```python
search = sq.Search(pipe, params={"model__C": [0.1, 1, 10]}, metric=sq.accuracy)
search = sq.Search(pipe, metric=sq.accuracy, method=sq.Random(trials=50))
search = sq.Search(pipe, metric=sq.accuracy, method=sq.Optuna(trials=100))

search.train("data/train/*.parquet", target="churned")
search.predict("data/new.parquet")
```

**Methods plug in.** `method=` chooses how settings are picked; the argument is
not called `engine`, which names DuckDB
([ADR 0002](../0002-sql-on-duckdb-execution-engine.md)). Grid is the default;
grid and random are built in. Every method is a small adapter over
**ask and tell**, which Optuna, scikit-optimize, Nevergrad and Ray Tune all
offer: sqlearn asks for the next settings, trains them over the folds, computes
the metric in SQL, and tells the method the score. An outside library is
imported only when its method is used, so it is never a runtime dependency
([ADR 0005](../0005-runtime-dependencies.md)); a new method touches nothing
else.

**Params in one form, translated per method.** Users write lists
(`[0.1, 1, 10]`) and ranges (`sq.range(0.01, 10, log=True)`); each adapter
translates them for its library (Optuna gets `suggest_float(..., log=True)`).
Params may be written inline, built by a function or kept in the user's own
class; a library's own form (an Optuna objective's space) is passed through. A
form a method cannot use (a range given to grid) is refused with a message in
the manner of [ADR 0019](0019-custom-steps-and-failure-feedback.md), never
guessed.

**Defaults, so a search runs with nothing specified.**

- Folds: `sq.KFold(5, seed=0)`, a stored fold column (ADR 0014).
- Each method's own settings (Optuna: number of trials, sampler, seed).
- What to search: a table of default search spaces for known models from other
  libraries ([ADR 0017](../0017-models-from-other-libraries.md)), for example
  `C` from 0.001 to 100 on a log scale for scikit-learn's `LogisticRegression`.
  It grows one model at a time; the slice needs only that one.
- A model with no entry: its own default settings are evaluated over the folds
  (one trial), so the user still gets a cross-validated score.

Anything the user sets overrides the default.

**Saying what was used.** At the end of `train` the best settings are trained
on all the data, as scikit-learn's `refit=True` does. The search reports what
ran, and when a default stood in for something not given, a
`sq.DefaultsUsedWarning` (a Python warning, which users can silence) says which
and how to choose:

```text
Hint: no params given. sqlearn searched its default space for
LogisticRegression: C in [0.001, 100], log scale.
Pass params=... to choose what to search.
```

The record is always on the object: `best_params_`, `results_` (every trial
and fold, as a table) and `used_` (what was given and what was defaulted).

## Consequences

- Defaults may not suit the user's problem; that is the user's to fix by
  passing them, and the warning says so.
- The table of default search spaces must be maintained as outside libraries
  change; each entry is tested.
- Pruning (stopping a poor trial after its first folds, which Optuna supports)
  is left for later.
