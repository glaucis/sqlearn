---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [metrics, fbeta, average-precision, balanced-accuracy, mcc, brier, confusion-matrix, classification-report, roc-curve, precision-recall-curve, evaluation]
summary: "Scoring a trained classifier beyond accuracy: fbeta, average_precision, balanced accuracy, MCC and Brier for imbalanced classes, the confusion matrix and classification report as relations, and the ROC and precision-recall curves as relations you plot with your own library."
related: [docs/specs/library-more-metrics.md, docs/specs/library-balanced-scores.md, docs/adr/0049-table-metrics-are-relations.md, docs/guide/tuning-a-model.md, docs/guide/from-scikit-learn.md]
---

# Evaluating a model

A trained model is judged by how its predictions compare with the truth.
Beyond accuracy, sqlearn has scores that weigh the two kinds of mistake,
tables that show where a model goes wrong, and curves that show how it trades
one mistake for another. All of them are computed in SQL over a relation that
holds the true label, the model's prediction and, for the probability scores,
its probabilities.

This page uses scikit-learn's breast cancer data. It holds out about a fifth
with `sq.folds.holdout` ([tuning a model](tuning-a-model.md)), trains a model on
the rest, and scores the held-out rows, which the model has not seen: scores on
the rows it trained on are too optimistic.

```{code-cell} python
import duckdb
from sklearn.datasets import load_breast_cancer
from sklearn.linear_model import LogisticRegression

import sqlearn as sq

con = duckdb.connect()
sq.set_config(connection=con)  # sqlearn computes on your connection

frame = load_breast_cancer(as_frame=True).frame
data = con.from_df(frame)
split = sq.folds.holdout(test=0.2, seed=0)
train = split.rows(data, held=False)
held = split.rows(data, held=True).df()

pipe = sq.Pipeline([sq.scale.standard(), LogisticRegression(max_iter=1000)])
pipe.train(train, target="target")

# The held rows' target, then the model's probability of each class.
scored = pipe.predict_proba(held, out="pandas")
scored["prediction"] = pipe.predict(held, out="pandas")["prediction"]
rows = con.from_df(scored)
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
the classes they belong to, in order: `pipe.classes_`. `predict_proba` hands
back the target first when the data holds it, so its result is scored as it
is. In a search, `metric=sq.metrics.average_precision` supplies both.

```{code-cell} python
sq.metrics.average_precision.compute(rows, "target", classes=pipe.classes_)
```

With two classes it scores the class `pos_label` (1 by default; name another
with `sq.metrics.average_precision(pos_label="b")`). A `pos_label` that is not
one of the model's classes is refused, even on a fold that holds only one
class, where scikit-learn 1.9.1 would score 0.0.

## Scores for imbalanced classes

When one class is rare, accuracy flatters. A model that always says 0, on 95
rows of 0 and 5 of 1, is right 95 times in 100, yet it has learned nothing.
`balanced_accuracy` is the mean recall over the classes, and `mcc`, the
Matthews correlation coefficient, is 0 for a prediction no better than
chance and 1 for a perfect one.

```{code-cell} python
rare = con.sql(
    "SELECT 0 AS target, 0 AS prediction FROM range(95) "
    "UNION ALL SELECT 1, 0 FROM range(5)"
)
{
    name: getattr(sq.metrics, name).compute(rare, "target")
    for name in ("accuracy", "balanced_accuracy", "mcc")
}
```

`sq.metrics.balanced_accuracy(adjusted=True)` rescales it so that chance
scores 0, as scikit-learn's `adjusted=True`.

`brier` judges the probabilities themselves: the mean squared distance
between each row's probabilities and its true class, halved with two classes.
Lower is better, and it reads the same columns as `average_precision`.

```{code-cell} python
sq.metrics.brier.compute(rows, "target", classes=pipe.classes_)
```

Its one setting is `scale_by_half=` (`True`, `False` or `"auto"`, the
default). scikit-learn's `pos_label=` and `labels=` change nothing when every
probability column is given, as sqlearn gives them, so they are not settings.

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

`roc_curve` and `precision_recall_curve` take a score column, here the
probability of class 1, `__sqlearn_proba_1`, and give one row per threshold.
Handed with `out="pandas"` (or `"numpy"`), they go straight to your plotting
library; sqlearn has no plotting dependency.

```{code-cell} python
roc = sq.metrics.roc_curve(rows, "target", "__sqlearn_proba_1", out="pandas")
roc.head()
```

To plot it, give the columns to the library of your choice, for example
`ax.plot(roc["fpr"], roc["tpr"])` in matplotlib, with `fpr` across and `tpr`
up. `precision_recall_curve` has the columns `precision`, `recall` and
`threshold`; its last threshold is NULL, the point at recall 0.

```{code-cell} python
sq.metrics.precision_recall_curve(rows, "target", "__sqlearn_proba_1").limit(3)
```
