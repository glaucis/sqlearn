---
type: spec
tags: [pipeline, predict-proba, metrics, roc-curve, average-precision, search]
summary: "Short spec for Pipeline.predict_proba: one call hands back the target beside one probability column per class, in input order, so every probability metric and curve reads the result directly; with Pipeline.classes_ and Search.predict_proba."
related: [docs/adr/0050-predict-proba-keeps-the-target.md, docs/specs/archived/library-more-metrics.md, docs/adr/0003-scikit-learn-style-api.md, old_python/docs/guide/evaluating-a-model.md]
---
# Pipeline.predict_proba

Issue #59. Status: designed with Tomas on 2026-11-14 and approved.

## Intent

`roc_curve`, `precision_recall_curve` and `average_precision` read a model's
probabilities beside the true label. A trained `Pipeline` cannot give them:
the guide `docs/guide/evaluating-a-model.md` prepares the rows with a second,
steps-only pipeline, calls `pipe.model_.predict_proba` on the result and
stitches the target back on in pandas. `predict_proba` makes that one call,
for users scoring held-out rows.

## Approaches

| | Columns handed back | Then the user writes | Cost |
|---|---|---|---|
| A | `__sqlearn_proba_<i>` only | a join for the target, then `compute` | the stitching stays |
| B | `proba_<label>` | the join, then `roc_curve(rel, "target", "proba_1")` | `compute` would need a second way to read probabilities |
| **C** | the target, then `__sqlearn_proba_<i>` | `compute(rel, "target", classes=pipe.classes_)` | departs from `predict` and scikit-learn (ADR 0050) |

Tomas chose C: one call gives a relation every metric reads.

## Design

- `Pipeline.predict_proba(data, out=None)` works as `predict`: one query
  prepares the data with its rows numbered, the rows are streamed to the
  model's `predict_proba` in the feed it was trained with, and the result is
  sorted back by those numbers, so row `i` belongs to input row `i`.
- **What comes back.** When `data` holds the target the pipeline was trained
  on, its column first, under its own name and type, then
  `__sqlearn_proba_0`, `__sqlearn_proba_1`, ... (`DOUBLE`), in `classes_`
  order. Without the target, only the probability columns. A lazy relation
  by default; `out=` as for `predict`.
- **`Pipeline.classes_`**: the trained model's `classes_` as a list, so a
  user need not reach into `model_`. An untrained pipeline, or a model with
  no `classes_`, raises `SqlearnError` with a `Fix:` line, as `model_` does
  (a build ruling; the design said `AttributeError`, so `hasattr` raises on
  an untrained pipeline rather than answering False).
- **Refusals** (`SqlearnError`, with a `Fix:`): the pipeline is not trained
  (the message of `predict`); the model has no `predict_proba`; the model has
  no `classes_` (worded as the search's `_no_classes`, without a metric).
  All three are checked before any query runs. The checks of
  `predict` hold too (a missing column, `__sqlearn_row` in the data,
  insertion order not kept). A target named `__sqlearn_proba_<i>` is refused,
  as it could not be told apart from a class's column.
- **`Search.predict_proba(data, out=None)`** hands off to `best_pipeline_`,
  as `Search.predict` does, and refuses an untrained search alike.
- **The guide** drops the second pipeline and the pandas stitching and calls
  `predict_proba`.

## Non-goals

- `predict` is unchanged: it still drops the target.
- No `decision_function`; no renamed probability columns.

## Left to the builder

- How `predict` and `predict_proba` share their code (one private helper is
  expected).
- How the target is carried beside the stream's output, as long as no row
  reaches Python but the features the model reads. Built: the source is read
  once, into a temporary table of the prepared rows with the target set
  aside (DuckDB spills it as it needs); the model reads its features from it
  and the target is joined from it by row number. A second read of the
  source would put a target on another row's probabilities when the source
  is shuffled, sampled or changed between reads (found by the final review).
