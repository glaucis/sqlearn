---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [search, tuning, folds, metrics, optuna, random, grid, keep-prepared, cross-validation]
summary: "How sq.search tunes a model: the methods (grid, random, Optuna) and ranges, the fold schemes (kfold, stratified, group, time, holdout), the metrics, what a search returns, and keeping prepared folds in a file with keep_prepared."
related: [docs/specs/library-model-selection.md, docs/adr/0022-one-search-with-pluggable-methods.md, docs/adr/0039-the-search-names-as-groups.md, docs/adr/0040-fold-schemes-as-sql-over-rows.md, docs/guide/handing-data-to-models.md, docs/guide/inputs-and-the-store.md]
---

# Tuning a model

Tuning a model means choosing its settings by trying them over folds and
keeping the best. `sq.search` does it for a pipeline that ends in a model:
it tries each setting on each fold, scores it in SQL on the fold's held-out
rows, and trains the best setting on all the data. The preparation runs in
DuckDB, once per fold and preparation: settings that change only the model
share the fold's prepared rows.

```{code-cell} python
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import sqlearn as sq

rng = np.random.default_rng(0)
n = 1_000
age = rng.normal(40, 12, n)
income = rng.lognormal(10.5, 0.5, n)
data = pd.DataFrame(
    {
        "age": np.where(rng.random(n) < 0.1, np.nan, age),
        "income": income,
        "churned": (0.05 * (age - 40) - (income > 36_000) + rng.normal(0, 1, n) > 0)
        .astype(int),
    }
)
pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard(), LogisticRegression()])

search = sq.search(pipe, params={"model__C": [0.01, 0.1, 1.0]})
search.train(data, target="churned")
search.best_params_, round(search.best_score_, 3)
```

Settings are named `step__setting`, as in scikit-learn: `model__C` is the
model's `C`. A step without a name of its own is named after its shortcut
(`median`, `standard`, `onehot`), and the model is `model`, so
`median__value` is the imputer's value. The model's own name, `"model"`,
takes a list of models to choose between.

## Methods: how settings are picked

`method=` says which settings are tried. Every method is seeded: the same
seed gives the same settings and the same `results_`, byte for byte.

| method | tries | for |
|---|---|---|
| `sq.search.grid()` (the default) | every combination of the lists | a few settings |
| `sq.search.random(trials=50, seed=0)` | `trials` settings drawn from lists and ranges | many settings, or ranges |
| `sq.search.optuna(trials=100, sampler=None, seed=0)` | `trials` settings, each chosen by Optuna from the scores before it | costly models |

A list gives its values; `sq.search.range(low, high, log=False)` gives a
span of numbers, drawn uniformly (log-uniformly with `log=True`), whole
numbers when both bounds are whole. The grid takes lists only and refuses a
range.

```{code-cell} python
search = sq.search(
    pipe,
    params={"model__C": sq.search.range(0.001, 100.0, log=True)},
    method=sq.search.random(trials=4, seed=0),
)
search.train(data, target="churned")
search.results_.order("fold, setting").limit(4)
```

Optuna (`uv add optuna`, imported only when used) picks one setting at a
time from what it has learned: lists become its categorical distributions,
ranges its float or integer ones. `sampler=` takes any Optuna sampler
(`optuna.samplers.TPESampler()`, say); by default Optuna's own, seeded with
`seed`.

## Folds: which rows train and which are scored

`folds=` takes a fold scheme from `sq.folds`. A scheme says, as SQL over the
rows, which rows each fold trains on and which it holds out
([ADR 0040](../adr/0040-fold-schemes-as-sql-over-rows.md)): no fold column
is stored, and the answer is the same in every query.

| scheme | rows of fold k | for |
|---|---|---|
| `sq.folds.kfold(n=5, seed=0)` (the default) | dealt by a hash of the row's values and the seed | most data |
| `sq.folds.stratified(n=5, seed=0)` | each class of the target dealt evenly across the folds | classification |
| `sq.folds.group(by, n=5, seed=0)` | every row of a group (a customer, say) in one fold | rows that are not independent |
| `sq.folds.time(by, n=5, gap=0)` | held out: the k-th later period of `by`; trained on everything before | data ordered in time |
| `sq.folds.holdout(test=0.2, seed=0)` | one split, about `test` of the rows held out, by a hash | a quick check |

- `kfold`, `stratified` and `group` deal by value, so identical rows always
  share a fold and are never both trained on and scored.
- `stratified` keeps each class's share in every fold to within a row when
  no row repeats. Identical rows move together, so with repeated rows the
  shares and fold sizes vary with how many times each row repeats.
