---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [metrics, fbeta, average-precision, confusion-matrix, classification-report, roc-curve, precision-recall-curve, evaluation]
summary: "Scoring a trained classifier beyond accuracy: fbeta, average_precision, the confusion matrix and classification report as relations, and the ROC and precision-recall curves as relations you plot with your own library."
related: [docs/specs/library-more-metrics.md, docs/adr/0049-table-metrics-are-relations.md, docs/guide/tuning-a-model.md, docs/guide/from-scikit-learn.md]
---

# Evaluating a model

A trained model is judged by how its predictions compare with the truth.
Beyond accuracy, sqlearn has scores that weigh the two kinds of mistake,
tables that show where a model goes wrong, and curves that show how it trades
one mistake for another. All of them are computed in SQL over a relation that
holds the true label, the model's prediction and, for the probability scores,
its probabilities.

This page holds out one fold of five of the breast cancer data with
`sq.folds.kfold` ([tuning a model](tuning-a-model.md)), trains a model on the
rest, and scores the held-out rows, which the model has not seen: scores on the
rows it trained on are too optimistic.

```{code-cell} python
import duckdb
import pandas as pd
from sklearn.linear_model import LogisticRegression

import sqlearn as sq

data = sq.datasets.breast_cancer()
split = sq.folds.kfold(n=5, seed=0)
train = split.rows(data, 0, held=False)
held = split.rows(data, 0, held=True).df()

pipe = sq.Pipeline([sq.scale.standard(), LogisticRegression(max_iter=1000)])
pipe.train(train, target="target")

# The model's probability of class 1, from the held rows' prepared features.
prepare = sq.Pipeline([sq.scale.standard()]).learn(train, target="target")
features = prepare.apply(held, out="pandas").to_numpy()
proba = pipe.model_.predict_proba(features)

scored = pd.DataFrame(
    {
        "target": held["target"],
        "prediction": pipe.predict(held, out="pandas")["prediction"],
        "score": proba[:, 1],
    }
)
rows = duckdb.from_df(scored)
rows.limit(3)
```

## A score that weighs recall: fbeta

`f1` weighs precision and recall equally. `fbeta` takes `beta=`, the weight
of recall against precision: `beta=2` counts a missed case twice as heavy as
a false alarm, as when a missed tumour costs more. `beta=` has no default, so
`sq.metrics.fbeta` must be called with it.

```{code-cell} python
sq.metrics.fbeta(beta=2).compute(rows, "target")
```

It takes the same `average=`, `pos_label=` and `zero_division=` as
`precision`, `recall` and `f1`.

## A score from probabilities: average_precision

`average_precision` summarises the precision-recall curve from the model's
probabilities, so it reads one column per class, `__sqlearn_proba_<i>`, and
the model's `classes_`. In a search, `metric=sq.metrics.average_precision`
supplies both.

```{code-cell} python
with_proba = duckdb.from_df(
    scored.assign(__sqlearn_proba_0=proba[:, 0], __sqlearn_proba_1=proba[:, 1])
)
sq.metrics.average_precision.compute(
    with_proba, "target", classes=pipe.model_.classes_.tolist()
)
```

With two classes it scores the class `pos_label` (1 by default; name another
with `sq.metrics.average_precision(pos_label="b")`). A `pos_label` that is not
one of the model's classes is refused, even on a fold that holds only one
class, where scikit-learn 1.9.1 would score 0.0.

## Where it goes wrong: the confusion matrix

`confusion_matrix` counts the rows of each true label (down) by predicted
label (across). It is a lazy relation, so it can be filtered, joined or
written like any other; `.show()` prints it.

```{code-cell} python
sq.metrics.confusion_matrix(rows, "target").show()
```

Each label is a column named by its text. `normalize="true"`, `"pred"` or
`"all"` divides the counts by the row, column or grand totals.

## Every class at once: the classification report

`classification_report` gives each label's precision, recall, F1 and support,
then the accuracy and the macro and weighted averages, as one relation.

```{code-cell} python
sq.metrics.classification_report(rows, "target").show()
```

The `label` column is text, so the rows can sit beside the matrix's column
names. `zero_division=` and `out=` work as they do for the scores and the
matrix.

## Trading one mistake for another: the curves

`roc_curve` and `precision_recall_curve` take a score column and give one row
per threshold. Handed with `out="pandas"` (or `"numpy"`), they go straight to
your plotting library; sqlearn has no plotting dependency.

```{code-cell} python
roc = sq.metrics.roc_curve(rows, "target", "score", out="pandas")
roc.head()
```

To plot it, give the columns to the library of your choice, for example
`ax.plot(roc["fpr"], roc["tpr"])` in matplotlib, with `fpr` across and `tpr`
up. `precision_recall_curve` has the columns `precision`, `recall` and
`threshold`; its last threshold is NULL, the point at recall 0.

```{code-cell} python
sq.metrics.precision_recall_curve(rows, "target", "score").limit(3)
```
