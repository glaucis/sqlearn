"""Expression helpers: the DuckDB expressions steps build their SQL from."""

import duckdb
from duckdb import Expression

__all__ = [
    "avg",
    "const",
    "count",
    "distinct_values",
    "is_missing",
    "median",
    "quote",
    "stddev_pop",
]


def _call(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def avg(x: Expression) -> Expression:
    """Return the mean of `x`.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``avg(x)``.
    """
    return _call("avg", x)


def stddev_pop(x: Expression) -> Expression:
    """Return the population standard deviation of `x`.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``stddev_pop(x)``.
    """
    return _call("stddev_pop", x)


def median(x: Expression) -> Expression:
    """Return the median of `x`.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``median(x)``.
    """
    return _call("median", x)


def count(x: Expression) -> Expression:
    """Return the number of non-NULL values of `x`.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``count(x)``.
    """
    return _call("count", x)


def distinct_values(x: Expression) -> Expression:
    """Return the sorted list of the distinct values of `x`.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``list_sort(list_distinct(list(x)))``.
    """
    return _call("list_sort", _call("list_distinct", _call("list", x)))


def is_missing(x: Expression) -> Expression:
    """Return whether `x` is NULL or NaN.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to test.

    Returns
    -------
    duckdb.Expression
        ``x IS NULL OR isnan(x::DOUBLE)``.
    """
    return x.isnull() | _call("isnan", x.cast("DOUBLE"))


def const(v: object) -> Expression:
    """Return the constant `v` as an expression.

    Parameters
    ----------
    v : object
        The Python value.

    Returns
    -------
    duckdb.Expression
        The constant.
    """
    return duckdb.ConstantExpression(v)


def quote(name: str) -> str:
    """Quote `name` as a SQL identifier.

    Parameters
    ----------
    name : str
        Any column or table name.

    Returns
    -------
    str
        The name in double quotes, inner quotes doubled.
    """
    return '"' + name.replace('"', '""') + '"'