- `group` deals the groups by a hash, so fold sizes vary with the groups'
  sizes; scikit-learn's `GroupKFold` balances them instead.
- `time` cuts the rows, ordered by `by`, into `n + 1` chunks of equal row
  counts, as scikit-learn's `TimeSeriesSplit` does: fold k holds out chunk
  k + 1 and trains on the chunks before it, less `gap` rows. Rows sharing a
  value of `by` always fall on one side: a boundary moves to the end of its
  tie. `by` may not be NULL.

```{code-cell} python
data["day"] = range(n)
search = sq.search(
    pipe, params={"model__C": [0.1, 1.0]}, folds=sq.folds.time("day", n=4, gap=10)
)
search.train(data, target="churned").results_.filter("setting LIKE '%0.1%'")
```

A scheme of your own is any object with the members of
`sqlearn.model_selection.Folds`: `splits`, `key`, `numbered`, `training` and
`held`. This is how scikit-learn's `PredefinedSplit` is written in sqlearn:
number the rows with a column you already have, and say which rows each
fold holds out.

## Metrics

`metric=` is the score, computed in SQL over each fold's held-out rows. The
default is `sq.metrics.accuracy`.

| metric | kind | better |
|---|---|---|
| `sq.metrics.accuracy` | classification | higher |
| `sq.metrics.log_loss` | classification, from `predict_proba` | lower |
| `sq.metrics.roc_auc` | classification, from `predict_proba` | higher |
| `sq.metrics.rmse`, `sq.metrics.mae` | regression | lower |
| `sq.metrics.r2` | regression | higher |

`log_loss` and `roc_auc` read the model's probabilities, one column per
class in the order of its `classes_`; with more than two classes `roc_auc`
is one-vs-rest, averaged over the classes (scikit-learn's
`multi_class="ovr"`, `average="macro"`). A metric that needs probabilities
refuses a model without `predict_proba` before any work. Where lower is
better, the best setting is the lowest.

## What a search gives back

| attribute | holds |
|---|---|
| `best_params_` | the best setting; on a tie, the first the method tried |
| `best_score_` | its score, the mean over the folds |
| `results_` | a DuckDB relation: `setting` (JSON text), `fold`, `score` |
| `best_pipeline_` | a copy of the pipeline with the best setting, trained on all data |
| `transforms_` | how many times a fold's data was prepared |
| `used_` | for `params`, `method` and `folds`: given, or the default used |

`search.predict(data, out=...)` predicts with `best_pipeline_`. The pipeline
given to `sq.search` is never changed: every trial runs on a copy.

## Keeping prepared folds: `keep_prepared`

Within one `train`, each fold's prepared rows live in a temporary table for
that call, so trials sharing a preparation read them again rather than
prepare them: a grid prepares each (preparation, fold) once, and Optuna,
which tries one setting at a time, keeps the current preparation's tables
and drops the others when it asks for a different one, so the temporary
tables hold one preparation's folds at most. The tables are dropped when
`train` returns, so a later search, in this session or another, prepares
the folds again. With `keep_prepared="project.duckdb"`, each fold's
prepared rows are written once to that DuckDB file and read back by every
later trial and search on the same data, steps and folds:

```python
search = sq.search(
    pipe,
    params={"model__C": sq.search.range(0.001, 100.0, log=True)},
    method=sq.search.optuna(trials=40, seed=0),
    keep_prepared="project.duckdb",
)
search.train("data/train/*.parquet", target="churned")
search.transforms_  # 5: each fold prepared once, then read for 40 trials
```

The file keeps every preparation it is given, by design: an Optuna search
over the steps' settings writes one set of folds per preparation it tries,
and the file grows with them. `sq.store.prepared(path)` lists what is kept,
and `sq.store.clear(prepared=path)` empties the file when it is no longer
wanted.

A kept table is found by a key of the data, the target, the steps and their
settings, the folds and the versions, the same in every process. What the
key cannot see (a table edited in place, a change to the code of a step of
your own) and how to clear the file with `sq.store.clear(prepared=path)` are
in [inputs and the store](inputs-and-the-store.md).

## From scikit-learn

The search's names beside scikit-learn's are in
[from scikit-learn](from-scikit-learn.md). Given sqlearn's folds
(`PredefinedSplit`) and, for random, the settings sqlearn drew as a fixed
list, `GridSearchCV` gives the same scores and best settings; the fold
schemes deal rows differently from their scikit-learn twins and are checked
against them on what defines each: class balance, groups kept together, the
order in time kept. The validation runner
`validation/pipelines/validate_model_selection.py` records both.
