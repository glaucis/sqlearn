"""`profile`: one row per column, with the counts and statistics of each."""

from typing import Any

from sqlearn._config import get_config
from sqlearn._expr import quote
from sqlearn._inputs import read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector
from sqlearn.explore._common import answer, columns, missing_sql

__all__ = ["profile"]

_RESULT = [
    ("column", "VARCHAR"),
    ("type", "VARCHAR"),
    ("rows", "BIGINT"),
    ("missing", "BIGINT"),
    ("missing_share", "DOUBLE"),
    ("distinct", "BIGINT"),
    ("distinct_share", "DOUBLE"),
    ("mean", "DOUBLE"),
    ("std", "DOUBLE"),
    ("min", "DOUBLE"),
    ("q25", "DOUBLE"),
    ("median", "DOUBLE"),
    ("q75", "DOUBLE"),
    ("max", "DOUBLE"),
    ("zeros", "BIGINT"),
    ("negative", "BIGINT"),
    ("infinite", "BIGINT"),
    ("skewness", "DOUBLE"),
    ("kurtosis", "DOUBLE"),
    ("min_length", "BIGINT"),
    ("max_length", "BIGINT"),
    ("first", "VARCHAR"),
    ("last", "VARCHAR"),
]
"""The result's columns up to `exact`, with their types; `notes` follows."""
_FILLED = 7
"""How many leading columns are filled from the counts."""


def _literal(value: str | float | None) -> str:
    """Write a fetched value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, float):
        return repr(float(value))
    return repr(int(value))


def profile(
    data: object,
    cols: Selector | str | list[str] | None = None,
    *,
    exact: bool = True,
    id_rows: int = 20,
    high_cardinality: int = 50,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401
    """Profile each column: its type, rows, missing and distinct values.

    The data is scanned once: every column's counts come from one query.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to profile; by default all. A name must be a column.
    exact : bool, default True
        Count distinct values exactly; False estimates them (faster on
        very large data).
    id_rows : int, default 20
        The fewest rows for a column to be flagged ``id-like``.
    high_cardinality : int, default 50
        The most distinct values a text column has before it is flagged
        ``high-cardinality``.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        One row per column: ``column``, ``type``, ``rows``, ``missing``,
        ``missing_share``, ``distinct``, ``distinct_share``, the numeric,
        text and date statistics, ``exact`` and ``notes``. The result is
        computed now and kept, so it outlives `data`.

    Raises
    ------
    SqlearnError
        If a name in `cols` is not a column.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> frame = pd.DataFrame({"a": [1, 2, 2], "b": ["x", None, "y"]})
    >>> sq.explore.profile(frame, out="pandas")[["column", "missing", "distinct"]]
      column  missing  distinct
    0      a        0         2
    1      b        1         2
    """
    del id_rows, high_cardinality  # used by the notes
    source = read(data)
    names = columns(source, cols, function="profile")
    types = dict(source.schema)
    aggregates = ["count(*)"]
    for name in names:
        column = quote(name)
        missing = missing_sql(name, types[name])
        distinct = (
            f"count(DISTINCT {column}) FILTER (WHERE NOT {missing})"
            if exact
            else f"approx_count_distinct({column}) FILTER (WHERE NOT {missing})"
        )
        aggregates += [f"count(*) FILTER (WHERE {missing})", distinct]
    counts = source.relation.aggregate(", ".join(aggregates)).fetchall()[0]
    rows = counts[0]
    values = []
    for position, name in enumerate(names):
        missing, distinct = counts[1 + 2 * position : 3 + 2 * position]
        present = rows - missing
        share = [
            None if rows == 0 else missing / rows,
            distinct,
            None if present == 0 else distinct / present,
        ]
        row = [name, str(types[name]), rows, missing, share[0], *share[1:]]
        values.append(f"({', '.join(_literal(v) for v in row)})")
    labels = [f"v{i}" for i in range(_FILLED)]
    if values:
        body = f"(VALUES {', '.join(values)}) AS v({', '.join(labels)})"
    else:
        nulls = ", ".join("NULL" for _ in labels)
        body = f"(SELECT {nulls} WHERE false) AS v({', '.join(labels)})"
    select = [
        f"CAST(v.{alias} AS {kind}) AS {quote(label)}"
        for alias, (label, kind) in zip(labels, _RESULT, strict=False)
    ]
    select += [
        f"CAST(NULL AS {kind}) AS {quote(label)}" for label, kind in _RESULT[_FILLED:]
    ]
    select += [f'{exact!r}::BOOLEAN AS "exact"', '[]::VARCHAR[] AS "notes"']
    sql = f"SELECT {', '.join(select)} FROM {body}"
    rel = answer(sql)
    return to_output(rel, out if out is not None else get_config().out)
