"""Validate sq.scale's learned values: each method's centre and divisor.

Each method learns, through a one-step pipeline, from the numeric datasets,
and its centre and divisor are compared with the canonical value (ADR 0016):
exact as a `Fraction` where the answer is rational (the mean, the median and
the quartiles, the extremes), the square root of the exact variance at 50
digits with mpmath for the standard deviation. A quantile's ranks are found
as numpy finds them (in doubles), then its value is interpolated exactly.

The divisor counts a spread at the level of rounding as 1, as sqlearn and
scikit-learn do (no dataset here has one but the single value, whose spread
is 0); the exact answer and numpy's count a spread of 0 as 1, so the
comparison stays like for like. The near-constant rule itself is tested
against scikit-learn in the step's tests. Beside sqlearn: scikit-learn's
scaler of the same method (``StandardScaler``, ``RobustScaler``,
``MinMaxScaler``, ``MaxAbsScaler``) and numpy.

``normalize`` learns nothing, so its cases are its outputs: the first
column of each row of small three-column tables (DOUBLE, a row of zeros,
INTEGER), divided by the row's ``l1``, ``l2`` or ``max`` norm, against the
exact quotient (a `Fraction`; for ``l2`` the root at 50 digits). Beside
sqlearn: scikit-learn's ``Normalizer`` and numpy.
"""

from collections.abc import Callable
from fractions import Fraction

import mpmath
import numpy as np
from sklearn.preprocessing import (
    MaxAbsScaler,
    MinMaxScaler,
    Normalizer,
    RobustScaler,
    StandardScaler,
)

import sqlearn as sq
from validation import _cases
from validation.sqlearn.agg.validate_aggregates import exact_quantile

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: the mean
# 119 ULPs with DuckDB's plain `avg`; tightened to 1 when the mean moved to
# the compensated `favg` (ADR 0033), worst then 1 ULP (medium set). Standard
# deviation: 12 ULPs on the large set (`stddev_pop` alone shows the same);
# tightened to 2 when it moved to two compensated passes (issue #28), worst
# then 1 ULP (small and large sets), with 1 ULP more for the order DuckDB's
# threads finish in (ADR 0043: the large set gave 0 in 2 of 30 runs).
# The median, the extremes, the range and the largest absolute value: 0 ULPs.
# The IQR: 32 on the small set, as `sq.agg.iqr`'s own (each quartile is
# rounded at values near 1,000, and their difference keeps those errors at
# its own finer ULPs; numpy and scikit-learn show the same).
BOUNDS = {
    ("standard", "center"): 1,
    ("standard", "scale"): 2,
    ("robust", "center"): 1,
    ("robust", "scale"): 32,
    ("minmax", "center"): 1,
    ("minmax", "scale"): 1,
    ("maxabs", "scale"): 1,
}

FORMULAS = {
    ("standard", "center"): "standard center: mean",
    ("standard", "scale"): "standard scale: population standard deviation",
    ("robust", "center"): "robust center: median",
    ("robust", "scale"): "robust scale: quantile(0.75) - quantile(0.25)",
    ("minmax", "center"): "minmax center: min",
    ("minmax", "scale"): "minmax scale: max - min",
    ("maxabs", "scale"): "maxabs scale: max(abs(x))",
}
DIVISOR_NOTE = "a spread of 0 counted as 1, as for sqlearn"

SKLEARN = {
    "standard": (StandardScaler, "mean_", "scale_"),
    "robust": (RobustScaler, "center_", "scale_"),
    "minmax": (MinMaxScaler, "data_min_", "data_range_"),
    "maxabs": (MaxAbsScaler, None, "scale_"),
}
"""Each method's scikit-learn scaler and the attributes of its centre and spread."""


def _divisor(spread: float) -> float:
    return 1.0 if spread == 0 else spread


def _exact_spread(method: str, values: list[float]) -> Fraction | object:
    if method == "standard":
        return _cases.exact_stddev_pop(values)
    if method == "robust":
        return exact_quantile(values, 0.75, "linear") - exact_quantile(
            values, 0.25, "linear"
        )
    if method == "minmax":
        return Fraction(max(values)) - Fraction(min(values))
    return max(abs(Fraction(v)) for v in values)


def _exact(method: str, what: str, values: list[float]) -> object:
    if not values:
        return None
    if what == "center":
        return {
            "standard": _cases.exact_mean,
            "robust": _cases.exact_median,
            "minmax": lambda v: Fraction(min(v)),
        }[method](values)
    spread = _exact_spread(method, values)
    return spread if spread != 0 else 1


def _numpy(method: str, what: str, v: np.ndarray) -> float:
    if what == "center":
        return {"standard": np.mean, "robust": np.median, "minmax": np.min}[method](v)
    spread = {
        "standard": np.std,
        "robust": lambda a: np.quantile(a, 0.75) - np.quantile(a, 0.25),
        "minmax": np.ptp,
        "maxabs": lambda a: np.max(np.abs(a)),
    }[method](v)
    return _divisor(float(spread))


def _sqlearn(data: _cases.Dataset, method: str, what: str) -> float:
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    step = sq.scale(data.column, method=method)
    learned = sq.Pipeline([step]).learn(rel)[method]
    return (learned.center_ if what == "center" else learned.scale_)[data.column]


