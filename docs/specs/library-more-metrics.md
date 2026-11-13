---
type: spec
tags: [metrics, fbeta, confusion-matrix, classification-report, roc-curve, precision-recall-curve, average-precision, library-breadth]
summary: "Spec for the second metrics slice of sqlearn's library breadth (overview 3.3): fbeta and average precision as scores, and the confusion matrix, the classification report and the ROC and precision-recall curves as tables handed back as DuckDB relations, all computed in SQL and checked against scikit-learn 1.9.1."
related: [docs/specs/library-metrics.md, docs/adr/0042-a-metrics-settings-are-a-call.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0016-validation-method.md]
---
# Library breadth: more metrics

The sixth area of part 3.3 of [the overview](../architecture/overview.md), the
second slice of metrics after [precision, recall and F1](library-metrics.md).

Status: written on 2026-11-13 without a design talk. Tomas asked for the
area to be built without questions, so every choice here is the spec's call
unless it repeats a rule already set (the first metrics spec, ADR 0042). A
builder check the same day measured scikit-learn 1.9.1 against the first
draft; its corrections are in this text.

## 1. Purpose

sqlearn scores a model with nine metrics, each one number: what a search
ranks by. After the score, someone evaluating a classifier wants to see
where it goes wrong: which classes it confuses, how each class fares, and
how the trade-off between two kinds of error moves with the threshold. In
scikit-learn that is `fbeta_score`, `confusion_matrix`,
`classification_report`, `roc_curve`, `precision_recall_curve` and
`average_precision_score`. The first metrics spec left them for a later
slice (its §10). This slice adds them.

The two rules of the first slice hold here too:

1. **They behave as scikit-learn 1.9.1's**: the same numbers, defaults and
   refusals. Where this text and scikit-learn 1.9.1 disagree, scikit-learn
   is built and this spec is corrected.
2. **Everything is computed in SQL** by DuckDB. What comes back is small (a
   few counts per class), or is a relation the user reads as they like. A
   curve over a billion rows is a query, not a billion-element array.

## 2. What it looks like

```python
import sqlearn as sq

# Scores: Metrics, usable with compute and as a search's metric=.
sq.metrics.fbeta(beta=2.0).compute(rel, "y")
sq.metrics.fbeta(beta=0.5, average="macro").compute(rel, "y")
search = sq.search(pipe, params, metric=sq.metrics.average_precision)
sq.metrics.average_precision(pos_label="churned")  # text labels

# Tables: functions over a relation, handed back as a DuckDB relation.
sq.metrics.confusion_matrix(rel, "y")  # prediction="prediction"
sq.metrics.confusion_matrix(rel, "y", normalize="true", out="numpy")
sq.metrics.classification_report(rel, "y").show()
sq.metrics.roc_curve(scored, "y", "score", out="pandas")
sq.metrics.precision_recall_curve(scored, "y", "score")
```

`scored` is any relation with a target column and a score column (a
probability or a decision value), as scikit-learn's curves take `y_true` and
`y_score`.

## 3. The scores

### fbeta

`sq.metrics.fbeta` is a `ClassificationMetric` (ADR 0042) with one more
setting, `beta`, beside `average`, `pos_label` and `zero_division`, all as
scikit-learn's `fbeta_score`. `f1` is `fbeta` at `beta=1` and keeps its
name.

- `beta` has no default, as in scikit-learn: computing `sq.metrics.fbeta`
  without it refuses, telling the user to pass `beta=`. A search given it
  refuses the same way before any fold is trained.
- `beta` is taken as scikit-learn 1.9.1 takes it, a float in `[0, inf]`:
  `beta=0` is precision, `beta=inf` is recall, a bool is a number
  (`beta=True` is F1). Below 0, NaN, or not a number is refused.
- Zero division follows scikit-learn's rule for F-beta.

### average_precision

`sq.metrics.average_precision` is a `"predict_proba"` metric, as `roc_auc`,
greater is better, with one setting, `pos_label` (default `1`), as
scikit-learn's `average_precision_score`; a call sets it (ADR 0042).

- **Two classes:** the average precision of class `pos_label`, read from
  that class's probability column in `classes` (with labels `{1, 2}` it is
  class 1, `proba[:, 0]`, as scikit-learn). `pos_label` not among the
  classes refuses as scikit-learn does, so text labels need `pos_label=`.
