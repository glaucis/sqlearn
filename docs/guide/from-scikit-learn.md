---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [scikit-learn, migration, equivalents, pipeline, preprocessing]
summary: "A table of every scikit-learn name sqlearn's preprocessing implements and its sqlearn counterpart, with the differences that matter."
related: [docs/specs/library-preprocessing.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0034-a-grouped-api.md]
---

# From scikit-learn

sqlearn follows scikit-learn's conventions
([ADR 0003](../adr/0003-scikit-learn-style-api.md)) with its own verbs: a step
`learn`s and `apply`s where a scikit-learn transformer `fit`s and
`transform`s. The table maps each scikit-learn name this area implements to
its counterpart.

| scikit-learn | sqlearn |
|---|---|
| `make_pipeline(a, b)` | `sq.Pipeline([a, b])` |
| `SimpleImputer(strategy="mean")` | `sq.impute.mean()` |
| `SimpleImputer(strategy="median")` | `sq.impute.median()` |
| `SimpleImputer(strategy="most_frequent")` | `sq.impute.mode()` |
| `SimpleImputer(strategy="constant", fill_value=0)` | `sq.impute.constant(0)` |
| `SimpleImputer(add_indicator=True)` | `sq.impute(..., indicator=True)` |
| `MissingIndicator()` | `sq.impute.indicator()` |
| `StandardScaler()` | `sq.scale.standard()` |
| `RobustScaler()` | `sq.scale.robust()` |
| `RobustScaler(quantile_range=(10, 90))` | `sq.scale.robust(quantile_range=(10, 90))` |
| `MinMaxScaler(feature_range=(-1, 1))` | `sq.scale.minmax(feature_range=(-1, 1))` |
| `MaxAbsScaler()` | `sq.scale.maxabs()` |
| `Normalizer(norm="l2")` | `sq.scale.normalize(norm="l2")` |
| `OneHotEncoder(handle_unknown="ignore")` | `sq.encode.onehot()` |
| `OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)` | `sq.encode.ordinal()` |
| `TargetEncoder(smooth="auto", cv=5)` | `sq.encode.target(smooth="auto", cv=5)` |
| `KBinsDiscretizer(strategy="uniform", encode="ordinal")` | `sq.bin.uniform()` |
| `KBinsDiscretizer(strategy="quantile", encode="ordinal")` | `sq.bin.quantile()` |
| `Binarizer(threshold=0.0)` | `sq.bin.binarize()` |
| `FunctionTransformer(np.log)` | `sq.transform.log()` |
| `FunctionTransformer(np.log1p)` | `sq.transform.log1p()` |
| `FunctionTransformer(np.sqrt)` | `sq.transform.sqrt()` |
| `FunctionTransformer(np.clip, kw_args={"a_min": 0, "a_max": 1})` | `sq.transform.clip(lower=0, upper=1)` |
| `PolynomialFeatures(degree=2)` | `sq.features.polynomial(degree=2)` |
| `SplineTransformer(n_knots=5, degree=3)` | `sq.features.spline(n_knots=5, degree=3)` |

For example, scikit-learn's

```python
make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
```

is

```{code-cell} python
import pandas as pd
import sqlearn as sq

pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard()])
data = pd.DataFrame({"x": [1.0, None, 3.0, 5.0]})
pipe.learn(data).apply(data, out="pandas")
```

## What differs

- **Verbs.** `learn` and `apply` for steps, `train` and `predict` for models.
  The result of `apply` is a lazy DuckDB relation, not an array.
- **Columns first.** A step takes the columns it works on as its first
  arguments: `sq.scale.robust("age", "income")`. With none, it works on the
  columns its kind suits.
- **Indicators.** `sq.impute(..., indicator=True)` puts each `<column>_missing`
  right after its own column; scikit-learn puts all the indicators last. A
  dict step cannot carry an indicator.
- **Names.** Created columns are named `<column>_<label>`, and the missing
  category is `<column>_NULL`, where scikit-learn says `_nan`. A clash is
  numbered, never refused ([column names](column-names.md)).
- **Bad input is refused.** The log of 0 or the square root of -1 raises when
  the value is met, where numpy gives `-inf` or `nan` with a warning.
- **The bias column.** `sq.features.polynomial(include_bias=True)` puts the
  column `1` after the inputs' own terms, where scikit-learn puts it first; it
  is off by default.
- **Target encoding.** Cross-fitting happens in `train` only. Learn-then-apply
  does not cross-fit, and a text target is refused.

Each page of this guide for a group (imputing, scaling, encoding, binning,
transforming, making features) lists its own edge cases.
