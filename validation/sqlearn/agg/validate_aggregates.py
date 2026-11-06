"""Validate every aggregate of ``sq.agg`` against its exact value.

Each aggregate learns, through a one-step pipeline, from the numeric datasets
and is compared with the canonical value (ADR 0016): exact as a `Fraction`
where the answer is rational (the mean, quantiles, extremes, the variance),
the square root of the exact variance at 50 digits with mpmath for the
standard deviation. A quantile's ranks are found as numpy finds them (in
doubles), then its value is interpolated exactly. Beside sqlearn: DuckDB's
own function alone and at one thread, numpy, and pandas where they have one.

``approx_quantile`` has no bound: its error against the exact quantile is
recorded per dataset. The aggregates taking any type (mode, min, max, count,
distinct) are also learned from the text datasets and must agree exactly with
the canonical answer (a `collections.Counter` and `sorted`).
"""

import math
from collections import Counter
from collections.abc import Callable
from fractions import Fraction

import duckdb
import numpy as np
import pandas as pd

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: 0 ULPs
# for the quantiles, the median and the exact aggregates (mode, extremes,
# range, maxabs, count); 1 for the mean (medium set, as Impute's); 12 for the
# standard deviation and 20 for the variance (large set; DuckDB's
# `stddev_pop` and `var_pop` alone show the same, issue #28); 32 for the IQR
# (small set): each quantile is rounded at values near 1,000, and their
# difference, about 21, keeps those errors at its own finer ULPs, as every
# reference (DuckDB, numpy, pandas) shows the same 32.
BOUNDS = {
    "mean": 1,
    "median": 1,
    "quantile": 1,
    "iqr": 32,
    "mode": 1,
    "min": 1,
    "max": 1,
    "range": 1,
    "maxabs": 1,
    "std": 16,
    "var": 32,
    "count": 1,
}

QS = (0.1, 0.25, 0.9)
"""The quantiles validated, for each method."""


