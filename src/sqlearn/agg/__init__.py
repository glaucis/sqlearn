"""Aggregates: what a step learns from a column, ``sq.agg.median`` and its kin.

Each is a value a step takes (``value=sq.agg.median``) and, given a column,
the expression a step learns (``{"m": sq.agg.median(x)}``). Missing values
(NULL, and NaN in a float column) are left out of every one.

Examples
--------
>>> import sqlearn as sq
>>> sq.agg.quantile(q=0.9)
sq.agg.quantile(q=0.9)
"""

from sqlearn.agg.aggregates import (
    Aggregate,
    approx_quantile,
    count,
    distinct,
    iqr,
    max,
    maxabs,
    mean,
    median,
    min,
    mode,
    quantile,
    range,
    std,
    var,
)

__all__ = [
    "Aggregate",
    "approx_quantile",
    "count",
    "distinct",
    "iqr",
    "max",
    "maxabs",
    "mean",
    "median",
    "min",
    "mode",
    "quantile",
    "range",
    "std",
    "var",
]
