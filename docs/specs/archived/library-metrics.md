---
type: spec
tags: [metrics, precision, recall, f1, averaging, classification, library-breadth]
summary: "Spec for the metrics area of sqlearn's library breadth (overview 3.3): precision, recall and F1 beside accuracy, with scikit-learn's averaging modes, positive label and zero-division handling, every count computed in DuckDB."
related: [docs/architecture/overview.md, docs/specs/archived/library-core.md, docs/specs/archived/library-model-selection.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0016-validation-method.md, docs/adr/0034-a-grouped-api.md]
---
# Library breadth: metrics

The third area of part 3.3 of [the overview](../../architecture/overview.md).

Status: approved by Tomas on 2026-11-09. Written from the design talk of
2026-11-09. Where this spec makes a call of its own, it says "(spec's call)".

## 1. Purpose

The core and the model-selection area left sqlearn with six metrics:
`accuracy`, `log_loss`, `roc_auc`, `rmse`, `mae` and `r2`
(`src/sqlearn/metrics/`). Each is a `Metric`: one aggregate query in DuckDB,
usable on its own (`metric.compute(rel, target)`) and as a search's
`metric=`.

The classification metrics people reach for most after accuracy are
precision, recall and F1. This area adds those three, so the four most
common classification scores are all there.

Tomas's two requirements, from the design talk:

1. **They behave as scikit-learn's** `precision_score`, `recall_score` and
   `f1_score`: the same averaging modes, the same defaults, the same refusals.
   Someone who knows scikit-learn gets the number they expect.
2. **Everything is computed in SQL** by DuckDB. Nothing pulls the labels into
   Python; only a handful of counts per class come back, so a score works on
   data of any size.

**scikit-learn 1.9.1 wins.** Where this spec's text and scikit-learn 1.9.1
disagree on what a score, refusal or warning should be, scikit-learn's
behaviour is the one to build, and the spec is corrected (spec's call,
following requirement 1).

## 2. What it looks like

```python
import sqlearn as sq

# Two classes: the scikit-learn default, average="binary", pos_label=1.
sq.metrics.precision.compute(rel, "y")
sq.metrics.recall.compute(rel, "y")
sq.metrics.f1.compute(rel, "y")

# Any number of classes: choose how the per-class scores are averaged.
f1_macro = sq.metrics.f1(average="macro")
f1_macro.compute(rel, "y")

# Text labels: name the positive one.
sq.metrics.precision(pos_label="churned").compute(rel, "y")

# In a search, as any other metric.
search = sq.search(pipe, params, metric=sq.metrics.f1(average="weighted"))
```

`compute` takes what `accuracy.compute` takes today: a relation, its target
column and its prediction column (default `"prediction"`). The three metrics
read the model's `predict`.

## 3. The settings