- **More:** each class against the rest, averaged with equal weight
  (scikit-learn 1.9.1's multiclass `average="macro"`). `pos_label` other
  than 1 refuses there, as scikit-learn fixes it to 1 for multiclass.
- **A class with no target rows:** with two classes, no positive rows give
  0.0 and scikit-learn's warning, no negative rows give 1.0 and no warning.
  With more classes, a class missing from the target refuses as `roc_auc`
  does (`MissingClassError`), since scikit-learn has no answer there; a
  search names the fold.
- Computed as `roc_auc` is, a window stage over the rows by each class's
  probability, then one aggregate. Ties count as scikit-learn counts them
  (one threshold per distinct score).

## 4. The tables

Each is a function `f(rel, target, ..., out=None)` and hands back a DuckDB
relation, lazy, sorted as scikit-learn orders its output. `out=` converts
it as `Pipeline.predict`'s `out=` does (`"pandas"`, `"polars"`, `"numpy"`,
`"arrow"`). They are not `Metric`s: a table cannot rank a search, and
passing one as `metric=` refuses, saying so. The departure from
scikit-learn's form (arrays and a string) is recorded in an ADR (§8).

### confusion_matrix

```python
sq.metrics.confusion_matrix(rel, target, prediction="prediction", *, normalize=None, out=None)
```

One row per true label, one column per predicted label, as scikit-learn's
matrix (`C[i, j]`: rows of true label `i` predicted `j`).

- The labels are those in the target or the prediction, sorted, as
  scikit-learn takes them without `labels=`. A target and prediction
  holding one label between them warn, as scikit-learn 1.9.1 does ("A single
  label was found"), and give a 1 by 1 matrix.
- The first column holds the true label and is named as `target`; then one
  column per label, named by the label's text as DuckDB renders it (a
  boolean is `true`, not `True`). A label whose text equals `target`, or an
  empty text label (DuckDB cannot name a column with no text), refuses,
  saying why and how to fix it.
- Counts are `BIGINT`. `normalize` is `None`, `"true"`, `"pred"` or `"all"`,
  as scikit-learn; normalised cells are `DOUBLE`, and a row or column with
  no rows gives 0, as scikit-learn's `nan_to_num`.
- The label checks are those of precision, recall and F1 (the first spec's
  §4): no rows, NULL, NaN, infinity, continuous or mixed-kind labels, nested
  types, types DuckDB cannot compare.

### classification_report

```python
sq.metrics.classification_report(rel, target, prediction="prediction", *, zero_division="warn", out=None)
```

scikit-learn's report with `output_dict=True`, as rows. Columns `label`
(`VARCHAR`), `precision`, `recall`, `f1_score` (`DOUBLE`), `support`
(`BIGINT`). Rows: one per class, in label order; then `accuracy`
(precision and recall NULL, `f1_score` the accuracy, `support` every row);
then `macro avg` and `weighted avg`.

- The per-class scores come from the same grouped counts as precision,
  recall and F1, in one query; their zero-division warning is the same
  warning, naming the classes.
- scikit-learn's text form is not copied: `.show()` on the relation prints
  it as a table (spec's call: the relation is the result, the text one way
  to look at it).
- `precision_recall_fscore_support` is not added: the report's class rows
  are its arrays.

### roc_curve

```python
sq.metrics.roc_curve(rel, target, score, *, pos_label=None, drop_intermediate=True, out=None)
```

Columns `fpr`, `tpr`, `threshold` (`DOUBLE`), in scikit-learn's order: the
first row at threshold `inf`, then one row per distinct score, descending.

- Binary target only, as scikit-learn. `pos_label=None` takes what
  scikit-learn 1.9.1 takes: the labels `{0, 1}`, `{-1, 1}`, or one of `{0}`,
  `{1}`, `{-1}`, as integers, floats or booleans; other labels refuse,
  asking for `pos_label=`.
- `drop_intermediate=True` drops the points scikit-learn drops: a point
  whose second differences of both the false and the true positive counts
  are 0 (equal steps on both sides), not every point on a straight line.
  Decided from the exact counts with `lag` and `lead`; the first and last
  points are kept.
- No negative (or no positive) rows: scikit-learn's
  `UndefinedMetricWarning`, and `fpr` (or `tpr`) NaN, as scikit-learn.
- The score column refuses NULL, NaN and infinity, as scikit-learn refuses
  an infinite score.

### precision_recall_curve

```python
sq.metrics.precision_recall_curve(rel, target, score, *, pos_label=None, drop_intermediate=False, out=None)
```

