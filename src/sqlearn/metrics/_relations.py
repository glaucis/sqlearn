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
    """
    got = rel.query(name, sql)
    if got is None:  # a SELECT always gives a relation
        msg = "DuckDB gave no relation for a SELECT"
        raise InternalError(msg)
    return got
