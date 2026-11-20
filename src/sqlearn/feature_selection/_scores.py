"""The scores of the univariate feature selectors: f_classif, f_regression, chi2.

Each score is learned per column in SQL (`learn_score`) and finished in
Python from the few numbers that come back (`finish_score`), as
scikit-learn 1.9.1 computes it.
"""

import math
import sys
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE

from sqlearn._expr import const, is_missing, target_stats

__all__ = ["LEARNED", "SCORES", "finish_score", "learn_score"]

SCORES = ("f_classif", "f_regression", "chi2")
"""The names `score=` takes."""

LEARNED = {
    "f_classif": ("count", "missing", "infinite", "target_missing", "stats", "low"),
    "chi2": ("count", "missing", "infinite", "target_missing", "stats", "low"),
    "f_regression": (
        "count",
        "missing",
        "infinite",
        "target_missing",
        "kind",
        "covariance",
        "variance",
        "target_variance",
    ),
}
"""The names each score learns (`learn_score`), in its order."""

Stats = Sequence[tuple[int, object, int, float, float]]
"""Per class: the fold (always 0), the class, its count, the sum of the
column less its minimum, and the sum of its squares (`target_stats`)."""


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _count(condition: Expression) -> Expression:
    """Return the number of rows where `condition` holds."""
    return _fn("count_if", condition)


def learn_score(score: str, x: Expression, y: Expression) -> dict[str, Expression]:
    """Return what `score` learns of the column `x` against the target `y`.

    Every score learns ``count`` (the rows), ``missing`` and ``infinite``
    (the rows where `x` is NULL or NaN, or infinite) and ``target_missing``
    (the rows where the target is NULL, NaN or infinite). ``f_classif`` and
    ``chi2`` learn ``stats``, the count, sum and sum of squares of `x` per
    class of the target (`sqlearn._expr.target_stats`, with one fold), and
    ``low``, the column's minimum, which those sums are taken less of.
    ``f_regression`` learns the population ``covariance`` of `x` and the
    target, the ``variance`` of each, and the target's type, ``kind``.

    Parameters
    ----------
    score : str
        One of `SCORES`.
    x : duckdb.Expression
        The column.
    y : duckdb.Expression
        The target.

    Returns
    -------
    dict of str to duckdb.Expression
        Learned name to aggregate.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn.feature_selection._scores import LEARNED, SCORES, learn_score
    >>> x, y = duckdb.ColumnExpression("a"), duckdb.ColumnExpression("y")
    >>> list(learn_score("chi2", x, y))
    ['count', 'missing', 'infinite', 'target_missing', 'stats', 'low']
    >>> all(list(learn_score(s, x, y)) == list(LEARNED[s]) for s in SCORES)
    True
    """
    number = x.cast(DOUBLE)
    target = y.try_cast(DOUBLE)
    floating = _fn("typeof", y).isin(const("FLOAT"), const("DOUBLE"))
    learned = {
        "count": _fn("count_star"),
        "missing": _count(is_missing(x)),
        "infinite": _count(_fn("isinf", number)),
        "target_missing": _count(y.isnull() | (floating & ~_fn("isfinite", target))),
    }
    if score == "f_regression":
        return {
            **learned,
            "kind": _fn("any_value", _fn("typeof", y)),
            "covariance": _fn("covar_pop", number, target),
            "variance": _fn("var_pop", number),
            "target_variance": _fn("var_pop", target),
        }
    return {
        **learned,
        "stats": target_stats(y, number, const(0)),
        "low": _fn("min", number),
    }


def _ratio(a: Fraction, b: Fraction) -> float:
    """Return the exact ``a / b`` as a float, numpy's NaN or infinity at b = 0."""
    if b == 0:
        return math.nan if a == 0 else math.copysign(math.inf, a)
    return float(a / b)


def _exact(value: object) -> Fraction:
    """Return a learned number exactly, refusing what is not a finite number.

    What is learned is a number from DuckDB, but a saved file's values are
    read back from JSON: text there (``"1e100000000"``, which `Fraction`
    would read as a number of a hundred million digits) is refused, so
    loading reports the file as damaged rather than hanging.
    """
    if type(value) is not int and type(value) is not float:
        msg = f"a learned value is {type(value).__name__}, not a number"
        raise TypeError(msg)
    return Fraction(value)  # NaN and infinity raise ValueError, OverflowError


