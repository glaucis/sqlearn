"""
Tune a model over kept folds
============================

The model-selection script, scaled down: a pipeline whose model reads text as
categories, tuned by a random search then by Optuna over stratified folds,
scored by the log loss. The folds' prepared rows are kept in a DuckDB file,
so the second search prepares nothing. Last, a model that learns in pieces
is trained on a stream of batches, as it would be on data larger than memory.
"""

import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import SGDClassifier

import sqlearn as sq

# %%
# Make 5,000 customers: two numbers with gaps, a city and a plan as text, and
# ``target``, whether the customer churned. Write them to Parquet. Your own
# data would start here.

rng = np.random.default_rng(0)
rows = 5_000
customers = pd.DataFrame(
    {
        "age": rng.normal(40, 12, rows),
        "income": np.exp(rng.normal(10.5, 0.5, rows)),
        "city": rng.choice(["Oslo", "Lima", "Kyoto", "Cairo"], rows),
        "plan": rng.choice(["basic", "plus", "pro"], rows, p=[0.5, 0.3, 0.2]),
    }
)
signal = (
    0.04 * (customers["age"] - 40)
    + 0.8 * (customers["income"] < customers["income"].median())
    + 0.5 * (customers["plan"] == "basic")
)
customers["target"] = (rng.random(rows) < 1 / (1 + np.exp(1 - signal))).astype(int)
customers.loc[rng.random(rows) < 0.1, "age"] = np.nan
customers.loc[rng.random(rows) < 0.05, "income"] = np.nan

folder = Path(tempfile.mkdtemp())
duckdb.from_df(customers).to_parquet(str(folder / "train.parquet"))

# %%
# The model is scikit-learn's histogram boosting, handed a pandas frame: the
# city and the plan reach it as categories, with no encoding step.

pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.Model(
            HistGradientBoostingClassifier(
                categorical_features="from_dtype", max_iter=30
            ),
            feed="pandas",
        ),
    ]
)
params = {
    "model__max_depth": sq.search.range(2, 8),
    "model__learning_rate": sq.search.range(0.01, 0.3, log=True),
}

# %%
# A random search of eight settings over five stratified folds. Each fold is
# prepared once and written to ``kept.duckdb``.

kept = folder / "kept.duckdb"
search = sq.search(
    pipe,
    params=params,
    method=sq.search.random(trials=8, seed=0),
    folds=sq.folds.stratified(5, seed=0),
    metric=sq.metrics.log_loss,
    keep_prepared=kept,
)
search.train(str(folder / "train.parquet"), target="target")
print(search.best_params_, round(search.best_score_, 4), search.transforms_)

# %%
# Optuna on the same data, steps and folds: it reads every fold back from the
# file, so it prepares nothing (``transforms_`` is 0).

search = sq.search(
    pipe,
    params=params,
    method=sq.search.optuna(trials=8, seed=0),
    folds=sq.folds.stratified(5, seed=0),
    metric=sq.metrics.log_loss,
    keep_prepared=kept,
)
search.train(str(folder / "train.parquet"), target="target")
print(search.best_params_, round(search.best_score_, 4), search.transforms_)
sq.store.prepared(kept)

# %%
# A model with ``partial_fit`` learns from one batch of 500 rows at a time:
# memory holds a batch, never the data. The stream takes numbers, so the
# text is one-hot encoded first.

stream = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.encode.onehot(),
        sq.Model(SGDClassifier(loss="log_loss"), feed="stream", rows=500),
    ]
)
stream.train(str(folder / "train.parquet"), target="target")
stream.predict(str(folder / "train.parquet"), out="pandas").head()
