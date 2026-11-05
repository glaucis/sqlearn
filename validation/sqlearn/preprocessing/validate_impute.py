"""Validate Impute's fill values: the median and the mean of the present values.

Each dataset's fill value is compared with the canonical value (ADR 0016):
the exact median or mean as a `Fraction`, both rational. Beside sqlearn:
DuckDB's ``median`` and ``favg`` alone and at one thread, numpy's
``nanmedian`` and ``nanmean``, scikit-learn's ``SimpleImputer`` and pandas.
"""

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: median 0
# ULPs everywhere; mean 119 ULPs on the large set with DuckDB's plain `avg`,
# tightened to 1 when the mean moved to the compensated `favg` (ADR 0033),
# worst then 1 ULP (medium set).
BOUNDS = {"median": 1, "mean": 1}

DUCKDB = {"median": "median", "mean": "favg"}
NUMPY = {"median": np.nanmedian, "mean": np.nanmean}
EXACT = {"median": _cases.exact_median, "mean": _cases.exact_mean}


def _sqlearn(data: _cases.Dataset, strategy: str) -> float:
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    step = sq.Impute(cols=[data.column], strategy=strategy)
    pipe = sq.Pipeline([("impute", step)]).learn(rel)
    return pipe["impute"].value_[data.column]


def _sklearn(data: _cases.Dataset, strategy: str) -> float:
    imputer = SimpleImputer(strategy=strategy).fit(_cases.as_nan(data.values)[:, None])
    return imputer.statistics_[0]


def _pandas(data: _cases.Dataset, strategy: str) -> float:
    series = pd.Series(_cases.as_nan(data.values))
    return series.median() if strategy == "median" else series.mean()


def cases() -> list[dict]:
    """Return Impute's cases: each strategy, dataset and reference."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        for strategy in ("median", "mean"):
            out += _cases.measure_all(
                step="impute",
                formula=strategy,
                data=data,
                type="DOUBLE",
                exact=EXACT[strategy](values) if values else None,
                bound=BOUNDS[strategy],
                answers={
                    "sqlearn": lambda d=data, s=strategy: _sqlearn(d, s),
                    "duckdb": lambda v=values, s=strategy: _cases.duckdb_alone(
                        DUCKDB[s], v, threads=None
                    ),
                    "duckdb, 1 thread": lambda v=values, s=strategy: (
                        _cases.duckdb_alone(DUCKDB[s], v, threads=1)
                    ),
                    "numpy": lambda d=data, s=strategy: NUMPY[s](
                        _cases.as_nan(d.values)
                    ),
                    "scikit-learn": lambda d=data, s=strategy: _sklearn(d, s),
                    "pandas": lambda d=data, s=strategy: _pandas(d, s),
                },
            )
    return out
