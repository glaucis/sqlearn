---
type: adr
tags: [models, engine, duckdb, hand-over, scikit-learn, architecture-decision]
summary: "Records that sqlearn's own models become a goal, trained inside DuckDB with no hand-over, in a set order with one spec each, while outside models stay supported."
related: [docs/adr/0017-models-from-other-libraries.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/specs/native-engine.md]
---
# 0068: sqlearn's own models, in the engine

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.9).
Amends [ADR 0017](0017-models-from-other-libraries.md).

## Context

[ADR 0017](0017-models-from-other-libraries.md) says that "for now" sqlearn
builds everything except the models, and that models written in SQL "may come
later". It also names the limit of the hand-over: the prepared data is loaded
into memory, so training is limited to what the chosen library can hold.

## Decision

- sqlearn's own models become a goal: trained inside DuckDB on data larger
  than memory, with no hand-over, and predicting in plain SQL where the model
  allows. Outside models stay supported, and the hand-over stays.
- The order, one spec each:
  1. linear and ridge regression (gram plus solve; predict is one SQL
     expression);
  2. logistic regression (IRLS passes);
  3. k-means;
  4. naive Bayes;
  5. histogram gradient boosting.
- Each is validated against scikit-learn
  ([ADR 0016](0016-validation-method.md)) and benchmarked
  against it on the same data.
- Prior art first: Apache MADlib (Apache-2.0) and LightGBM's histogram
  algorithm.
- Replacing Optuna and the outside models with sqlearn's own is a later
  choice, and needs no C++: a search's cost is its trials' training.

## Consequences

- Each model is its own spec, in Phase 4 of the native engine.
- Each model is validated and benchmarked against scikit-learn before it
  counts as done.
- Outside models and the hand-over stay supported, so a user's choice of
  model library is unchanged.
