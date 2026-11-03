---
type: adr
tags: [api, scikit-learn, design, estimator, compatibility]
summary: "Records the decision that sqlearn's user-facing API follows scikit-learn's conventions, with departures requiring their own ADR."
related: [docs/questions/scikit-learn-api-survey.md]
mdindex: [type=0fc814, tags=64cd6d, summary=1a8364, related=ff7cc4]
---
# 0003: scikit-learn-style API

Status: accepted (2026-11-03)

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
