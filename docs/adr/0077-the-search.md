---
type: adr
tags: [search, hyperparameter-tuning, defaults, warnings, api]
summary: "ADR 0077 consolidates the rules for sq.search: one search with pluggable methods, grouped names, default params and folds, and the defaults warning."
related: [docs/adr/archived/0022-one-search-with-pluggable-methods.md, docs/adr/archived/0031-the-defaults-warning-is-about-what-to-search.md, docs/adr/0039-the-search-names-as-groups.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0034-a-grouped-api.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0005-runtime-dependencies.md]
mdindex: [type=0fc814, tags=48fe67, summary=5a434c, related=baf3a3]
---
# 0077: The search: one function, pluggable methods, defaults and the defaults warning

Status: accepted (2026-11-27). Written on Tomas's decision of 2026-11-27, in the
docs cleanup, to consolidate the records below: it states their rules as they
stand and takes no new decision. Supersedes
[ADR 0022](archived/0022-one-search-with-pluggable-methods.md) and
[ADR 0031](archived/0031-the-defaults-warning-is-about-what-to-search.md).
Takes over the search half of
[ADR 0039](0039-the-search-names-as-groups.md) (`sq.search` and its
shortcuts); 0039 stays current for the fold schemes' names, `sq.folds`.

## Context

The rule for the search was spread over three records. ADR 0022 made one
search class, `sq.Search`, whose methods plug in through ask and tell, with
one form for params and defaults that let a search run with nothing
specified, and a `DefaultsUsedWarning` when a default stood in. ADR 0031
narrowed that warning to the one default that matters, what to search.
ADR 0034 then moved the metrics into `sq.metrics` and the warnings into
`sq.errors`, and ADR 0039 moved the search's names into groups:
`sq.Search` became `sq.search`, `sq.Grid` and `sq.range` became
`sq.search.grid` and `sq.search.range`, and `sq.KFold` became
`sq.folds.kfold`. This record states the rule with those changes applied.

## Decision

- **One search, `sq.search`.** It tries settings of a pipeline over folds and
  keeps the best. There is one search, not a class per method as in scikit-learn
  (`GridSearchCV`, `RandomizedSearchCV`), a departure from
  [ADR 0003](0003-scikit-learn-style-api.md) recorded here (ADR 0022). A
  pipeline ending in a model has `train` and `predict`
  ([ADR 0013](0013-learn-apply-train-predict.md)), so the search does too (ADR
  0022):

  ```python
  search = sq.search(pipe, params={"model__C": [0.1, 1, 10]}, metric=sq.metrics.accuracy)
  search = sq.search(pipe, metric=sq.metrics.accuracy, method=sq.search.random(trials=50))
  search = sq.search(
      pipe, metric=sq.metrics.accuracy, method=sq.search.optuna(trials=100)
  )

  search.train("data/train/*.parquet", target="churned")
  search.predict("data/new.parquet")
  ```

- **The names are a group.** `sq.search` is callable, as the step groups
  are ([ADR 0034](0034-a-grouped-api.md)), and holds the shortcuts
  `sq.search.grid()`, `sq.search.range(...)`, and `sq.search.random(...)`
  and `sq.search.optuna(...)` (ADR 0039). The top level has no `Search`,
  `Grid` or `range` (which no longer shadows the built-in); the old names
  are removed, not kept as aliases. Later methods are added as shortcuts
  in the group without touching the top level (ADR 0039).
- **Messages and reprs.** Messages print the group paths
  (`sq.search.range`). Reprs print the class and its settings, as
  scikit-learn's do: `Grid()`, `Range(low=..., high=..., log=...)`
  (ADR 0039).
- **Methods plug in.** `method=` chooses how settings are picked; the
  argument is not called `engine`, which names DuckDB
  ([ADR 0002](0002-sql-on-duckdb-execution-engine.md)). Grid is the
  default; grid and random are built in. Every method is a small adapter
  over **ask and tell**, which Optuna, scikit-optimize, Nevergrad and Ray
  Tune all offer: sqlearn asks for the next settings, trains them over the
  folds, computes the metric in SQL, and tells the method the score. An
  outside library is imported only when its method is used, so it is never
  a runtime dependency ([ADR 0005](0005-runtime-dependencies.md)); a new
  method touches nothing else (ADR 0022).
