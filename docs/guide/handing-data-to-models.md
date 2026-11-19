---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [model, feed, pandas, polars, arrow, stream, partial-fit, categories, memory, catboost]
summary: "How sq.Model hands prepared data to a model from another library: the forms (numpy, pandas, Polars, Arrow, a stream through partial_fit), text columns as categories, streaming data larger than memory, and the memory budget that refuses a fold rather than swapping."
related: [docs/specs/library-model-selection.md, docs/adr/0041-the-hand-over.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/guide/tuning-a-model.md]
---

# Handing data to models

sqlearn prepares the data in DuckDB and hands it to a model you imported:
scikit-learn, CatBoost, XGBoost, LightGBM, any object with `fit` and
`predict` ([ADR 0017](../adr/0017-models-from-other-libraries.md)). sqlearn
never trains a model itself. How the prepared rows reach the model is its
**feed**, chosen on `sq.Model`
([ADR 0041](../adr/0041-the-hand-over.md)). A plain model at the end of a
pipeline is `sq.Model(model)`, with the default feed.

## The forms

| `feed=` | `fit(X, y)` gets | text columns |
|---|---|---|
| `"numpy"` (the default) | a 2-D float64 array | refused |
| `"pandas"` | a `DataFrame` | `category` dtype |
| `"polars"` | a `DataFrame` | `Enum` |
| `"arrow"` | a `pyarrow.Table` | dictionary-encoded |
| `"stream"` | one batch at a time, as numpy, through `partial_fit` | refused |

Each form comes from DuckDB's own method and its library is imported only
when used: none is a dependency of sqlearn, so install the one your model
reads (`uv add pandas`, `uv add polars`, `uv add pyarrow`). The target goes
over in the same form as the features: a numpy array, a pandas or Polars
`Series`, a `pyarrow.ChunkedArray`. A missing target is refused in every
form.

A model that shows what it is handed:

```{code-cell} python
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

import sqlearn as sq


class Peek(DummyClassifier):
    def fit(self, X, y):
        print(type(X).__name__, dict(X.dtypes.astype(str)), type(y).__name__)
        return super().fit(X, y)


data = pd.DataFrame(
    {
        "age": [20.0, 30.0, None, 50.0] * 5,
        "city": ["oslo", "rome", None, "oslo"] * 5,
        "churned": [0, 1, 0, 1] * 5,
    }
)
pipe = sq.Pipeline([sq.impute.median(), sq.Model(Peek(), feed="pandas")])
pipe.train(data, target="churned");
```

## Text columns reach the model as categories

With pandas, Polars and Arrow, a text column needs no encoding step: it
arrives as a category, the form CatBoost, LightGBM, XGBoost
(`enable_categorical=True`) and scikit-learn's histogram boosting
(`categorical_features="from_dtype"`) read. A NULL stays missing (NaN or
null), never a category of its own.

```{code-cell} python
from sklearn.ensemble import HistGradientBoostingClassifier

model = HistGradientBoostingClassifier(categorical_features="from_dtype")
pipe = sq.Pipeline([sq.impute.median(), sq.Model(model, feed="pandas")])
pipe.train(data, target="churned").predict(data, out="pandas").head(4)
```

- **Text is `VARCHAR` (with any collation) or an `ENUM`.** An `ENUM`
  column keeps its declared values in their declared order as its
  categories, whether or not a fold or batch holds them all, so every fold
  and every prediction batch codes it alike.
- **Codes stay fixed.** Training records each text column's categories,
  sorted; every prediction batch is cast with that list first and any new
  values after it, sorted. A known value keeps its code from training to
  prediction, and a new one is never dropped to missing. A model that reads
  the codes rather than the values reads the same code for a value at train
  and at predict.
- **Polars gets an `Enum`**, not a `Categorical`: an `Enum`'s codes are its
  list's order and survive `to_arrow` and `to_pandas`, where a
  `Categorical`'s follow the order values were first seen in the process.
- **CatBoost** still takes `cat_features=` as it would without sqlearn, and
  refuses a missing category: fill text first, with
  `sq.impute("city", value="mode")` say.

```python
from catboost import CatBoostClassifier

pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.Model(CatBoostClassifier(verbose=0, cat_features=["city"]), feed="pandas"),
    ]
)
```

## The stream: models that learn in pieces

`feed="stream"` streams the prepared rows from DuckDB in Arrow batches and
calls `partial_fit(X, y)` once per batch, scikit-learn's convention for
learning in pieces. Memory holds one batch, never the whole data, so a model
with `partial_fit` (`SGDClassifier`, `SGDRegressor`, `MLPClassifier`, ...)
trains on data larger than memory. It needs pyarrow.

