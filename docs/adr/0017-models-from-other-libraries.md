---
type: adr
tags: [models, scope, hand-over, numpy, arrow, model-selection]
summary: "Records that, for now, sqlearn builds everything except the models: it prepares data in DuckDB and hands it to any model library the user installs."
related: [docs/architecture/overview.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0014-learning-store.md, docs/adr/0005-runtime-dependencies.md]
---
# 0017: Models come from other libraries, for now

Status: accepted (2026-11-04)

## Context

The overview listed models (linear, trees, ensembles, clustering) as part of
the library's breadth. Building models in SQL is a large task, and model
libraries already exist that users trust and know: scikit-learn, XGBoost,
CatBoost, LightGBM. What sqlearn uniquely offers is the preparation in DuckDB,
on data larger than memory, and fast model selection on top of it: each fold's
preparation learned once, however many trials follow
([ADR 0014](0014-learning-store.md)).

## Decision

For now sqlearn builds everything except the models themselves: preparation
steps, pipelines, model selection (a search over hyperparameters and folds,
with sqlearn's own folds or an outside optimiser such as Optuna), metrics and
datasets.

Models come from any library the user installs. sqlearn learns the values,
builds the `apply` SQL, has DuckDB run it over the data wherever it lives
(Parquet, CSV, JSON, a DuckDB table), and hands the prepared result to the
model library in the form it takes (numpy, Arrow, pandas). A pipeline's
`train` and `predict` ([ADR 0013](0013-learn-apply-train-predict.md)) pass the
call on to that library with its parameters.

Models written in SQL may come later, as steps DuckDB runs with no hand-over;
that is a separate decision when the rest runs.

## Consequences

- Model libraries are the user's choice and never a runtime dependency of
  sqlearn ([ADR 0005](0005-runtime-dependencies.md)); the tests may use them
  as development dependencies.
- Preparation works on data larger than memory. The hand-over loads the
  prepared data into memory, because model libraries take it that way, so
  training is limited to what the chosen library can hold.
- Handing data over in batches, for libraries that learn piece by piece, and
  letting the user choose the format (Arrow and others that avoid a copy) are
  later ideas ([issue #21](https://github.com/glaucis/sqlearn/issues/21)).
