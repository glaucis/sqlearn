"""Column functions: build expressions steps use, such as ``sq.fn.ln``."""

import duckdb
from duckdb import Expression

from sqlearn._expr import const, is_missing

__all__ = [
    "abs",
    "coalesce",
    "const",
    "exp",
    "greatest",
    "is_missing",
    "least",
    "ln",
    "log10",
    "lower",
    "sqrt",
    "upper",
]


def _expr(value: object) -> Expression:
    return value if isinstance(value, Expression) else duckdb.ConstantExpression(value)


def _call(name: str, *args: object) -> Expression:
    return duckdb.FunctionExpression(name, *(_expr(a) for a in args))


def ln(x: Expression | object) -> Expression:
    """Return the natural logarithm of `x`.

    Parameters
    ----------
    x : duckdb.Expression or object
        The column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``ln(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.ln(duckdb.ColumnExpression("a")))
    'ln("a")'
    """
    return _call("ln", x)


def log10(x: Expression | object) -> Expression:
    """Return the base-10 logarithm of `x`.

    Parameters
    ----------
    x : duckdb.Expression or object
        The column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``log10(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.log10(duckdb.ColumnExpression("a")))
    'log10("a")'
    """
    return _call("log10", x)


def exp(x: Expression | object) -> Expression:
    """Return e raised to `x`.

    Parameters
    ----------
    x : duckdb.Expression or object
        The column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``exp(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.exp(duckdb.ColumnExpression("a")))
    'exp("a")'
    """
    return _call("exp", x)


def sqrt(x: Expression | object) -> Expression:
    """Return the square root of `x`.

    Parameters
    ----------
    x : duckdb.Expression or object
        The column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``sqrt(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.sqrt(duckdb.ColumnExpression("a")))
    'sqrt("a")'
    """
    return _call("sqrt", x)


def abs(x: Expression | object) -> Expression:
    """Return the absolute value of `x`.

    Parameters
    ----------
    x : duckdb.Expression or object
        The column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``abs(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.abs(duckdb.ColumnExpression("a")))
    'abs("a")'
    """
    return _call("abs", x)


def least(*xs: Expression | object) -> Expression:
    """Return the smallest of the values in each row.

    Parameters
    ----------
    *xs : duckdb.Expression or object
        The columns, expressions or plain values to compare.

    Returns
    -------
    duckdb.Expression
        ``least(x, ...)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.least(duckdb.ColumnExpression("a"), 10))
    'least("a", 10)'
    """
    return _call("least", *xs)


def greatest(*xs: Expression | object) -> Expression:
    """Return the largest of the values in each row.

    Parameters
    ----------
    *xs : duckdb.Expression or object
        The columns, expressions or plain values to compare.

    Returns
    -------
    duckdb.Expression
        ``greatest(x, ...)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.greatest(duckdb.ColumnExpression("a"), 0))
    'greatest("a", 0)'
    """
    return _call("greatest", *xs)


def lower(x: Expression | object) -> Expression:
    """Return `x` in lower case.

    Parameters
    ----------
    x : duckdb.Expression or object
        The text column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``lower(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.lower(duckdb.ColumnExpression("city")))
    'lower("city")'
    """
    return _call("lower", x)


def upper(x: Expression | object) -> Expression:
    """Return `x` in upper case.

    Parameters
    ----------
    x : duckdb.Expression or object
        The text column or expression (a plain value becomes a constant).

    Returns
    -------
    duckdb.Expression
        ``upper(x)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.upper(duckdb.ColumnExpression("city")))
    'upper("city")'
    """
    return _call("upper", x)


def coalesce(*xs: Expression | object) -> Expression:
    """Return the first value in each row that is not NULL.

    Parameters
    ----------
    *xs : duckdb.Expression or object
        The columns, expressions or plain values, in order of preference.

    Returns
    -------
    duckdb.Expression
        ``COALESCE(x, ...)``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.fn.coalesce(duckdb.ColumnExpression("a"), 0))
    'COALESCE("a", 0)'
    """
    return duckdb.CoalesceOperator(*(_expr(x) for x in xs))