Calling a metric returns a new metric with the settings changed; the
metric called is unchanged (it is frozen, as `Metric` is today). The plain
names `sq.metrics.precision`, `recall` and `f1` are scikit-learn's defaults.
(Spec's call: scikit-learn has `make_scorer` and scorer strings such as
`"f1_macro"`; sqlearn's search takes a metric object, so a call on that
object is the shorter road. Calling a metric is a departure from
scikit-learn's form and gets an ADR, §8.)

| setting | values | default | as scikit-learn 1.9.1 |
|---|---|---|---|
| `average` | `"binary"`, `"macro"`, `"micro"`, `"weighted"` | `"binary"` | yes |
| `pos_label` | a label | `1` | yes; used by `"binary"` only |
| `zero_division` | `"warn"`, `0.0`, `1.0`, `nan` | `"warn"` | yes |

- **`binary`:** the score of the class `pos_label` alone.
- **`macro`:** the plain mean of each class's score.
- **`micro`:** the score from the counts summed over the classes.
- **`weighted`:** each class's score weighted by its number of target rows.

The classes are those that appear in the target or the prediction, as
scikit-learn takes them when `labels=` is not given.

A setting given to a metric that does not have it (`accuracy(average=...)`)
or a value outside the table refuses with ADR 0019's message form.

## 4. Refusals and warnings, as scikit-learn

Each of these follows scikit-learn 1.9.1; the validation (§6) checks each
against it.

- **`binary` on more than two classes** refuses, and the message names the
  other averages. scikit-learn raises here too.
- **`pos_label` not among the labels** under `binary` refuses when two or
  more labels are present, as scikit-learn does. With integer labels 0 and 1
  the default works; with text labels the default `1` is not among them and
  refuses, telling the user to pass `pos_label=`. With one label only,
  scikit-learn does not refuse: it scores `pos_label` as an absent class,
  which falls under zero division below. sqlearn does the same, so a fold
  holding one class does not stop a search.
- **The kind of labels** (spec's call): the three new metrics refuse what
  scikit-learn's refuse, a continuous target or prediction (a non-whole
  number) and a target and prediction of different kinds (text against
  numbers); the grouped query of §5 brings back what the check needs.
  `accuracy` kept its behaviour in this area at first; since #35 it refuses
  continuous and mixed-kind labels too, from the same checks.
- **Zero division:** precision is undefined for a class never predicted,
  recall for a class never in the target, F1 when both its precision and
  recall are 0 or undefined (scikit-learn's exact rule for F1 is followed).
  With `"warn"` the score counts as 0 and a warning is raised, a
  `SqlearnWarning` subclass that names the metric and, except under
  `"micro"`, the classes (a micro score is over all classes at once, so its
  warning names none, as scikit-learn's does, #37); with a number, that
  number is used and nothing is said.
- **A NaN score in a search** (spec's call): `zero_division=nan` can make a
  fold's score NaN, which no metric could before. The search ranks a
  setting whose mean score is NaN last and picks the best among the rest, as
  `GridSearchCV` does; an Optuna trial with a NaN score is reported to
  Optuna as failed, as Optuna treats NaN. If every setting is NaN, the
  search refuses, naming `zero_division`.
- **What every metric already refuses** stays: no rows, a missing column, a
  NULL or NaN label (`Metric.compute` today). Since #37 the label metrics
  also refuse an infinite label, a LIST, ARRAY, STRUCT, MAP or UNION label
  column, and two columns whose types DuckDB cannot compare, as
  scikit-learn refuses them.

## 5. Computed in SQL

All the counts come from DuckDB in one query: grouped by label, the number of
rows where it is the target, where it is the prediction, and where it is
both. From those three counts per class come every class's true positives,
false positives and false negatives; the averaging is arithmetic on these few
numbers, and may run in Python or SQL (left to the builder), since only one
row per class comes back. The checks of §4 read the same counts, so a
refusal costs no second pass over the data where it can be avoided.

Today's `Metric` holds one aggregate expression over the rows. A per-class
count needs a grouped stage first, so the interface grows to allow it, as
it grew for `roc_auc`'s window stage. How it grows is left to the builder,
provided the existing six metrics keep their behaviour and their tests.

## 6. Tests and validation

- **Against scikit-learn** (ADR 0016): each of the three metrics, under each
  `average`, on two and three classes, integer and text labels, and the sizes
  of `validation/_cases.py`. The exact answer is computed in pure Python with
  `Fraction` beside sqlearn, scikit-learn and numpy; the bounds are set from
  the first measurement, as for `accuracy`.
- **Edge cases**, each against scikit-learn: a class never predicted, a class
  never in the target, a perfect and a wholly wrong prediction, every
  `zero_division` value, one class only, and each refusal of §4.
- **In a search:** a search with `f1(average="macro")` gives the scores of
  `GridSearchCV(scoring="f1_macro")` given sqlearn's folds, as the
  model-selection area checks `accuracy`; and with `zero_division=nan` on
  folds where a class is missing, the same best setting as `GridSearchCV`.
- **Unit tests** through the public seam (`compute` and the call), named in
  `GLOSSARY.md` terms.

## 7. Documentation

- The metrics reference page gains the three metrics from their docstrings,
  each with an example that runs as a doctest.
- The tuning guide's metrics section names them and shows a call with
  `average=`.
- The scikit-learn name map gains `precision_score`, `recall_score`,
  `f1_score` and the scorer strings (`"f1_macro"` and the rest) beside their
  sqlearn forms.

## 8. Decisions to record

ADRs, written with the plan:

- A metric's settings: calling a metric returns a configured copy (§3).
- Metrics with a grouped stage: how the interface grows for per-class counts
  (§5), if the builder's shape is a decision rather than a detail.

## 9. Done when

- §2's examples run.
- §6's tests and validations pass in `just verify`, with results committed
  under `validation/sqlearn/metrics/`.
- §7's documentation builds.

## 10. Not in this spec

- `average="samples"`, which only means something for multilabel data;
  sqlearn has none.
- `labels=` (scoring a chosen subset of classes) and `sample_weight=`.
- `fbeta_score`, `precision_recall_fscore_support`, the confusion matrix,
  the classification report, and curves (ROC, precision–recall).
- More regression metrics.

Each can come in a later slice; none is needed for the four common scores.

## 11. Left to the builder

- Module layout (a new `classification.py` beside `accuracy.py`, or not),
  internal names and message text beyond ADR 0019's form.
- How `Metric` grows to hold the settings and the grouped stage (§5).
- Whether the averaging runs in Python or SQL.
- The warning class's name.
