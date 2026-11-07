"""Regression metrics: rmse, mae and r2, each one aggregate query."""

import duckdb
from duckdb import Expression

from sqlearn._expr import const
from sqlearn.metrics.accuracy import Metric

__all__ = ["mae", "r2", "rmse"]


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _error(y: Expression, p: Expression) -> Expression:
    return y.cast("DOUBLE") - p.cast("DOUBLE")


def _rmse(y: Expression, p: Expression) -> Expression:
    error = _error(y, p)
    return _fn("sqrt", _fn("favg", error * error))


def _mae(y: Expression, p: Expression) -> Expression:
    return _fn("favg", _fn("abs", _error(y, p)))


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


rmse = Metric("rmse", _rmse, False)
mae = Metric("mae", _mae, False)
r2 = Metric("r2", _r2, True)
