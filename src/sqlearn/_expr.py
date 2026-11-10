"""Expression helpers: the DuckDB expressions steps build their SQL from."""

import duckdb
from duckdb import Expression

__all__ = [
    "MODE",
    "QUANTILE",
    "STD",
    "TARGET_STATS",
    "VAR",
    "const",
    "is_missing",
    "quote",
    "target_stats",
]


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

STD = "__sqlearn_std"
"""The name of the standard deviation marker: ``__sqlearn_std(x)``.

Not a DuckDB function. The compositor computes the population standard
deviation of `x` (its present values, as DOUBLE) in two passes, each a stage
of its own: the mean with the compensated ``favg``, then
``sqrt(favg((x - mean) ^ 2))`` over the rows beside that one mean (issue
#28). DuckDB's one-pass ``stddev_pop`` drifts further from the exact value.
"""

VAR = "__sqlearn_var"
"""The name of the variance marker: ``__sqlearn_var(x)``.

Not a DuckDB function. The population variance of `x`, from the same two
passes as `STD` (issue #42): ``favg((x - mean) ^ 2)``. The marker and the
standard deviation's of one expression share them.
"""


TARGET_STATS = "__sqlearn_target_stats"
"""The name of the grouped marker: ``__sqlearn_target_stats(x, y, fold)``.

Not a DuckDB function. The compositor computes it in a ``GROUP BY fold, x``
stage of its own (NULL is a category, as is NaN), returning per inner fold
and category the count, and the sum and the sum of squares of ``y -
min(y)`` (the target shifted by its minimum over every row, so whole values
stay exact and a large offset costs no digits): what a step learning
from the target needs to learn on every inner fold's complement at once.
The learned value is the list of ``(fold, category, count, sum, sum of
squares)`` tuples, sorted by fold, then category.
"""


def target_stats(x: Expression, y: Expression, fold: Expression) -> Expression:
    """Return the grouped marker counting and summing `y` per fold and category.

    Parameters
    ----------
    x : duckdb.Expression
        The column whose values are the categories.
    y : duckdb.Expression
        The target, as a number.
    fold : duckdb.Expression
        Each row's inner fold (`sqlearn._compose.inner_fold`).

    Returns
    -------
    duckdb.Expression
        The marker; see `TARGET_STATS`.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._expr import target_stats
    >>> x, y, f = (duckdb.ColumnExpression(c) for c in "xyf")
    >>> str(target_stats(x, y, f))
    '__sqlearn_target_stats(x, y, f)'
    """
    return _call(TARGET_STATS, x, y, fold)


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