Columns `precision`, `recall`, `threshold` (`DOUBLE`), in scikit-learn's
order: thresholds increasing, then the final point (precision 1, recall 0),
whose `threshold` is NULL (scikit-learn returns one threshold fewer than
points).

- The same labels, `pos_label` and refusals as `roc_curve`.
- Missing classes as scikit-learn 1.9.1, which differs from `roc_curve`: no
  positive rows warn (scikit-learn's `UserWarning`, "No positive class found
  in y_true, recall is set to one for all thresholds"), recall is 1 and
  precision 0 (1 at the final point); no negative rows give precision 1 and
  no warning.

## 5. Computed in SQL

- The matrix is one grouped count over (target, prediction), pivoted to a
  column per label. The labels are known from the same pass's checks, so
  the pivot's columns are fixed before it runs.
- The report reuses `ClassificationMetric`'s grouped counts; the scores are
  arithmetic on one row per class.
- A curve is one grouped count per distinct score (positives and negatives
  at that score), then running sums in a window ordered by score: one row
  per distinct score. Rates divide two exact integers once.
  `drop_intermediate` compares neighbouring counts with `lag` and `lead`.
- `average_precision` cannot stay in integers as `roc_auc` does: it is
  `Σ Δtp_k · precision_k / P` over the thresholds, and each precision has its
  own denominator. The terms are summed in doubles, compensated (`fsum`,
  ADR 0033), and the bound against the exact `Fraction` answer is measured.

## 6. Tests and validation

- **Against scikit-learn** (ADR 0016), each function and score on two and
  three classes (curves: two), integer and text labels, ties in the scores,
  and the sizes of `validation/_cases.py`. Counts are compared exactly;
  rates and scores within bounds set from the first measurement, against an
  exact answer computed with `Fraction`. Results committed under
  `validation/sqlearn/metrics/`.
- **Edge cases**, each against scikit-learn: one class, a class never
  predicted, a perfect and a wholly wrong prediction, every `normalize`,
  every `zero_division`, `beta` 0 and refused values, every refusal of §3
  and §4.
- **In a search:** `fbeta(beta=2)` gives the scores of
  `GridSearchCV(scoring=make_scorer(fbeta_score, beta=2))` on sqlearn's
  folds. `average_precision` gives, on each fold, scikit-learn's
  `average_precision_score` of that fold's `predict_proba`, as the roc_auc
  search test checks it, on `{0, 1}` labels: scikit-learn's own
  `"average_precision"` scorer reads `decision_function` first, which
  sqlearn's search does not call, so it is not the reference.
- **Unit tests** through the public seams (`compute`, the calls, the five
  functions), named in `GLOSSARY.md` terms.

## 7. Documentation

- The metrics reference page gains the two scores and five functions, each
  with an example that runs as a doctest.
- A guide page, "Evaluating a model", shows the scores, the matrix, the
  report and a curve on a dataset from `sq.datasets`, and how to plot a
  curve from `out="pandas"` (plotting stays the user's library).
- The tuning guide's metrics table gains `fbeta` and `average_precision`.
- The scikit-learn name map gains every name of §2 beside its sqlearn form,
  and `precision_recall_fscore_support` pointing to the report.
- `GLOSSARY.md` gains the terms the slice settles (a table metric, a
  curve), if the builder finds them needed.

## 8. Decisions to record

- An ADR: the tables are functions handing back a relation with `out=`, not
  arrays or a string, and are not `Metric`s (§4; ADR 0003 asks for one).

## 9. Done when

- §2's examples run.
- §6's tests and validations pass in `just verify`.
- §7's documentation builds.

## 10. Not in this spec

- `labels=` and `sample_weight=` anywhere, `average=None` on a score (the
  report has the per-class scores), multilabel data.
- `det_curve`, calibration curves, plotting (`*Display`): a plot needs a
  plotting library, outside ADR 0004's one runtime dependency.
- Other scores (`balanced_accuracy`, `matthews_corrcoef`, `cohen_kappa`,
  `brier_score`), and more regression metrics: a later slice.

## 11. Left to the builder

- Module layout, internal names, message text beyond ADR 0019's form.
- How `ClassificationMetric` takes `beta` and how `f1` becomes `fbeta` at 1.
- The pivot's SQL (DuckDB `PIVOT` or conditional sums).
- How the window stage is shared between `roc_auc` and `average_precision`.
