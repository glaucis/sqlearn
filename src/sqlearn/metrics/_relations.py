"""The relation helper the table and curve metrics share (ADR 0049)."""

import duckdb

from sqlearn._errors import InternalError

SOURCE = "_sqlearn_rows"
"""The name the rows go by inside the SQL of a table or curve metric."""


def select(
    rel: duckdb.DuckDBPyRelation, sql: str, name: str = SOURCE
) -> duckdb.DuckDBPyRelation:
    """Return the relation of a SELECT over `rel`, which the SQL calls `name`.

    The result lives on `rel`'s own connection, so it joins with `rel`.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The rows the SELECT reads.
    sql : str
        The SELECT, naming the rows `name`.
    name : str, default SOURCE
        The name `rel` goes by inside `sql`.

    Returns
    -------
    duckdb.DuckDBPyRelation
        The SELECT's result, lazy, on `rel`'s connection.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn.metrics._relations import select
    >>> rel = duckdb.sql("SELECT 1 AS a")
    >>> select(rel, "SELECT a + 1 AS b FROM _sqlearn_rows").fetchall()
    [(2,)]
    """
    got = rel.query(name, sql)
    if got is None:  # a SELECT always gives a relation
        msg = "DuckDB gave no relation for a SELECT"
        raise InternalError(msg)
    return got
