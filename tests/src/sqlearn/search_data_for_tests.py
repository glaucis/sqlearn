"""Data and a pipeline shared by the search tests."""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import sqlearn as sq


def customers(seed=0, rows=600):
    """Return the slice's data: two numbers with gaps, a city, a plan, churned."""
    rng = np.random.default_rng(seed)
    age = rng.normal(40, 12, rows)
    income = rng.normal(3000, 800, rows)
    city = rng.choice(["kyiv", "oslo", "rome"], rows)
    plan = rng.choice(["basic", "pro", "team"], rows)
    logit = (
        0.08 * (age - 40)
        - 0.002 * (income - 3000)
        + (city == "oslo") * 1.5
        - (plan == "team") * 1.0
    )
    churned = (rng.random(rows) < 1 / (1 + np.exp(-logit))).astype(int)
    age[rng.random(rows) < 0.1] = np.nan
    income[rng.random(rows) < 0.1] = np.nan
    return pd.DataFrame(
        {"age": age, "income": income, "city": city, "plan": plan, "churned": churned},
    )


def slice_pipe(model=None):
    """Return the slice's pipeline (spec §2)."""
    return sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric())),
            ("model", LogisticRegression() if model is None else model),
        ]
    )
