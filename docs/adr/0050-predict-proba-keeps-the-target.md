---
type: adr
tags: [pipeline, predict-proba, api, metrics, scikit-learn]
summary: "Records that Pipeline.predict_proba hands back the target beside one __sqlearn_proba_<i> column per class when the data holds it, unlike scikit-learn's predict_proba and sqlearn's own predict, so the probability metrics and curves read its result directly."
related: [docs/specs/pipeline-predict-proba.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0049-table-metrics-are-relations.md, docs/adr/0023-lazy-results-out-and-feed.md]
---
# 0050: predict_proba keeps the target

Status: accepted (2026-11-14). Written with
[the predict_proba spec](../specs/pipeline-predict-proba.md) (#59).

## Context

scikit-learn's `predict_proba` returns an array of one column per class and
nothing else. sqlearn's probability metrics (`average_precision`) and curves
(`roc_curve`, `precision_recall_curve`) read one relation holding the target
beside the probabilities. A result of the probabilities alone leaves every
user to join the target back on by row position. ADR 0003 asks that a
departure from scikit-learn's form gets its own ADR.

## Decision

- **When the data holds the target** the pipeline was trained on,
  `predict_proba` hands it back first, under its own name, then
  `__sqlearn_proba_0`, `__sqlearn_proba_1`, ... in the order of the model's
  `classes_`. Without it, only the probability columns.
- **The columns keep the names the search's stream makes**, which
  `Metric.compute` reads, so a score computes the same in a search and on a
  user's held-out rows.
- **`Pipeline.classes_`** names the probability columns' labels.

## Consequences

- `sq.metrics.average_precision.compute(pipe.predict_proba(held), "target",
  classes=pipe.classes_)` scores held-out rows in one line.
- `predict` and `predict_proba` differ: `predict` drops the target. Changing
  `predict` would be its own decision.
- A user who wants scikit-learn's array takes the probability columns of
  `out="numpy"`.
