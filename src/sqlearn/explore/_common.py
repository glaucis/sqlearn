"""What the exploration functions share: choosing columns, answering, missing."""

import itertools
import math
from collections.abc import Sequence

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import Source
from sqlearn._selectors import Selector, to_selector

__all__ = ["LARGEST_LIMIT", "answer", "columns", "literal", "missing_sql"]

_tables = itertools.count()
LARGEST_LIMIT = 2**63 - 1
"""The largest count DuckDB's LIMIT takes: BIGINT's largest value."""
_LISTED = 10


def columns(
    source: Source,
    cols: Selector | str | Sequence[str] | None,
    *,
    function: str,
) -> list[str]:
    """Return the names of the columns an exploration function looks at.

    Parameters
    ----------
    source : Source
        The data read.
    cols : Selector or str or sequence of str or None
        None takes every column. A name or names must each be a column; a
        selector that chooses nothing gives an empty list.
    function : str
        The function's name, for the message.

    Returns
    -------
    list of str
        The names, in the schema's order.

    Raises
    ------
    SqlearnError
        If a plain name is not a column.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._inputs import read
    >>> from sqlearn.explore._common import columns
    >>> source = read(connection().sql("SELECT 1 AS a, 2 AS b"))
    >>> columns(source, ["b"], function="profile")
    ['b']
    """
    names = [name for name, _ in source.schema]
    if cols is None:
        return names
    if not isinstance(cols, Selector):
        asked = [cols] if isinstance(cols, str) else list(cols)
        for name in asked:
            if name not in names:
                listed = ", ".join(repr(n) for n in names[:_LISTED])
                if len(names) > _LISTED:
                    listed += ", …"
                raise SqlearnError(
                    f"`{function}` was given cols={name!r}, which is not a "
                    f"column. Why: a name in cols= must be a column of the data, so a "
                    f"typo is not passed over silently. Fix: pass one of {listed}."
                )
    return to_selector(cols).resolve(source.schema)


def answer(sql: str) -> duckdb.DuckDBPyRelation:
    """Run a query now and return its result as a table on the connection.

    Parameters
    ----------
    sql : str
        The query.

    Returns
    -------
    duckdb.DuckDBPyRelation
        A relation over a temporary table holding the result, so it outlives
        the data it was computed from.

    Examples
    --------
    >>> from sqlearn.explore._common import answer
    >>> answer("SELECT 1 AS a").fetchall()
    [(1,)]
    """
    con = connection()
    name = f"__sqlearn_explore_{next(_tables)}"
    con.execute(f"CREATE TEMP TABLE {quote(name)} AS {sql}")
    return con.table(name)


def missing_sql(name: str, dtype: DuckDBPyType) -> str:
    """Return the SQL that is true when a column's value is missing.

    Parameters
    ----------
    name : str
        The column.
    dtype : DuckDBPyType
        Its type: a float is missing when NULL or NaN, anything else when NULL.

    Returns
    -------
    str
        A boolean expression.

    Examples
    --------
    >>> from duckdb.sqltypes import DOUBLE
    >>> from sqlearn.explore._common import missing_sql
    >>> missing_sql("a", DOUBLE)
    '("a" IS NULL OR isnan("a"))'
    """
    column = quote(name)
    if dtype.id in {"float", "double"}:
        return f"({column} IS NULL OR isnan({column}))"
    return f"({column} IS NULL)"


def literal(value: str | float | bool | None) -> str:
    """Write a fetched value as a SQL literal.

    Parameters
    ----------
    value : str or float or bool or None
        The value.

    Returns
    -------
    str
        SQL that reads back as the value; NaN and infinities are cast from
        text.

    Examples
    --------
    >>> from sqlearn.explore._common import literal
    >>> literal("it's")
    "'it''s'"
    >>> literal(float("nan"))
    "'NaN'::DOUBLE"
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, float):
        if math.isnan(value):
            return "'NaN'::DOUBLE"
        if math.isinf(value):
            return "'inf'::DOUBLE" if value > 0 else "'-inf'::DOUBLE"
        return repr(float(value))
    return repr(int(value))
