---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [features, polynomial, spline, polynomialfeatures, splinetransformer, scikit-learn]
summary: "How sq.features makes new columns from old ones: polynomial terms and B-spline bases, their names, where the bias column goes, and the knot vector."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md]
---

# Making features: polynomials and splines

`sq.features` creates columns from the numeric ones. Its two makers are presets
of the general form, `sq.features(columns, method="polynomial")`, and their
columns are named as scikit-learn names them
([ADR 0035](../adr/0035-names-of-generated-columns.md)).

| shortcut | creates | scikit-learn |
|---|---|---|
| `sq.features.polynomial(degree=2)` | every product up to the degree | `PolynomialFeatures` |
| `sq.features.spline(n_knots=5, degree=3)` | a B-spline basis per column | `SplineTransformer` |

## Polynomial

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame({"a": [2.0], "b": [3.0]})
pipe = sq.Pipeline([sq.features.polynomial()]).learn(data)
pipe.columns_out_, pipe.apply(data, out="pandas").to_numpy().tolist()
```

The names are `a^2` and `a*b`, in scikit-learn's order. `interaction_only=True`
leaves out the squares. It learns nothing, and each product reads several
columns of the row.

`include_bias=True` adds the column `1`, of ones. It goes **after** the inputs'
own terms, where scikit-learn puts it first, and it is off by default, since
the models sqlearn feeds fit their own intercept:

```{code-cell} python
biased = sq.Pipeline([sq.features.polynomial(include_bias=True)]).learn(data)
biased.columns_out_
```

## Spline

A spline replaces a column by `n_knots + degree - 1` columns, `x_sp_0`,
`x_sp_1` and so on, each a B-spline of the degree. The knots are learned, evenly
from the minimum to the maximum (`knots="uniform"`) or at the quantiles
(`knots="quantile"`).

```{code-cell} python
line = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
splined = sq.Pipeline([sq.features.spline(n_knots=3, degree=1)]).learn(line)
splined.columns_out_, splined.apply(line, out="pandas").to_numpy().tolist()
```

`knots_` is the **whole extended knot vector**: the `degree` knots added on each
side as well as the learned ones, as scikit-learn's `bsplines_[i].t` is.

```{code-cell} python
splined["spline"].knots_
```

Outside the first and last learned knots, each column holds its value at the
nearer end (`extrapolation="constant"`). A missing value or infinity is
refused when the rows are fetched, as scikit-learn's `handle_missing="error"`;
impute first.

## Other things to know

- Every created column is DOUBLE. These makers take no `suffix=`.
- A name that a column passing through already has is numbered, never refused.
