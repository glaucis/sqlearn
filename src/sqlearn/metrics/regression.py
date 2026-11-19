"""Regression metrics, each one aggregate query.

The metrics are rmse, mae, r2, mse, max_error, median_absolute_error,
mape, explained_variance, msle and rmsle.
"""

from dataclasses import dataclass

import duckdb
from duckdb import Expression

from sqlearn._expr import const
from sqlearn.metrics.accuracy import Metric

__all__ = [
    "LogError",
    "explained_variance",
    "mae",
    "mape",
    "max_error",
    "median_absolute_error",
    "mse",
    "msle",
    "r2",
    "rmse",
    "rmsle",
]


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _error(y: Expression, p: Expression) -> Expression:
    return y.cast("DOUBLE") - p.cast("DOUBLE")


def _rmse(y: Expression, p: Expression) -> Expression:
    error = _error(y, p)
    return _fn("sqrt", _fn("favg", error * error))


def _mae(y: Expression, p: Expression) -> Expression:
    return _fn("favg", _fn("abs", _error(y, p)))


def _mse(y: Expression, p: Expression) -> Expression:
    error = _error(y, p)
    return _fn("favg", error * error)


def _max_error(y: Expression, p: Expression) -> Expression:
    return _fn("max", _fn("abs", _error(y, p)))


def _median_absolute_error(y: Expression, p: Expression) -> Expression:
    return _fn("median", _fn("abs", _error(y, p)))


# numpy's ``finfo(float).eps``: scikit-learn divides by at least this, so a
# zero target gives a huge number rather than an error.
_EPSILON = 2.220446049250313e-16


def _mape(y: Expression, p: Expression) -> Expression:
    denominator = _fn("greatest", _fn("abs", y.cast("DOUBLE")), const(_EPSILON))
    return _fn("favg", _fn("abs", _error(y, p)) / denominator)


def _r2(y: Expression, p: Expression) -> Expression:
    # One minus the residual over the total sum of squares.
    #
    # The residual sum is compensated (``fsum``, ADR 0033). The total sum is
    # DuckDB's population variance (a running update about the mean, not
    # compensated) times the count; a sum of squares minus a squared sum would
    # cancel for a target far from zero. A constant target scores 1 when
    # predicted exactly and 0 otherwise, as scikit-learn's r2_score has it.
    error = _error(y, p)
    residual = _fn("fsum", error * error)
    total = _fn("var_pop", y.cast("DOUBLE")) * _fn("count", y)
    constant = duckdb.CaseExpression(residual == const(0.0), const(1.0)).otherwise(
        const(0.0)
    )
    return duckdb.CaseExpression(total == const(0.0), constant).otherwise(
        const(1.0) - residual / total
    )


def _ev(y: Expression, p: Expression) -> Expression:
    # One minus the error's variance over the target's variance, both
    # DuckDB's population variance (as ``_r2`` explains for the target; the
    # error's is the same kind of running update about its mean, so an offset
    # in the errors costs no digits). A constant target (minimum equals
    # maximum, exact where a variance can be one rounding off) scores 1 when
    # the error's variance is 0 and 0 otherwise, as scikit-learn's
    # explained_variance_score has it.
    target = y.cast("DOUBLE")
    numerator = _fn("var_pop", _error(y, p))
    denominator = _fn("var_pop", target)
    constant = duckdb.CaseExpression(numerator == const(0.0), const(1.0)).otherwise(
        const(0.0)
    )
    return duckdb.CaseExpression(
        _fn("min", target) == _fn("max", target), constant
    ).otherwise(const(1.0) - numerator / denominator)


def _log1p(x: Expression) -> Expression:
    # Kahan's log1p, which DuckDB lacks: ln(1 + x) loses every digit of a
    # small x, so scale ln(u) by x / (u - 1), where the rounding of u = 1 + x
    # cancels. NaN or -inf (not an error) at or below -1, where a metric
    # refuses the row after the aggregate.
    u = const(1.0) + x
    return duckdb.CaseExpression(u == const(1.0), x).otherwise(
        _fn("ln", u) * x / (u - const(1.0))
    )


def _log_error(y: Expression, p: Expression) -> Expression:
    return _log1p(y.cast("DOUBLE")) - _log1p(p.cast("DOUBLE"))


def _msle(y: Expression, p: Expression) -> Expression:
    error = _log_error(y, p)
    return _fn("favg", error * error)


def _rmsle(y: Expression, p: Expression) -> Expression:
    return _fn("sqrt", _msle(y, p))


@dataclass(frozen=True)
class LogError(Metric):
    """A metric on the logarithm of 1 plus each value (msle, rmsle).

    It refuses a target or a prediction at or below -1, where that
    logarithm is undefined, as scikit-learn does.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.rmsle.greater_is_better
    False
    """

    def _outside(
        self, y: Expression, p: Expression
    ) -> list[tuple[Expression, str, str]]:
        limit = const(-1.0)
        why = (
            "the logarithm of 1 plus a value is undefined at or below -1, "
            "and scikit-learn refuses such values too."
        )
        return [
            (y.cast("DOUBLE") <= limit, "a target at or below -1", why),
            (p.cast("DOUBLE") <= limit, "a prediction at or below -1", why),
        ]


rmse = Metric("rmse", _rmse, False)
mae = Metric("mae", _mae, False)
r2 = Metric("r2", _r2, True)
mse = Metric("mse", _mse, False)
max_error = Metric("max_error", _max_error, False)
median_absolute_error = Metric("median_absolute_error", _median_absolute_error, False)
mape = Metric("mape", _mape, False)
explained_variance = Metric("explained_variance", _ev, True)
msle = LogError("msle", _msle, False)
rmsle = LogError("rmsle", _rmsle, False)
