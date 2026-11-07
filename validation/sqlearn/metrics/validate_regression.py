"""Validate rmse, mae and r2 against exact arithmetic.

The canonical values are computed in pure Python from the doubles' exact
values: the mean absolute error as a `Fraction`, the root mean squared error
as the square root of a `Fraction` at 50 digits with mpmath, and r2 as one
minus a `Fraction` ratio (ADR 0016). A constant target has no spread to
explain: r2 is then 1 for an exact prediction and 0 otherwise, as
scikit-learn's ``r2_score`` has it. Beside sqlearn: DuckDB alone (``favg``
and ``fsum``, and at one thread), scikit-learn, numpy. Targets or predictions
with NULL or NaN, and no rows, have no right answer: sqlearn must refuse
them. The ``offset`` dataset puts the target's mean far above its spread,
where a sum of squares minus a squared sum would lose every digit.
"""

import math
from fractions import Fraction

import duckdb
import mpmath
import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value. Loosening a bound needs a written reason here, never a
# quiet edit. r2's total sum of squares is DuckDB's ``var_pop`` (a running
# update about the mean that is not compensated): measured at 11 doubles on
# 100,000 rows, and at 114,466 doubles (1.7e-11 relative) where the target's
# mean is a million times its spread. A metric's expression sees only the two
# columns, so it cannot shift by the mean first; the wide bound is that
# limit, recorded and named, not a tolerance. rmse and mae are compensated.
BOUNDS = {"rmse": 2, "mae": 2, "r2": 16}
WIDE = {("r2", "offset"): 120_000}


def _pairs() -> list[tuple[_cases.Dataset, tuple, tuple]]:
    """Return each dataset: its target values and its predictions."""
    rng = np.random.default_rng(_cases.SEED)

    def draw(n: int, offset: float = 0.0) -> tuple[tuple, tuple]:
        y = offset + rng.normal(size=n)
        p = y + rng.normal(scale=0.5, size=n)
        return tuple(float(v) for v in y), tuple(float(v) for v in p)

    out = []
    for name, n in _cases.SIZES.items():
        y, p = draw(n)
        out.append((name, y, p, f"{n:,} rows"))
    y, p = draw(1_000, 1e6)
    out.append(("offset", y, p, "target mean 1e6, spread 1"))
    y, p = draw(1_000)
    out.append(("null", y, tuple(_cases._gaps(rng, list(p), None)),
                "a tenth of the predictions NULL"))  # fmt: skip
    y, p = draw(1_000)
    out.append(("nan", y, tuple(_cases._gaps(rng, list(p), math.nan)),
                "a tenth of the predictions NaN"))  # fmt: skip
    out.append(("empty", (), (), "no rows"))
    out.append(("constant", (2.0,) * 10, (2.0, 1.0, 3.0) * 3 + (2.0,),
                "a constant target, predicted off"))  # fmt: skip
    out.append(("constant, exact", (2.0,) * 10, (2.0,) * 10,
                "a constant target, predicted exactly"))  # fmt: skip
    return [(_cases.Dataset(name, "y", y, note), y, p) for name, y, p, note in out]


def _exact(metric: str, y: tuple, p: tuple) -> Fraction | mpmath.mpf:
    """Return the metric's exact value over the doubles."""
    n = len(y)
    squares = sum((Fraction(a) - Fraction(b)) ** 2 for a, b in zip(y, p, strict=True))
    if metric == "mae":
        return (
            sum(abs(Fraction(a) - Fraction(b)) for a, b in zip(y, p, strict=True)) / n
        )
    if metric == "rmse":
        with mpmath.workdps(_cases.DIGITS):
            return mpmath.sqrt(mpmath.mpf(squares.numerator) / squares.denominator / n)
    mean = sum(Fraction(a) for a in y) / n
    total = sum((Fraction(a) - mean) ** 2 for a in y)
    if total == 0:
        return Fraction(1 if squares == 0 else 0)
    return 1 - squares / total


_SQL = {
    "rmse": "sqrt(favg((y - p) * (y - p)))",
    "mae": "favg(abs(y - p))",
    "r2": "1 - fsum((y - p) * (y - p)) / (var_pop(y) * count(y))",
}
_SKLEARN = {
    "rmse": root_mean_squared_error,
    "mae": mean_absolute_error,
    "r2": r2_score,
}


def _duckdb(metric: str, y: tuple, p: tuple, threads: int | None) -> float:
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    rel = _cases.table(con, "data", {"y": y, "p": p}, "DOUBLE")
    return rel.aggregate(_SQL[metric]).fetchall()[0][0]


def _numpy(metric: str, a: np.ndarray, b: np.ndarray) -> float:
    e = a - b
    if metric == "rmse":
        return float(np.sqrt(np.mean(e * e)))
    if metric == "mae":
        return float(np.mean(np.abs(e)))
    return float(1 - np.sum(e * e) / np.sum((a - a.mean()) ** 2))


def cases() -> list[dict]:
    """Return the cases of rmse, mae and r2: each dataset and reference."""
    out = []
    for data, y, p in _pairs():
        answerable = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))
        for metric, bound in BOUNDS.items():
            exact = _exact(metric, y, p) if answerable else None

            def ours(metric=metric, y=y, p=p) -> float:
                rel = _cases.sqlearn_table({"y": y, "prediction": p}, "DOUBLE")
                return getattr(sq.metrics, metric).compute(rel, "y")

            def arrays(y=y, p=p) -> tuple[np.ndarray, np.ndarray]:
                return _cases.as_nan(y), _cases.as_nan(p)

            answers = {
                "sqlearn": ours,
                "duckdb": lambda m=metric, y=y, p=p: _duckdb(m, y, p, None),
                "duckdb, 1 thread": lambda m=metric, y=y, p=p: _duckdb(m, y, p, 1),
                "numpy": lambda m=metric, a=arrays: _numpy(m, *a()),
                "scikit-learn": lambda m=metric, a=arrays: _SKLEARN[m](*a()),
            }
            out += _cases.measure_all(
                step=metric,
                formula=metric,
                data=data,
                type="DOUBLE",
                exact=exact,
                bound=WIDE.get((metric, data.name), bound),
                answers=answers,
            )
    return out
