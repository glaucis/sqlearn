"""Expression helpers: the DuckDB expressions steps build their SQL from."""

import duckdb
from duckdb import Expression

__all__ = ["MODE", "QUANTILE", "const", "is_missing", "quote"]


def _call(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


QUANTILE = "__sqlearn_quantile"
"""The name of the quantile marker: ``__sqlearn_quantile(x, q, method)``.

Not a DuckDB function. `sqlearn.agg` builds it and the compositor finds it
anywhere in a learned value and computes the quantile by sorting (see
`sqlearn._compose`), because DuckDB's own ``quantile_cont`` keeps a column's
values in memory and so cannot learn from data larger than memory.
"""

MODE = "__sqlearn_mode"
"""The name of the mode marker: ``__sqlearn_mode(x)``.

Not a DuckDB function. The compositor computes the mode by counting each
value in a ``GROUP BY``, which spills to disk, and breaks a tie to the
smallest value, which DuckDB's ``mode`` does not promise.
"""


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
    >>> rel.select(sq.fn.is_missing(duckdb.ColumnExpression("a"))).fetchall()
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
    >>> str(sq.fn.const(3))
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