def _count_of(value: object) -> int:
    """Return a learned count, refusing what is not a whole number."""
    if type(value) is not int:
        msg = f"a learned count is {type(value).__name__}, not a whole number"
        raise TypeError(msg)
    return value


def _classes(values: Mapping[str, object]) -> list[tuple[int, Fraction, Fraction]]:
    """Return each class's count, sum and sum of squares, exactly."""
    stats = cast("Stats", values["stats"])
    return [(_count_of(n), _exact(s), _exact(ss)) for _, _, n, s, ss in stats]


def _f_classif(values: Mapping[str, object]) -> float:
    """Return the ANOVA F, as scikit-learn's ``f_oneway``.

    The sums are of the column less its minimum, which leaves F unchanged;
    they are combined exactly, so a constant column's F is exactly 0 / 0.
    """
    classes = _classes(values)
    n = sum(c for c, _, _ in classes)
    total = sum((s for _, s, _ in classes), Fraction(0))
    between = sum((s * s / c for c, s, _ in classes), Fraction(0)) - total**2 / n
    # Each class's own spread is never below 0; rounding of its sums may be.
    within = sum(
        (max(ss - s * s / c, Fraction(0)) for c, s, ss in classes), Fraction(0)
    )
    k = len(classes)
    if k == 1 or n == k:
        return math.nan  # numpy's x / 0 with x exactly 0: NaN
    msb = between / (k - 1)
    msw = within / (n - k)
    return _ratio(msb, msw)


def _chi2(values: Mapping[str, object]) -> float:
    """Return chi², as scikit-learn's ``chi2``: observed against expected sums.

    One class is NaN, as scikit-learn's, whose label binarizer adds a second
    class holding nothing (0 / 0).
    """
    classes = _classes(values)
    if len(classes) == 1:
        return math.nan
    low = _exact(values["low"])
    n = sum(c for c, _, _ in classes)
    observed = [s + c * low for c, s, _ in classes]
    total = sum(observed, Fraction(0))
    if total == 0:
        return math.nan  # every expected sum is 0: 0 / 0, as scikit-learn's
    expected = [Fraction(c, n) * total for c, _, _ in classes]
    return float(
        sum(
            ((o - e) ** 2 / e for o, e in zip(observed, expected, strict=True)),
            Fraction(0),
        )
    )


def _f_regression(values: Mapping[str, object]) -> float:
    """Return the F of the correlation, as ``f_regression(force_finite=True)``.

    ``F = r² / (1 - r²) · (n - 2)``, with ``r² = cov² / (var(x) var(y))``,
    taken exactly as ``cov² (n - 2) / (var(x) var(y) - cov²)``. A constant
    column or target (no correlation) scores 0; a perfect correlation, whose
    F is infinite, scores the largest double (0 at two rows, where scikit-
    learn's ``inf · 0`` is NaN and then 0).
    """
    dof = _count_of(values["count"]) - 2

    def exact(name: str) -> Fraction:
        value = values[name]
        return Fraction(0) if value is None else _exact(value)

    spread = exact("variance") * exact("target_variance")
    if spread == 0:
        return 0.0 * dof  # r is NaN, taken as 0
    covariance = exact("covariance")
    rest = spread - covariance**2
    if rest <= 0:  # |r| = 1, up to the rounding of the sums
        return 0.0 if dof == 0 else sys.float_info.max
    return float(covariance**2 * dof / rest)


def finish_score(score: str, values: Mapping[str, object]) -> float:
    """Return one column's score from what `learn_score` learned for it.

    Parameters
    ----------
    score : str
        One of `SCORES`.
    values : mapping of str to object
        Learned name to value, for the column.

    Returns
    -------
    float
        The score, NaN where scikit-learn's is NaN (``f_classif`` of a
        constant column, ``chi2`` of a column of zeros, either with one
        class).

    Examples
    --------
    >>> from sqlearn.feature_selection._scores import finish_score
    >>> stats = [(0, "no", 2, 0.0, 0.0), (0, "yes", 2, 4.0, 8.0)]
    >>> finish_score("f_classif", {"stats": stats, "low": 1.0})
    inf
    >>> finish_score("chi2", {"stats": stats, "low": 1.0})
    2.0
    """
    if score == "f_classif":
        return _f_classif(values)
    if score == "chi2":
        return _chi2(values)
    return _f_regression(values)
