"""
Search a pipeline over files
============================

The core's vertical slice: a pipeline of four preparation steps and a
scikit-learn model, searched over six settings with five-fold validation. The
data is generated here, written to Parquet in a temporary directory, and read
from there by DuckDB, so the preparation runs as SQL over the files.
"""

import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import sqlearn as sq

# %%
# Generate 10,000 rows: two numeric columns with some values missing, two
# categorical columns, and a 0/1 target that depends on them.

rng = np.random.default_rng(0)
n = 10_000
age = rng.normal(40, 12, n)
income = rng.lognormal(10.5, 0.5, n)
city = rng.choice(["Oslo", "Lima", "Kyoto", "Cairo"], n)
plan = rng.choice(["basic", "plus", "pro"], n, p=[0.5, 0.3, 0.2])
signal = (
    0.04 * (age - 40)
    - 0.8 * (income > np.median(income))
    + 0.9 * (plan == "basic")
    + 0.5 * (city == "Cairo")
    + rng.normal(0, 1, n)
)
frame = pd.DataFrame(
    {
        "age": np.where(rng.random(n) < 0.1, np.nan, age),
        "income": np.where(rng.random(n) < 0.05, np.nan, income),
        "city": city,
        "plan": plan,
        "churned": (signal > 0.4).astype(int),
    }
)

folder = Path(tempfile.mkdtemp())
duckdb.sql(f"COPY frame TO '{folder}/train.parquet' (FORMAT parquet)")

# %%
# The pipeline imputes the numeric columns, encodes the two categorical ones,
# scales every numeric column (including the one-hot columns) and ends in a
# model.

pipe = sq.Pipeline(
    [
        ("impute", sq.impute.median(cols=sq.cols.numeric())),
        ("onehot", sq.OneHot(cols=["city"])),
        ("ordinal", sq.Ordinal(cols=["plan"])),
        ("scale", sq.scale.standard(cols=sq.cols.numeric())),
        ("model", LogisticRegression()),
    ]
)

# %%
# Search two imputer settings and three values of ``C``. The imputer and the
# scaler learn once per fold and imputer setting; changing only ``C`` learns
# nothing new.

search = sq.Search(
    pipe,
    params={"model__C": [0.1, 1, 10], "impute__value": ["median", "mean"]},
    metric=sq.metrics.accuracy,
)
search.train(str(folder / "*.parquet"), target="churned")
print(search.best_params_, search.best_score_)
search.results_.show(max_rows=6)
