---
type: adr
tags: [scikit-learn, api-design, estimator, conventions, sqlearn]
summary: "ADR accepting a scikit-learn-style user API for sqlearn, with later amendments changing verbs and naming to learn/apply, grouped APIs, and lazy results."
related: [docs/adr/0013-learn-apply-train-predict.md, docs/adr/archived/0022-one-search-with-pluggable-methods.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/adr/0034-a-grouped-api.md, docs/adr/0039-the-search-names-as-groups.md, docs/questions/scikit-learn-api-survey.md]
mdindex: [type=0fc814, tags=d33cc9, summary=b92b52, related=8cd0af]
---
# 0003: scikit-learn-style API

Status: accepted (2026-11-03). Amended by
[ADR 0013](0013-learn-apply-train-predict.md): the verbs are `learn` and
`apply` for steps, `train` and `predict` for models, not `fit`, `transform`
and `fit_transform`. Amended by
[ADR 0022](archived/0022-one-search-with-pluggable-methods.md): one search for
every method instead of a class per method, and a search may run without
`params`. Amended by [ADR 0023](0023-lazy-results-out-and-feed.md): `apply`
returns a lazy DuckDB relation, not a numpy array. Amended by
[ADR 0034](0034-a-grouped-api.md): public names live in groups (`sq.impute`,
`sq.scale`, ...), not in scikit-learn's classes and module map. Amended by
[ADR 0039](0039-the-search-names-as-groups.md): the search and its fold
schemes are the groups `sq.search` and `sq.folds`, not top-level classes.

## Context

scikit-learn's estimator API is what most Python ML users already know.
sqlearn is independent of scikit-learn, but users should not have to learn a
new mental model.

## Decision

The user-facing API follows scikit-learn's conventions: `fit` / `transform` /
`fit_transform`, `Pipeline`-style composition, hyperparameters set in
`__init__`, and learned state stored in attributes ending in `_`.

sqlearn does not depend on scikit-learn and is not bound to match it exactly.
Where its API has known weak spots, sqlearn may do better, but each departure
needs its own ADR explaining why.

## Consequences

- Before designing a component, check how scikit-learn does it. See
  [questions/scikit-learn-api-survey.md](../questions/scikit-learn-api-survey.md).
- Departures from scikit-learn are deliberate and recorded, never accidental.