class Learn(sq.Step):
    """Learn one aggregate of each column; apply leaves the column."""

    def __init__(self, cols=None, value=sq.agg.mean, keep=False, suffix=None):
        """Set the settings."""
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.value = value

    def learn(self, x):
        """Learn the aggregate."""
        return {"v": self.value(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def _sqlearn(data: _cases.Dataset, aggregate: sq.agg.Aggregate, kind: str) -> object:
    rel = _cases.sqlearn_table({data.column: data.values}, kind)
    step = Learn(cols=[data.column], value=aggregate)
    return sq.Pipeline([("learn", step)]).learn(rel)["learn"].v_[data.column]


def _duckdb(sql: str, values: list, *, threads: int | None) -> object:
    """Run DuckDB's own SQL `sql` over the present values, on a fresh connection."""
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    rel = _cases.table(con, "data", {"x": tuple(values)}, "DOUBLE")
    return rel.aggregate(sql).fetchall()[0][0]


def _ranks(n: int, q: float, method: str) -> tuple[int, int, Fraction]:
    """Return the low and high ranks (from 1) and the weight, as numpy finds them."""
    if method == "linear":
        index = (n - 1) * q
        low = math.floor(index) + 1
        return low, min(low + 1, n), Fraction(index - math.floor(index))
    g = n * q
    if g == math.floor(g):
        return max(min(int(g), n), 1), max(min(int(g) + 1, n), 1), Fraction(1, 2)
    rank = max(min(math.ceil(g), n), 1)
    return rank, rank, Fraction(0)


def exact_quantile(values: list[float], q: float, method: str) -> Fraction:
    """Return the quantile: ranks as numpy's doubles find them, value exact."""
    ordered = sorted(Fraction(v) for v in values)
    low, high, weight = _ranks(len(ordered), q, method)
    lo, hi = ordered[low - 1], ordered[high - 1]
    return lo + weight * (hi - lo)


def exact_mode(values: list) -> object:
    """Return the most frequent value; a tie goes to the smallest."""
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)


def _pandas_mode(values: tuple) -> float:
    return float(pd.Series(_cases.as_nan(values)).mode().min())


def _references(name: str) -> tuple:
    """Return one numeric aggregate's exact value, DuckDB SQL, numpy and pandas."""
    return {
        "mean": (
            _cases.exact_mean,
            "favg(x)",
            lambda v: np.mean(v),
            lambda s: s.mean(),
        ),
        "median": (
            _cases.exact_median,
            "median(x)",
            lambda v: np.median(v),
            lambda s: s.median(),
        ),
        "iqr": (
            lambda v: (
                exact_quantile(v, 0.75, "linear") - exact_quantile(v, 0.25, "linear")
            ),
            "quantile_cont(x, 0.75) - quantile_cont(x, 0.25)",
            lambda v: np.quantile(v, 0.75) - np.quantile(v, 0.25),
            lambda s: s.quantile(0.75) - s.quantile(0.25),
        ),
        "mode": (lambda v: Fraction(exact_mode(v)), None, None, None),
        "min": (lambda v: Fraction(min(v)), "min(x)", np.min, lambda s: s.min()),
        "max": (lambda v: Fraction(max(v)), "max(x)", np.max, lambda s: s.max()),
        "range": (
            lambda v: Fraction(max(v)) - Fraction(min(v)),
            "max(x) - min(x)",
            np.ptp,
            lambda s: s.max() - s.min(),
        ),
        "maxabs": (
            lambda v: max(abs(Fraction(x)) for x in v),
            "max(abs(x))",
            lambda v: np.max(np.abs(v)),
            lambda s: s.abs().max(),
        ),
        "std": (
            _cases.exact_stddev_pop,
            "stddev_pop(x)",
            np.std,
            lambda s: s.std(ddof=0),
        ),
        "var": (
            _cases.exact_variance,
            "var_pop(x)",
            np.var,
            lambda s: s.var(ddof=0),
        ),
        "count": (
            lambda v: Fraction(len(v)),
            "count(x)",
            lambda v: np.count_nonzero(~np.isnan(v)),
            lambda s: s.count(),
        ),
    }[name]


def _measure(
    data: _cases.Dataset,
    formula: str,
    aggregate: sq.agg.Aggregate,
    bound: int,
    exact: Callable[[list], object],
    sql: str | None,
    numpy: Callable | None,
    pandas: Callable | None,
) -> list[dict]:
    values = _cases.present(data.values)
    answers: dict[str, Callable[[], object]] = {
        "sqlearn": lambda: _sqlearn(data, aggregate, "DOUBLE"),
    }
    if sql is not None:
        answers["duckdb"] = lambda: _duckdb(sql, values, threads=None)
        answers["duckdb, 1 thread"] = lambda: _duckdb(sql, values, threads=1)
    if numpy is not None:
        answers["numpy"] = lambda: numpy(np.array(values, dtype=float))
    if pandas is not None:
        answers["pandas"] = lambda: pandas(pd.Series(_cases.as_nan(data.values)))
    if formula == "mode":
        answers["pandas"] = lambda: _pandas_mode(data.values)
    return _cases.measure_all(
        step="agg",
        formula=formula,
        data=data,
        type="DOUBLE",
        exact=exact(values) if values else None,  # type: ignore[arg-type]
        bound=bound,
        answers=answers,  # type: ignore[arg-type]
    )


def _quantiles(data: _cases.Dataset) -> list[dict]:
    out = []
    values = _cases.present(data.values)
    for method in ("linear", "averaged_inverted_cdf"):
        for q in QS:
            aggregate = sq.agg.quantile(q=q, method=method)
            sql = f"quantile_cont(x, {q})" if method == "linear" else None
            out += _measure(
                data,
                repr(aggregate).removeprefix("sq.agg."),
                aggregate,
                BOUNDS["quantile"],
                lambda v, q=q, m=method: exact_quantile(v, q, m),
                sql,
                lambda v, q=q, m=method: np.quantile(v, q, method=m),
                (lambda s, q=q: s.quantile(q)) if method == "linear" else None,
            )
    for q in (0.5, 0.9):
        aggregate = sq.agg.approx_quantile(q=q)
        formula = repr(aggregate).removeprefix("sq.agg.")
        if not values:
            out.append(
                _cases.skipped(
                    step="agg",
                    formula=formula,
                    dataset=data.name,
                    rows=len(data.values),
                    type="DOUBLE",
                    reference="sqlearn",
                    note="no values: no quantile to measure against",
                    bound=0,
                )
            )
            continue
        out.append(
            _cases.recorded(
                step="agg",
                formula=formula,
                dataset=data.name,
                rows=len(data.values),
                type="DOUBLE",
                reference="sqlearn",
                value=float(_sqlearn(data, aggregate, "DOUBLE")),  # type: ignore[arg-type]
                exact=exact_quantile(values, q, "linear"),
                note="approximate by name: its error against the exact "
                "linear quantile is recorded, with no bound",
            )
        )
    return out


def _labels(data: _cases.Dataset) -> list[dict]:
    """Compare the any-type aggregates on text with the exact answer."""
    values = _cases.present(data.values)
    head = {
        "step": "agg",
        "dataset": data.name,
        "rows": len(data.values),
        "type": "VARCHAR",
        "compared_with": "collections.Counter and sorted over the present values",
    }
    exact: dict[str, Callable[[list], object]] = {
        "mode": exact_mode,
        "min": min,
        "max": max,
        "count": len,
        "distinct": lambda v: sorted(set(v)),
    }
    out = []
    for name, canonical in exact.items():
        aggregate = getattr(sq.agg, name)
        if not values:
            out.append(
                _cases.skipped(
                    step="agg",
                    formula=name,
                    dataset=data.name,
                    rows=len(data.values),
                    type="VARCHAR",
                    reference="sqlearn",
                    note=data.note + ": nothing to compare",
                    bound=0,
                )
            )
            continue
        got = _sqlearn(data, aggregate, "VARCHAR")
        out.append(
            _cases.exact_case(
                formula=name,
                mismatches=0 if got == canonical(values) else 1,
                cells=1,
                note=data.note,
                **head,
            )
        )
    return out


def _distinct_numbers(data: _cases.Dataset) -> dict:
    values = _cases.present(data.values)
    got = _sqlearn(data, sq.agg.distinct, "DOUBLE") if data.values else []
    return _cases.exact_case(
        step="agg",
        formula="distinct",
        dataset=data.name,
        rows=len(data.values),
        type="DOUBLE",
        mismatches=0 if got == sorted(set(values)) else 1,
        cells=1,
        compared_with="sorted(set(...)) over the present values",
        note=data.note,
    )


def cases() -> list[dict]:
    """Return the aggregates' cases: each aggregate, dataset and reference."""
    out = []
    for data in _cases.numbers():
        for name in BOUNDS:
            if name == "quantile":
                continue
            aggregate = getattr(sq.agg, name)
            exact, sql, numpy, pandas = _references(name)
            out += _measure(
                data, name, aggregate, BOUNDS[name], exact, sql, numpy, pandas
            )
        out += _quantiles(data)
        out.append(_distinct_numbers(data))
    for data in _cases.labels():
        out += _labels(data)
    return out