def _sklearn(data: _cases.Dataset, method: str, what: str) -> float:
    scaler, center, spread = SKLEARN[method]
    fitted = scaler().fit(_cases.as_nan(data.values)[:, None])
    value = getattr(fitted, center if what == "center" else spread)[0]
    return _divisor(value) if what == "scale" and method == "minmax" else value


def _answers(data: _cases.Dataset, method: str, what: str) -> dict:
    present = np.array(_cases.present(data.values), dtype=float)
    answers: dict[str, Callable[[], float]] = {
        "sqlearn": lambda: _sqlearn(data, method, what),
        "scikit-learn": lambda: _sklearn(data, method, what),
        "numpy": lambda: _numpy(method, what, present),
    }
    return answers


def cases() -> list[dict]:
    """Return sq.scale's cases: each method's centre and divisor, per dataset."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        for (method, what), bound in BOUNDS.items():
            notes = {"numpy": DIVISOR_NOTE} if what == "scale" else {}
            if what == "scale" and method == "minmax":
                notes["scikit-learn"] = "data_range_, " + DIVISOR_NOTE
            out += _cases.measure_all(
                step="scale",
                formula=FORMULAS[method, what],
                data=data,
                type="DOUBLE",
                exact=_exact(method, what, values),  # type: ignore[arg-type]
                bound=bound,
                answers=_answers(data, method, what),
                notes=notes,
            )
    return out + normalize_cases()


# Set from the first measurement (ADR 0016), as BOUNDS above: worst 1 ULP
# for l1 and l2 (one rounding in the sum or the root, then the division),
# 0 for max (an exact maximum, one division).
NORM_BOUNDS = {"l1": 1, "l2": 1, "max": 1}

NORM_FORMULAS = {
    "l1": "normalize l1: x / sum(abs(row))",
    "l2": "normalize l2: x / sqrt(sum(row ** 2))",
    "max": "normalize max: x / max(abs(row))",
}

COLUMNS = ("a", "b", "c")


def _rows() -> list[tuple[str, str, list[tuple[float, ...]], str]]:
    """Return the tables of rows normalize is measured on: name, type, rows, note."""
    rng = np.random.default_rng(_cases.SEED)
    small = [tuple(float(v) for v in row) for row in rng.normal(1_000.0, 100.0, (4, 3))]
    zero = [(0.0, 0.0, 0.0), (3.0, -4.0, 12.0), (-0.5, 0.25, 2.0)]
    whole = [tuple(float(v) for v in row) for row in rng.integers(-50, 50, (4, 3))]
    return [
        ("rows", "DOUBLE", small, "4 rows of 3, normal(1000, 100)"),
        ("zero row", "DOUBLE", zero, "a row of zeros first"),
        ("integer", "INTEGER", whole, "4 rows of 3 integers in [-50, 50)"),
    ]


def _exact_norm(norm: str, row: tuple[float, ...]) -> object:
    """Return the row's first value over its exact norm (a norm of 0 counts as 1)."""
    values = [Fraction(v) for v in row]
    if norm == "l2":
        total = sum((v * v for v in values), Fraction(0))
        if total == 0:
            return Fraction(0)
        with mpmath.workdps(_cases.DIGITS):
            root = mpmath.sqrt(mpmath.mpf(total.numerator) / total.denominator)
            return (mpmath.mpf(values[0].numerator) / values[0].denominator) / root
    size = sum(map(abs, values)) if norm == "l1" else max(map(abs, values))
    return values[0] / (size if size != 0 else 1)


def _normalized(kind: str, rows: list[tuple[float, ...]], norm: str) -> np.ndarray:
    columns = {c: tuple(row[i] for row in rows) for i, c in enumerate(COLUMNS)}
    rel = _cases.sqlearn_table(columns, kind)
    pipe = sq.Pipeline([sq.scale.normalize(norm=norm)]).learn(rel)
    return np.array(pipe.apply(rel).fetchall(), dtype=float)


def _numpy_norm(norm: str, row: np.ndarray) -> float:
    size = {
        "l1": lambda r: np.sum(np.abs(r)),
        "l2": lambda r: np.sqrt(np.sum(r * r)),
        "max": lambda r: np.max(np.abs(r)),
    }[norm](row)
    return float(row[0] / (size if size != 0 else 1.0))


def normalize_cases() -> list[dict]:
    """Return sq.scale.normalize's cases: the first output of each row, per norm."""
    out = []
    for name, kind, rows, note in _rows():
        array = np.array(rows, dtype=float)
        for norm, bound in NORM_BOUNDS.items():
            got = _normalized(kind, rows, norm)
            sk = Normalizer(norm=norm).fit_transform(array)
            for r, row in enumerate(rows):
                data = _cases.Dataset(f"{name}, row {r + 1}", "a", row, note)
                out += _cases.measure_all(
                    step="scale.normalize",
                    formula=NORM_FORMULAS[norm],
                    data=data,
                    type=kind,
                    exact=_exact_norm(norm, row),  # type: ignore[arg-type]
                    bound=bound,
                    answers={
                        "sqlearn": lambda got=got, r=r: got[r, 0],
                        "scikit-learn": lambda sk=sk, r=r: sk[r, 0],
                        "numpy": lambda array=array, r=r, norm=norm: _numpy_norm(
                            norm, array[r]
                        ),
                    },
                )
    return out
