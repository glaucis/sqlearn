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
    """Return the mean of `x`, summed with compensation.

    Builds DuckDB's ``favg``, which sums with Kahan's compensation: on
    100,000 values it lands on the double nearest the exact mean, where the
    plain ``avg`` drifted by 119 ULPs (``validation/``, ruling 18). The
    result is DOUBLE. It is NaN, not infinity, when the data holds an infinity
    or the sum overflows. It prints as ``favg``, not ``avg``.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``favg(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.avg(duckdb.ColumnExpression("age")))
    'favg("age")'
    """
    return _call("favg", x)


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

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.stddev_pop(duckdb.ColumnExpression("age")))
    'stddev_pop("age")'
    """
    return _call("stddev_pop", x)


MEDIAN = "__sqlearn_median"
"""The name of the function `median` returns: a marker, not a DuckDB function.

The compositor finds it at the top of a learned value and writes the median
by sorting (see `sqlearn._compose`), because DuckDB's own ``median`` keeps a
column's values in memory and so cannot learn from data larger than memory.
"""


def median(x: Expression) -> Expression:
    """Return the median of `x`, computed by sorting so it runs larger than memory.

    The result is a marker the compositor recognises; it must be a whole
    learned value (``{"value": sq.median(x)}``), not part of a larger
    expression. The compositor computes it from the values sorted by DuckDB,
    which spills the sort to disk when the data does not fit in memory:
    missing values (NULL, and NaN) are left out, the middle value is taken,
    or the two middle ones interpolated halfway as DuckDB's ``median`` does,
    as DOUBLE. With no value to take, the median is NULL. `x` must be numeric.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        The marker ``__sqlearn_median(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.median(duckdb.ColumnExpression("age")))
    '__sqlearn_median("age")'
    """
    return _call(MEDIAN, x)


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

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.count(duckdb.ColumnExpression("age")))
    'count("age")'
    """
    return _call("count", x)


def distinct_values(x: Expression) -> Expression:
    """Return the sorted list of the distinct values of `x`.

    NULL is not a value; with no value at all the list is empty. The values
    are counted in a hash table (``histogram``), so the memory this takes
    grows with the number of distinct values, not with the number of rows:
    a column of a few categories is learned from data larger than memory.

    Parameters
    ----------
    x : duckdb.Expression
        The column or expression to aggregate.

    Returns
    -------
    duckdb.Expression
        ``COALESCE(list_sort(map_keys(histogram(x))), [])``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.distinct_values(duckdb.ColumnExpression("age")))
    'COALESCE(list_sort(map_keys(histogram("age"))), [])'
    """
    keys = _call("list_sort", _call("map_keys", _call("histogram", x)))
    return duckdb.CoalesceOperator(keys, duckdb.ConstantExpression([]))


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

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> con = duckdb.connect()
    >>> rel = con.sql("SELECT * FROM (VALUES (1.0), (NULL)) t(a)")
    >>> rel.select(sq.is_missing(duckdb.ColumnExpression("a"))).fetchall()
    [(False,), (True,)]
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

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.const(3))
    '3'
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

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> sq._expr.quote('a"b')
    '"a""b"'
    """
    return '"' + name.replace('"', '""') + '"'
