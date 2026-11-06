"""Validate sq.impute: its median and mean, and its mode, constant and indicator.

The median and the mean are rounded, so each dataset's fill value is compared
with the canonical value (ADR 0016): the exact median or mean as a
`Fraction`. Beside sqlearn: DuckDB's ``median`` and ``favg`` alone and at one
thread, numpy's ``nanmedian`` and ``nanmean``, scikit-learn's
``SimpleImputer`` and pandas.

The mode, a constant and the indicator have no rounding: each is compared
value by value with scikit-learn (``SimpleImputer(strategy="most_frequent")``,
``SimpleImputer(strategy="constant")``, ``MissingIndicator()``), on numbers
and on text. The bound is 0; ``ulps`` holds the
count of values that differ.
"""

import math
from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.impute import MissingIndicator, SimpleImputer

import sqlearn as sq
from validation import _cases
from validation.sqlearn.preprocessing import _encoders

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

FILL = {"DOUBLE": 0.0, "VARCHAR": "unknown"}
"""The constant each kind of column is filled with."""


def _sqlearn(data: _cases.Dataset, value: str) -> float:
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    step = sq.impute(data.column, value=value)
    pipe = sq.Pipeline([("impute", step)]).learn(rel)
    return pipe["impute"].value_[data.column]


def _sklearn(data: _cases.Dataset, value: str) -> float:
    imputer = SimpleImputer(strategy=value).fit(_cases.as_nan(data.values)[:, None])
    return imputer.statistics_[0]


def _pandas(data: _cases.Dataset, value: str) -> float:
    series = pd.Series(_cases.as_nan(data.values))
    return series.median() if value == "median" else series.mean()


def _rounded() -> list[dict]:
    """Return the median and mean cases: each dataset and reference."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        for value in ("median", "mean"):
            out += _cases.measure_all(
                step="impute",
                formula=value,
                data=data,
                type="DOUBLE",
                exact=EXACT[value](values) if values else None,
                bound=BOUNDS[value],
                answers={
                    "sqlearn": lambda d=data, s=value: _sqlearn(d, s),
                    "duckdb": lambda v=values, s=value: _cases.duckdb_alone(
                        DUCKDB[s], v, threads=None
                    ),
                    "duckdb, 1 thread": lambda v=values, s=value: _cases.duckdb_alone(
                        DUCKDB[s], v, threads=1
                    ),
                    "numpy": lambda d=data, s=value: NUMPY[s](_cases.as_nan(d.values)),
                    "scikit-learn": lambda d=data, s=value: _sklearn(d, s),
                    "pandas": lambda d=data, s=value: _pandas(d, s),
                },
            )
    return out


def _same(a: object, b: object) -> bool:
    """Say whether two values agree, a missing value matching a missing one."""
    missing = [v is None or (isinstance(v, float) and math.isnan(v)) for v in (a, b)]
    return all(missing) or (not any(missing) and a == b)


def _differ(ours: list, theirs: list) -> int:
    """Count the positions at which two columns of values differ."""
    differ = sum(not _same(a, b) for a, b in zip(ours, theirs, strict=False))
    return differ + abs(len(ours) - len(theirs))


def _to_sklearn(data: _cases.Dataset, kind: str) -> np.ndarray:
    if kind == "DOUBLE":
        return _cases.as_nan(data.values)[:, None]
    return _encoders.to_sklearn(data.values)


def _apply(step: sq.Step, data: _cases.Dataset, kind: str) -> pd.DataFrame:
    rel = _cases.sqlearn_table({data.column: data.values}, kind)
    return sq.Pipeline([("impute", step)]).learn(rel).apply(rel, out="pandas")


def _fill_mismatches(step: sq.Step, imputer: SimpleImputer, data, kind: str) -> int:
    """Count the filled values that differ from scikit-learn's."""
    ours = _apply(step, data, kind)[data.column].tolist()
    theirs = imputer.fit_transform(_to_sklearn(data, kind))[:, 0].tolist()
    return _differ(ours, theirs)


def _indicator_mismatches(data: _cases.Dataset, kind: str) -> int:
    """Count the indicator values (columns created included) that differ."""
    frame = _apply(sq.impute.indicator(data.column), data, kind)
    created = [c for c in frame.columns if c != data.column]
    theirs = MissingIndicator().fit_transform(_to_sklearn(data, kind)).astype(int)
    misses = len(data.values) * abs(len(created) - theirs.shape[1])
    if created and theirs.shape[1]:
        misses += _differ(frame[created[0]].tolist(), theirs[:, 0].tolist())
    return misses


EXACT_FORMULAS: dict[str, tuple[str, Callable[[_cases.Dataset, str], int]]] = {
    "mode": (
        'scikit-learn SimpleImputer(strategy="most_frequent")',
        lambda d, k: _fill_mismatches(
            sq.impute.mode(d.column), SimpleImputer(strategy="most_frequent"), d, k
        ),
    ),
    "constant": (
        'scikit-learn SimpleImputer(strategy="constant")',
        lambda d, k: _fill_mismatches(
            sq.impute.constant(FILL[k], d.column),
            SimpleImputer(strategy="constant", fill_value=FILL[k]),
            d,
            k,
        ),
    ),
    "indicator": ("scikit-learn MissingIndicator()", _indicator_mismatches),
}


def _exact() -> list[dict]:
    """Return the mode, constant and indicator cases: each kind and dataset."""
    out: list[dict] = []
    datasets = [(d, "DOUBLE") for d in _cases.numbers()]
    datasets += [(d, "VARCHAR") for d in _cases.labels()]
    for data, kind in datasets:
        for formula, (compared_with, mismatches) in EXACT_FORMULAS.items():
            head = {
                "step": "impute",
                "formula": formula,
                "dataset": data.name,
                "rows": len(data.values),
                "type": kind,
            }
            if not data.values:
                out.append(_no_rows(data, kind, formula, head))
                continue
            out.append(
                _cases.exact_case(
                    mismatches=mismatches(data, kind),
                    cells=len(data.values),
                    compared_with=compared_with,
                    note=f"{data.note}; every value of the output column",
                    **head,
                )
            )
    return out


def _no_rows(data: _cases.Dataset, kind: str, formula: str, head: dict) -> dict:
    """Record a dataset without rows: scikit-learn refuses it."""
    note = "no rows; scikit-learn refuses no rows (ValueError)"
    if data.name == "nan" and kind == "VARCHAR":
        note = "text holds no NaN; NaN is a DOUBLE value"
    result = "skipped"
    if formula == "mode" and data.name == "empty":
        try:
            _apply(sq.impute.mode(data.column), data, kind)
        except sq.errors.SqlearnError as exc:
            result = "pass"
            note = f"refused, as specified: {_cases.first_line(exc)}; {note}"
        else:
            result = "fail"
            note = f"no value to learn the mode from, yet sqlearn learned; {note}"
    return _cases.skipped(
        reference="sqlearn", note=note, bound=0, result=result, **head
    )


def cases() -> list[dict]:
    """Return sq.impute's cases: rounded fill values, then exact comparisons."""
    return _rounded() + _exact()
