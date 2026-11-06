"""Validate accuracy: the share of rows where the prediction equals the target.

The canonical value is computed in pure Python as a `Fraction` (matches over
rows), exact (ADR 0016). Beside sqlearn: the same average in DuckDB alone
and at one thread, scikit-learn's ``accuracy_score``, numpy and pandas. A
mean of 0s and 1s sums exactly, so every answer should be the double nearest
the fraction: the bound is 0. Labels with NULL or NaN, and no rows, have no
right answer: sqlearn must refuse them.
"""

import math
from fractions import Fraction

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016); 0, as the answer is exact.
# Loosening it needs a written reason here, never a quiet edit.
BOUND = 0


def _pairs() -> list[tuple[_cases.Dataset, str, tuple, str, tuple, str]]:
    """Return each dataset: its target and prediction columns, and their type."""
    rng = np.random.default_rng(_cases.SEED)

    def draw(n: int) -> tuple[tuple, tuple]:
        y = rng.integers(0, 3, n)
        p = np.where(rng.random(n) < 0.7, y, rng.integers(0, 3, n))
        return tuple(int(v) for v in y), tuple(int(v) for v in p)

    out = []
    for name, n in _cases.SIZES.items():
        y, p = draw(n)
        out.append((name, "y", y, "prediction", p, "INTEGER", f"{n:,} rows, 3 labels"))
    y, p = draw(1_000)
    out.append(("null", "y", y, "prediction", tuple(_cases._gaps(rng, list(p), None)),
                "INTEGER", "a tenth of the predictions NULL"))  # fmt: skip
    y, p = draw(1_000)
    floats = tuple(_cases._gaps(rng, [float(v) for v in p], math.nan))
    out.append(("nan", "y", tuple(float(v) for v in y), "prediction", floats, "DOUBLE",
                "a tenth of the predictions NaN"))  # fmt: skip
    out.append(("empty", "y", (), "prediction", (), "INTEGER", "no rows"))
    y, p = draw(1)
    out.append(("single", "y", y, "prediction", p, "INTEGER", "one row"))
    y, p = draw(1_000)
    out.append(("reserved", "select", y, "from", p, "INTEGER",
                'columns named "select" and "from"'))  # fmt: skip
    return [
        (_cases.Dataset(name, y_col, y, note), y_col, y, p_col, p, kind)
        for name, y_col, y, p_col, p, kind, note in out
    ]


def _duckdb(
    y_col: str, y: tuple, p_col: str, p: tuple, kind: str, threads: int | None
) -> float:
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    rel = _cases.table(con, "data", {y_col: y, p_col: p}, kind)
    quoted = [_quote(y_col), _quote(p_col)]
    return rel.aggregate(
        f"favg(CASE WHEN {quoted[0]} = {quoted[1]} THEN 1.0 ELSE 0.0 END)"
    ).fetchall()[0][0]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cases() -> list[dict]:
    """Return accuracy's cases: each dataset and reference."""
    out = []
    for data, y_col, y, p_col, p, kind in _pairs():
        answerable = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))
        exact = (
            Fraction(sum(a == b for a, b in zip(y, p, strict=True)), len(y))
            if answerable
            else None
        )

        def ours(y=y, p=p, kind=kind, y_col=y_col, p_col=p_col) -> float:
            rel = _cases.sqlearn_table({y_col: y, p_col: p}, kind)
            return sq.metrics.accuracy.compute(rel, y_col, p_col)

        def arrays(y=y, p=p) -> tuple[np.ndarray, np.ndarray]:
            return _cases.as_nan(y), _cases.as_nan(p)

        out += _cases.measure_all(
            step="accuracy",
            formula="accuracy",
            data=data,
            type=kind,
            exact=exact,
            bound=BOUND,
            answers={
                "sqlearn": ours,
                "duckdb": lambda a=(y_col, y, p_col, p, kind): _duckdb(*a, None),
                "duckdb, 1 thread": lambda a=(y_col, y, p_col, p, kind): _duckdb(*a, 1),
                "numpy": lambda a=arrays: np.mean(a()[0] == a()[1]),
                "scikit-learn": lambda a=arrays: accuracy_score(*a()),
                "pandas": lambda a=arrays: (
                    pd.Series(a()[0]) == pd.Series(a()[1])
                ).mean(),
            },
        )
    return out
