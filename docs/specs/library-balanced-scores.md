---
type: spec
tags: [metrics, balanced-accuracy, mcc, brier, imbalanced-classes, library-breadth]
summary: "Short spec for three more scores in sq.metrics: balanced accuracy, the Matthews correlation coefficient (mcc) and the Brier score (brier), computed in SQL and matching scikit-learn 1.9.1, usable in a search."
related: [docs/specs/library-metrics.md, docs/specs/library-more-metrics.md, docs/adr/0042-a-metrics-settings-are-a-call.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0016-validation-method.md]
---
# Library breadth: balanced scores

The seventh area of part 3.3 of [the overview](../architecture/overview.md):
three more scores after [more metrics](library-more-metrics.md).

Status: approved by Tomas on 2026-11-19 as a short design. Issue #62.

## 1. Purpose

On imbalanced data, accuracy flatters. With 95 negatives and 5 positives, a
model that always says "no" scores 0.95 accuracy. Balanced accuracy gives it
0.5 and the Matthews correlation coefficient 0.0: no better than guessing. The
Brier score checks the probabilities themselves, beside `log_loss`. Each is one
number, so a search can rank by it.

## 2. What it looks like

```python
sq.metrics.balanced_accuracy.compute(rows, "target")
sq.metrics.balanced_accuracy(adjusted=True).compute(rows, "target")
sq.metrics.mcc.compute(rows, "target")
sq.metrics.brier.compute(rows, "target", classes=pipe.classes_)
sq.search(pipe, params=..., metric=sq.metrics.mcc)
```

## 3. Rules

The two rules of the earlier metrics hold:

1. **They behave as scikit-learn 1.9.1's** `balanced_accuracy_score`,
   `matthews_corrcoef` and `brier_score_loss`: the same numbers, defaults and
   settings. Where this text and scikit-learn disagree, scikit-learn is built
   and this spec is corrected.
2. **Everything is computed in SQL** by DuckDB; what comes back is a few counts
   per class or one number.

Settings are a call ([ADR 0042](../adr/0042-a-metrics-settings-are-a-call.md)),
and the message of `Metric.__call__` that lists the metrics with settings names
these too.

## 4. The three scores

- **`balanced_accuracy`**, setting `adjusted=False`: the mean recall over the
  target's classes; `adjusted=True` rescales it so chance scores 0. Higher is
  better. A predicted class not in the target is warned about, as scikit-learn
  warns. `adjusted=True` on a target with one class gives minus infinity in
  scikit-learn; sqlearn returns the same, with a warning saying why and a
  `Fix:` line ([ADR 0046](../adr/0046-sqlearn-warns-the-user-chooses.md)).
- **`mcc`**: the Matthews correlation coefficient from the confusion counts,
  for two classes or more. It takes no settings. Higher is better. Where its
  denominator is 0 it is 0.0, as in scikit-learn.
- **`brier`**, setting `scale_by_half="auto"` (`True`, `False` or `"auto"`):
  the mean over rows of the sum, over the classes, of the squared difference
  between a class's probability and 1 for the row's class, 0 for the others.
  It is halved when `scale_by_half=True`, or `"auto"` with two classes. It
  reads the `__sqlearn_proba_<i>` columns and the model's classes, as
  `log_loss` does, so a class absent from the scored rows is not refused.
  Lower is better.
- **Corrected after a probe of scikit-learn 1.9.1 (2026-11-19):** given every
  probability column, as sqlearn always has them, `brier_score_loss` gives the
  same number whatever `pos_label=` and `labels=` say, and the classes come
  from the model. So `brier` takes neither: a setting that changes nothing is
  not copied.

## 5. Checks

- Validation against scikit-learn and against exact fractions, in the
  validation runners of the modules the scores land in (ADR 0016).
- Tests through the public calls, named in the glossary's terms.
- A section in the guide's "Evaluating a model" page, the reference pages, and
  the docstrings' examples.

## 6. Names

`mcc` and `brier` are short, as `mae` and `r2` are: the spec's call, which
Tomas did not overrule. `balanced_accuracy` keeps scikit-learn's name without
`_score`, as `accuracy` does.

## 7. Left to the builder

Which modules the scores land in, how the counts are shared with the
existing classification metrics, and the exact warning texts. Any edge case
this text does not name follows scikit-learn 1.9.1, found by probing it.
