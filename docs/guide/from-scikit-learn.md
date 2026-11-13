---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [scikit-learn, migration, equivalents, pipeline, preprocessing, search, folds]
summary: "A table of every scikit-learn name sqlearn's preprocessing and model selection implement and its sqlearn counterpart, with the differences that matter."
related: [docs/specs/library-preprocessing.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0034-a-grouped-api.md]
---

# From scikit-learn

sqlearn follows scikit-learn's conventions
([ADR 0003](../adr/0003-scikit-learn-style-api.md)) with its own verbs: a step
`learn`s and `apply`s where a scikit-learn transformer `fit`s and
`transform`s. The table maps each scikit-learn name sqlearn implements to its
counterpart.

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
| `GridSearchCV(pipe, grid)` | `sq.search(pipe, params=grid)` |
| `RandomizedSearchCV(pipe, distributions, n_iter=50)` | `sq.search(pipe, params=..., method=sq.search.random(trials=50))` |
| `scipy.stats.loguniform(0.01, 10)` | `sq.search.range(0.01, 10, log=True)` |
| `KFold(5, shuffle=True)` | `sq.folds.kfold(5)` |
| `StratifiedKFold(5, shuffle=True)` | `sq.folds.stratified(5)` |
| `GroupKFold(5)` with `groups=customer` | `sq.folds.group("customer", 5)` |
| `TimeSeriesSplit(5, gap=0)` | `sq.folds.time("day", 5, gap=0)` |
| `PredefinedSplit(test_fold)` | a fold scheme of your own ([tuning a model](tuning-a-model.md)) |
| `scoring="accuracy"` | `metric=sq.metrics.accuracy` |
| `scoring="precision"`, `"recall"`, `"f1"` | `metric=sq.metrics.precision`, `recall`, `f1` |
| `scoring="f1_macro"` (and `"_micro"`, `"_weighted"`; the same for precision and recall) | `metric=sq.metrics.f1(average="macro")` |
| `fbeta_score(y, p, beta=2)` | `sq.metrics.fbeta(beta=2).compute(rel, "y", "p")` |
| `make_scorer(fbeta_score, beta=2)` | `metric=sq.metrics.fbeta(beta=2)` |
| `make_scorer(f1_score, pos_label="yes", zero_division=0.0)` | `metric=sq.metrics.f1(pos_label="yes", zero_division=0.0)` |
| `precision_score(y, p, average="macro")` | `sq.metrics.precision(average="macro").compute(rel, "y", "p")` |
| `confusion_matrix(y, p)` | `sq.metrics.confusion_matrix(rel, "y", "p", out="numpy")` (a relation by default) |
| `confusion_matrix(y, p, normalize="true")` | `sq.metrics.confusion_matrix(rel, "y", "p", normalize="true")` |
| `classification_report(y, p)` | `sq.metrics.classification_report(rel, "y", "p").show()` |
| `classification_report(y, p, output_dict=True)` | `sq.metrics.classification_report(rel, "y", "p", out="pandas")` (rows `label`, `accuracy`, `macro avg`, `weighted avg`) |
| `precision_recall_fscore_support(y, p)` | the class rows of `classification_report` (`precision`, `recall`, `f1_score`, `support`) |
| `scoring="neg_log_loss"` | `metric=sq.metrics.log_loss` |
| `scoring="roc_auc"` (`"roc_auc_ovr"` for more than two classes) | `metric=sq.metrics.roc_auc` |
| `scoring="neg_root_mean_squared_error"` | `metric=sq.metrics.rmse` |
| `scoring="neg_mean_absolute_error"` | `metric=sq.metrics.mae` |
| `scoring="r2"` | `metric=sq.metrics.r2` |

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
- **Scores keep their sign.** A metric where lower is better (`log_loss`,
  `rmse`, `mae`) is reported as it is, and the search keeps the lowest;
  scikit-learn negates it and keeps the highest.
- **Folds are dealt by value.** `sq.folds.kfold`, `stratified` and `group`
  deal rows by a hash of their values, so identical rows share a fold; the
  rows of a fold differ from scikit-learn's for the same seed. `group` does
  not balance fold sizes as `GroupKFold` does, and `time` never splits rows
  sharing a time between training and held-out rows.
- **`random` has its own sampler.** The same seed gives the same settings
  in sqlearn, not the settings `RandomizedSearchCV` would draw.

Each page of this guide for a group (imputing, scaling, encoding, binning,
transforming, making features) lists its own edge cases; [tuning a
model](tuning-a-model.md) and [handing data to
models](handing-data-to-models.md) cover the search and `sq.Model`.
