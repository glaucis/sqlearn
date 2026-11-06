"""Helpers shared by the steps that learn over non-missing numeric values."""

import math

import duckdb
from duckdb import Expression

from sqlearn._errors import StepError
from sqlearn._expr import const
from sqlearn._step import Learned

__all__ = ["infinite", "refuse_all_missing", "refuse_infinite"]


def infinite(x: Expression) -> Expression:
    """Return the aggregate saying whether a column holds infinity.

    Learned beside a value that infinity would make meaningless, or that it
    would hide (a median), so `refuse_infinite` can refuse the column.

    Parameters
    ----------
    x : duckdb.Expression
        The column, of numbers.

    Returns
    -------
    duckdb.Expression
        Infinity where the column holds any infinite value, else 0.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn.preprocessing._missing import infinite
    >>> rel = duckdb.sql("SELECT * FROM (VALUES (1.0), ('inf'::DOUBLE)) t(a)")
    >>> rel.aggregate(infinite(duckdb.ColumnExpression("a"))).fetchall()
    [(inf,)]
    """
    flag = duckdb.CaseExpression(
        duckdb.FunctionExpression("isinf", x.cast("DOUBLE")),
        const(float("inf")),
    ).otherwise(const(0.0))
    return duckdb.FunctionExpression("max", flag)


def refuse_all_missing(x: Expression, learned: Learned, name: str) -> None:
    """Refuse a column whose learned `name` is None: it had no value to learn.

    The refusal is a `StepError` without step or position (0); the pipeline
    adds them. Nothing is checked while the value is still a placeholder.

    Parameters
    ----------
    x : duckdb.Expression
        The column.
    learned : Learned
        The values learned for the column.
    name : str
        The learned value that is None when every value was missing.

    Raises
    ------
    StepError
        If the learned value is None.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._step import Learned
    >>> from sqlearn.preprocessing._missing import refuse_all_missing
    >>> x = duckdb.ColumnExpression("a")
    >>> refuse_all_missing(x, Learned.values({"mean": 1.0}), "mean")
    """
    if learned.raw(name) is None:
        msg = (
            f"cannot learn from column {x.get_name()!r}: every value is "
            "missing, so there is nothing to learn from. Fix: drop the "
            "column, or exclude it with cols=."
        )
        raise StepError(msg, step="", position=0)


def refuse_infinite(x: Expression, learned: Learned, name: str) -> None:
    """Refuse a column whose learned `name` is infinite or NaN.

    Infinity in the data makes a mean or spread meaningless (scikit-learn
    refuses it too). The refusal is a `StepError` without step or position
    (0); the pipeline adds them.

    Parameters
    ----------
    x : duckdb.Expression
        The column.
    learned : Learned
        The values learned for the column.
    name : str
        The learned value to test.

    Raises
    ------
    StepError
        If the learned value is a number that is not finite.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._step import Learned
    >>> from sqlearn.preprocessing._missing import refuse_infinite
    >>> x = duckdb.ColumnExpression("a")
    >>> refuse_infinite(x, Learned.values({"mean": 1.0}), "mean")
    """
    value = learned.raw(name)
    if isinstance(value, int | float) and not math.isfinite(value):
        msg = (
            f"cannot learn from column {x.get_name()!r}: it contains "
            "infinity, which makes what is learned meaningless. Fix: "
            "replace the infinite values with NULL before this step."
        )
        raise StepError(msg, step="", position=0)
