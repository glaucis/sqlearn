---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [select, feature-selection, variancethreshold, selectkbest, selectpercentile, f_classif, f_regression, chi2, search, scikit-learn]
summary: "How sq.select drops columns that tell a model nothing: variance, best and percentile feature selectors, the f_classif, f_regression and chi2 scores, a search over k that learns each fold once, and the edge rules (no column left, missing values)."
related: [docs/specs/library-feature-selection.md, docs/adr/0055-a-target-step-need-not-cross-fit.md, docs/adr/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md, docs/guide/tuning-a-model.md, docs/guide/making-features.md]
---

# Selecting features

Wide data carries columns that tell a model nothing: one that never changes, or
one with no relation to the target. `sq.select` drops them before the model, so
training is cheaper and the model simpler. The scores are computed in DuckDB,
where the data is, so selection works on data larger than memory; what comes
back to Python is a few numbers per column.

A step of `sq.select` is a **feature selector**. It keeps some columns and
drops the rest; a column kept passes through unchanged (name, type and values).

| shortcut | keeps | scikit-learn |
|---|---|---|
| `sq.select.variance(threshold=0.0)` | columns whose variance is above `threshold` | `VarianceThreshold` |
| `sq.select.best(k=10, score="f_classif")` | the `k` columns with the highest score | `SelectKBest` |
| `sq.select.percentile(percentile=10, score="f_classif")` | the best `percentile` percent by score | `SelectPercentile` |

The shortcuts are presets of the general form,
`sq.select(*names, method="variance" | "best" | "percentile", ...)`, which
refuses a setting that does not belong to the method. By default a feature
selector works on the numeric columns, and refuses a chosen column that is not
numeric (encode it first).

```{code-cell} python
import numpy as np
import pandas as pd

import sqlearn as sq

rng = np.random.default_rng(0)
n = 60
kind = np.repeat(["a", "b", "c"], 20)
data = pd.DataFrame(
    {
        "flat": 1.0,
        "signal": (kind == "a") * 2.0 + rng.normal(size=n),
        "weak": (kind == "b") * 0.3 + rng.normal(size=n),
        "noise": rng.normal(size=n),
        "kind": kind,
    }
)
```

## Variance

`variance` learns each column's variance and keeps the columns above the
threshold. It does not read the target. At `threshold=0.0` it drops constant
columns:

```{code-cell} python
pipe = sq.Pipeline([sq.select.variance()]).learn(data)
pipe.columns_out_, pipe["variance"].variances_
```

Missing values are ignored when the variance is computed. A negative threshold
is refused at the call.

## Best and percentile

`best` and `percentile` score each column against the target, so `learn` needs
it: `learn(data, target="kind")`, as for `sq.encode.target`. Without a target,
`learn` refuses them. `best` keeps the `k` highest scores, `k="all"` keeps every
column; `percentile` keeps the columns whose score is in the top
`percentile` percent.

```{code-cell} python
numbers = data.drop(columns="flat")
best = sq.Pipeline([sq.select.best(k=2)]).learn(numbers, target="kind")
best.columns_out_, best["best"].scores_
```

```{code-cell} python
top = sq.Pipeline([sq.select.percentile(percentile=50)]).learn(
    numbers, target="kind"
)
top.columns_out_
```

The scores are readable as `scores_`, keyed by column. sqlearn does not compute
scikit-learn's `pvalues_`: nothing here selects by p-value.

## The scores

`score=` is a name, so a saved pipeline stays plain data.

| `score=` | target | scores each column by |
|---|---|---|
| `"f_classif"` | classes, of any type | the ANOVA F between the classes |
| `"f_regression"` | a number | the F of the correlation with the target |
| `"chi2"` | classes | observed against expected sums: for counts and frequencies |

`chi2` refuses a negative value in a scored column; scale to 0 up first
(`sq.scale.minmax()`) or use `f_classif`. A constant column scores NaN for
`f_classif`, which ranks lowest, and sqlearn warns once, naming the constant
columns. For `f_regression` a constant column, or a constant target, scores 0.

Ties are broken as scikit-learn breaks them: among equal scores the later
column is kept. A NaN score ranks lowest.

sqlearn combines what it learned exactly, so where scikit-learn's own rounding
departs from the exact score (a column far from zero, such as 1e6 plus noise;
a constant 0.1), sqlearn gives the exact score, and the columns kept can then
differ from scikit-learn's.

## In a pipeline

A feature selector learns on the rows `train` is given, once: it has no `cv` and
no `seed`, unlike `sq.encode.target`, which cross-fits
([ADR 0055](../adr/0055-a-target-step-need-not-cross-fit.md)). A later step sees
only the kept columns.

```{code-cell} python
from sklearn.linear_model import LogisticRegression

pipe = sq.Pipeline(
    [
        sq.select.variance(),
        sq.select.best(k=2, score="f_classif"),
        LogisticRegression(),
    ]
)
pipe.train(data, target="kind")
pipe.predict(data.drop(columns="kind"), out="pandas").head(3)
```

## Searching over k

A search over `k`, `percentile` or `threshold` learns each fold's scores once
and keeps 5, 10 or 20 columns from them
([ADR 0056](../adr/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md)):
those settings change only which columns are kept, never what is learned.
`score` changes what is learned, so a search over `score` learns per setting.

```{code-cell} python
search = sq.search(
    sq.Pipeline([sq.select.best(k=1), LogisticRegression()]),
    params={"best__k": [1, 2, 3]},
)
search.train(numbers.assign(kind=data["kind"]), target="kind")
search.best_params_
```

## Edge rules

- **No column left.** `k=0` or `percentile=0` keeps none and warns, as
  scikit-learn does, so long as other columns pass beside the feature selector.
  When it would leave no column at all, `learn` raises with a `Fix:` line: a
  table needs a column and a model a feature. `variance` raises likewise when no
  column's variance is above the threshold, naming the largest variance learned.
  In a search, that setting fails the search, naming the setting and the fold.
- **`k` too large.** `k` above the number of columns keeps them all and warns.
  A negative or non-whole `k` is refused at the call, and so is `True` or
  `False`, which scikit-learn reads as 1 and 0.
- **Missing values.** A missing (NULL or NaN) or infinite value in a column
  scored by `best` or `percentile` is refused, as is a missing target value;
  impute first with `sq.impute`. `variance` ignores missing values but refuses
  an infinite one, as scikit-learn's `VarianceThreshold` does.

```{code-cell} python
holes = numbers.assign(signal=numbers["signal"].where(numbers.index != 3))
try:
    sq.Pipeline([sq.select.best(k=1)]).learn(holes, target="kind")
except sq.errors.StepError as error:
    print(error)
```

## Not here

Mutual information, selection by a model (`SelectFromModel`, `RFE`), selection
by p-value (`SelectFpr` and kin) and `r_regression` are not in sqlearn's feature
selectors.