- **Params in one form, translated per method.** Users write lists
  (`[0.1, 1, 10]`) and ranges (`sq.search.range(0.01, 10, log=True)`); each
  adapter translates them for its library (Optuna gets
  `suggest_float(..., log=True)`). Params may be written inline, built by a
  function or kept in the user's own class; a library's own form (an Optuna
  objective's space) is passed through. A form a method cannot use (a range
  given to grid) is refused with a message, never guessed (ADR 0022). One
  setting covers a step's whole family
  (`params={"impute__value": ["mean", "median", 0]}`, ADR 0034).
- **The metric is a `Metric` object**, given as `metric=`, not a scorer
  string; its settings are given by calling it
  (`sq.metrics.f1(average="macro")`,
  [ADR 0042](0042-a-metrics-settings-are-a-call.md)). A NaN mean score
  ranks last, as in `GridSearchCV` (ADR 0042).
- **Defaults, so a search runs with nothing specified** (ADR 0022):
  - folds: `sq.folds.kfold(5, seed=0)` (ADR 0039; how a scheme deals its
    rows is [ADR 0040](0040-fold-schemes-as-sql-over-rows.md));
  - each method's own settings (Optuna: number of trials, sampler, seed);
  - what to search: a table of default search spaces for known models from
    other libraries ([ADR 0017](0017-models-from-other-libraries.md)), for
    example `C` from 0.001 to 100 on a log scale for scikit-learn's
    `LogisticRegression`. It grows one model at a time;
  - a model with no entry: its own default settings are evaluated over the
    folds (one trial), so the user still gets a cross-validated score.

  Anything the user sets overrides the default.
- **The best settings are trained on all the data** at the end of `train`,
  as scikit-learn's `refit=True` does (ADR 0022).
- **The defaults warning is about what to search.**
  `sq.errors.DefaultsUsedWarning` (a Python warning, which users can
  silence; ADR 0022, ADR 0034) fires only when `params` is left out, and
  says what was searched and how to choose (ADR 0031):

  ```python
  sq.search(pipe).train("t")  # warns: searched the default space
  sq.search(pipe, params={"model__C": [0.1, 1]})  # no warning
  ```

  ```text
  Hint: no params given. sqlearn searched its default space for
  LogisticRegression: C in [0.001, 100], log scale.
  Pass params=... to choose what to search.
  ```

  With no default space for the model, the warning says it ran one trial
  with the model's own settings. A default method or default folds is
  recorded in `used_` and not warned about (ADR 0031). The warning follows
  [ADR 0046](0046-sqlearn-warns-the-user-chooses.md)'s rule that an
  explicit choice is never warned about.
- **The record is always on the object:** `best_params_`, `results_`
  (every trial and fold, as a table) and `used_` (what was given and what
  was defaulted) (ADR 0022).
- **Each trial's preparation is reused from the learning store**, which is
  what makes a search on sqlearn fast (ADR 0022; the store is
  [ADR 0076](0076-the-learning-store-and-its-keys.md)).
- **The old Python implemented the search** in
  `old_python/src/sqlearn/model_selection/` (the classes `Search`, `Grid`,
  `Random`, `Optuna` and `Range`, importable from
  `sqlearn.model_selection` for type annotations and `isinstance`, and the
  groups built on `sqlearn._group.Group`, in
  `old_python/src/sqlearn/_group.py`; ADR 0039). Those are not rules: the
  C++ group's design decides the mechanics
  ([ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md)).

## Consequences

- Defaults may not suit the user's problem; that is the user's to fix by
  passing them, and the warning says so (ADR 0022).
- `search.used_` says what was defaulted, warned or not (ADR 0031).
- The table of default search spaces must be maintained as outside
  libraries change; each entry is tested (ADR 0022).
- Pruning (stopping a poor trial after its first folds, which Optuna
  supports) is left for later (ADR 0022).
- ADRs 0022 and 0031 are archived in `archived/` and keep their numbers;
  ADR 0039 stays current for `sq.folds`.
