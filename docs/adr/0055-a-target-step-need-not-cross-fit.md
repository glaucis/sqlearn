---
type: adr
tags: [step-contract, target, cross-fitting, feature-selection, scikit-learn]
summary: "Records that a step learning from the target need not cross-fit: 'learns from the target' and 'cross-fits' become two declarations, sq.encode.target keeps both, and the feature selectors of sq.select learn from the target once, as scikit-learn's SelectKBest.fit does."
related: [docs/specs/archived/library-feature-selection.md, docs/specs/archived/library-preprocessing.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0037-four-additions-to-the-step-contract.md]
---
# 0055: A target step need not cross-fit

Status: accepted (2026-11-19), with the
[feature selection spec](../specs/archived/library-feature-selection.md). Chosen
by Tomas as option A on 2026-11-19; the alternatives are kept in
[#64](https://github.com/glaucis/sqlearn/issues/64).

## Context

A step that learns from the target (`uses_target`, preprocessing spec §6.2)
is cross-fitted: in `train` each row reaching later steps takes values learned
without its own inner fold, so the step has `cv` and `seed`, ends its run, and
its `apply` returns one DOUBLE. That is right for `sq.encode.target`, whose
output for a row is made from that row's own target, as scikit-learn's
`TargetEncoder.fit_transform` cross-fits.

A feature selector also learns from the target, but its output is which
columns exist. scikit-learn's `SelectKBest.fit` scores every column once on
the rows given; leakage is handled by the search, which fits the selector
again on each outer fold's training rows. Cross-fitting a selector would give
different rows different columns, which one table cannot hold.

## Decision

- **"Learns from the target" and "cross-fits" are two declarations.** A step
  may learn from the target without cross-fitting: no `cv` or `seed`, learned
  once on the rows given, and any output a step may give, dynamic or whole-row
  included.
- **`sq.encode.target` declares both,** and behaves, keys and saves as
  before.
- **The feature selectors of `sq.select` learn from the target and do not
  cross-fit,** as scikit-learn's.

## Consequences

- The step contract gains one declaration; the pipeline's learn path takes
  cross-fitting from it rather than from `uses_target`.
- Inside a search, a feature selector is learned on each outer fold's
  training rows, as `GridSearchCV` refits `SelectKBest`; the held-out rows
  never choose the columns.
- One's own step can learn from the target without cross-fitting.
