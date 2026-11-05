"""Validate Scale's learned values: the mean and the population standard deviation.

The mean's canonical value is exact (a `Fraction`); the standard deviation's
is the square root of the exact variance at 50 digits with mpmath (ADR
0016). The divisor counts a standard deviation of 0 as 1, as sqlearn and
scikit-learn do; every reference's answer goes through the same rule so the
comparison stays like for like. Beside sqlearn: DuckDB's ``favg`` and
``stddev_pop`` alone and at one thread, numpy's ``nanmean`` and ``nanstd``,
scikit-learn's ``StandardScaler`` and pandas (``ddof=0``).
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: mean 119
# ULPs with DuckDB's plain `avg`; tightened to 1 when the mean moved to the
# compensated `favg` (ADR 0033), worst then 1 ULP (medium set). Standard
# deviation: 12 ULPs on the large set (`stddev_pop` alone shows the same).
BOUNDS = {"mean": 1, "scale": 16}

FORMULAS = {
    "mean": "mean",
    "scale": "population standard deviation, 0 counted as 1",
}
DIVISOR_NOTE = "a standard deviation of 0 counted as 1, as for sqlearn"


def _divisor(sd: float) -> float:
    return 1.0 if sd == 0 else sd


def _sqlearn(data: _cases.Dataset, what: str) -> float:
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    step = sq.Scale(cols=[data.column])
    learned = sq.Pipeline([("scale", step)]).learn(rel)["scale"]
    return (learned.mean_ if what == "mean" else learned.scale_)[data.column]


def _sklearn(data: _cases.Dataset, what: str) -> float:
    scaler = StandardScaler().fit(_cases.as_nan(data.values)[:, None])
    return (scaler.mean_ if what == "mean" else scaler.scale_)[0]


def _answers(data: _cases.Dataset, values: list[float], what: str) -> dict:
    if what == "mean":
        return {
            "sqlearn": lambda: _sqlearn(data, "mean"),
            "duckdb": lambda: _cases.duckdb_alone("favg", values, threads=None),
            "duckdb, 1 thread": lambda: _cases.duckdb_alone("favg", values, threads=1),
            "numpy": lambda: np.nanmean(_cases.as_nan(data.values)),
            "scikit-learn": lambda: _sklearn(data, "mean"),
            "pandas": lambda: pd.Series(_cases.as_nan(data.values)).mean(),
        }
    return {
        "sqlearn": lambda: _sqlearn(data, "scale"),
        "duckdb": lambda: _divisor(
            _cases.duckdb_alone("stddev_pop", values, threads=None)
        ),
        "duckdb, 1 thread": lambda: _divisor(
            _cases.duckdb_alone("stddev_pop", values, threads=1)
        ),
        "numpy": lambda: _divisor(np.nanstd(_cases.as_nan(data.values))),
        "scikit-learn": lambda: _sklearn(data, "scale"),
        "pandas": lambda: _divisor(pd.Series(_cases.as_nan(data.values)).std(ddof=0)),
    }


def _exact(values: list[float], what: str) -> object:
    if not values:
        return None
    if what == "mean":
        return _cases.exact_mean(values)
    sd = _cases.exact_stddev_pop(values)
    return sd if sd != 0 else 1


def cases() -> list[dict]:
    """Return Scale's cases: each learned value, dataset and reference."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        for what in ("mean", "scale"):
            out += _cases.measure_all(
                step="scale",
                formula=FORMULAS[what],
                data=data,
                type="DOUBLE",
                exact=_exact(values, what),  # type: ignore[arg-type]
                bound=BOUNDS[what],
                answers=_answers(data, values, what),
                notes={
                    r: DIVISOR_NOTE
                    for r in ("duckdb", "duckdb, 1 thread", "numpy", "pandas")
                    if what == "scale"
                },
            )
    return out