```{code-cell} python
from sklearn.linear_model import SGDClassifier

rng = np.random.default_rng(0)
big = pd.DataFrame({"x": rng.normal(size=10_000)})
big["y"] = (big["x"] + rng.normal(scale=0.5, size=10_000) > 0).astype(int)
stream = sq.Pipeline(
    [
        sq.scale.standard(),
        sq.Model(SGDClassifier(loss="log_loss"), feed="stream", rows=1_000),
    ]
)
stream.train(big, target="y").predict(big.head(5), out="pandas")
```

| setting | default | does |
|---|---|---|
| `rows=` | | the rows in each batch |
| `megabytes=` | about 100 MB | the size of each batch, its rows worked out from a row's width; not with `rows=` |
| `epochs=` | `1` | the passes over the data |
| `shuffle=` | `True` | each epoch streams the rows in the order of a hash of the row, the seed and the epoch, so data sorted by date or class does not train badly; `False` keeps the input's order |
| `seed=` | `0` | the seed of that order: the same seed, the same orders |

The first call is given `classes=` (the sorted distinct targets, computed in
SQL) when `partial_fit` takes it. A model without `partial_fit`, a text
column, a missing target and a missing pyarrow are refused before the first
batch. The stream hands numbers, as numpy does: encode text with a step
(`sq.encode.onehot()`) before it.

## Predictions are always streamed

`predict` hands the model one batch at a time, whatever the feed, and writes
each batch's predictions back to DuckDB beside the batch's row numbers. In a
search, each fold's metric is then computed in SQL over the whole fold.
Prediction never needs the data in memory, and with
`out=sq.out.parquet("scored.parquet")` the predictions go straight to a
file. A later batch of a wider type widens the column (fractions after
whole numbers keep their fractions), and a batch of text after numbers, or
numbers after text, is refused.

## The memory budget: never swap

Before any form but the stream loads a fold into memory, sqlearn estimates
its size and compares it with the memory it may use. A fold that would not
fit is refused **before** the fetch: swapping is never the fallback.

```{code-cell} python
from sklearn.linear_model import LogisticRegression

rows = pd.DataFrame({"x": rng.normal(size=100_000), "y": [0, 1] * 50_000})
sq.set_config(memory="2MB")
try:
    sq.Pipeline([sq.Model(LogisticRegression())]).train(rows, target="y")
except sq.errors.SqlearnError as error:
    print(error)
sq.set_config(memory=None)
```

- **One budget for the process:** `sq.set_config(memory=...)`, bytes or a
  size such as `"8GB"`; by default 80% of the machine's physical memory (in
  a Linux container, capped by its cgroup's limit).
- **DuckDB's share.** sqlearn's own connection is given half the budget as
  DuckDB's `memory_limit`, and the hand-over may use the rest. A connection
  you pass with `sq.set_config(connection=...)` keeps its settings: its
  `memory_limit` counts as at most half the budget. When that limit is above
  half (DuckDB's default, 80% of memory, is), DuckDB and the hand-over
  together may use more than the budget, and a `SqlearnWarning` says so once
  per process; `SET memory_limit` on that connection to half the budget or
  less to stay within it. sqlearn adds one thing to a connection you pass:
  the first streamed prediction attaches `__sqlearn_feed`, a private in-memory
  database that stays attached and holds the predictions.
- **The estimate errs towards refusing:** each value counts twice, for the
  two copies a fetch holds at its peak; a number is 8 bytes, a text value 64
  bytes plus its column's average length; numpy and the stream add a byte a
  value for a possible mask.
- **Larger than memory.** The stream is the way: the slow test
  `test_the_stream_trains_larger_than_memory` trains and predicts 20 million
  rows (about 1 GB of numbers) with a 256 MB budget, on one DuckDB thread;
  each of training and predicting adds under 384 MB to the process's peak
  (about 130 to 280 MB measured), against 3.6 GB for training without the
  budget. At a small `memory_limit`, run DuckDB on fewer threads: each
  thread holds its own buffers, and eight of them in 128 MB run out of
  memory in a large sort. Pass a connection of your own for that:

  ```python
  con = duckdb.connect()
  con.execute("SET memory_limit = '128MB'")
  con.execute("SET threads = 1")
  sq.set_config(connection=con, memory="256MB")
  ```

## In a search

Each model in a search trains in its own feed: a fold's training rows are
fetched once per distinct form among its models, and one form's rows are in
memory at a time. A stream model streams each fold's training rows itself.
See [tuning a model](tuning-a-model.md).
