"""`profile`: one row per column, with the counts and statistics of each."""

import math
from typing import Any

from duckdb.sqltypes import DuckDBPyType

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector, _is_numeric, is_text
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
_FILLED = len(_RESULT)
"""How many leading columns are filled from the scan."""
_QUARTILES = "[0.25, 0.5, 0.75]"
_INTEGERS = {
    "tinyint", "smallint", "integer", "bigint", "hugeint",
    "utinyint", "usmallint", "uinteger", "ubigint", "uhugeint",
}  # fmt: skip
"""The integer types, the only numbers a key can be."""
_NOTES = """list_filter([
    CASE WHEN v.v2 > 0 AND v.v3 = v.v2 THEN 'all-missing' END,
    CASE WHEN v.v5 = 1 THEN 'constant' END,
    CASE WHEN v.v23 AND v.v2 - v.v3 >= {id_rows} AND v.v5 = v.v2 - v.v3
        THEN 'id-like' END,
    CASE WHEN v.v24 AND v.v5 > {high_cardinality}
        AND v.v5 * 2 > v.v2 - v.v3
        AND NOT (v.v2 - v.v3 >= {id_rows} AND v.v5 = v.v2 - v.v3)
        THEN 'high-cardinality' END
], lambda x: x IS NOT NULL)"""
"""The notes, in their one order, from the counted row (`v2` rows, `v3`
missing, `v5` distinct; `v23` is a key's type, `v24` a text type)."""


def _count(name: str, value: object) -> int:
    """Return a setting that must be a non-negative integer, or refuse it."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        default = 20 if name == "id_rows" else 50
        raise SqlearnError(
            f"`profile` was given {name}={value!r}, which is not a "
            f"non-negative integer. Why: it counts rows or distinct values, "
            f"so it is a whole number from 0. Fix: pass an integer such as "
            f"{name}={default}."
        )
    return value


def _is_date(dtype: DuckDBPyType) -> bool:
    """Say whether a type is a date, a time or a timestamp."""
    return str(dtype).startswith(("DATE", "TIME"))


def _kind(dtype: DuckDBPyType) -> str:
    """Return how a column is described: number, boolean, text, date or other."""
    if str(dtype) == "BOOLEAN":
        return "boolean"
    if _is_numeric(dtype):
        return "number"
    if is_text(dtype):
        return "text"
    return "date" if _is_date(dtype) else "other"


def _statistics(kind: str, name: str, missing: str, exact: bool) -> list[str]:
    """Return the aggregates that describe a column of this kind, in order."""
    column = quote(name)
    if kind == "boolean":
        return [f"avg(CAST({column} AS DOUBLE))"]
    if kind == "number":
        number = f"CAST({column} AS DOUBLE)"
        finite = f"FILTER (WHERE isfinite({number}))"
        quantile = "quantile_cont" if exact else "approx_quantile"
        return [
            f"avg({number}) {finite}",
            f"stddev_samp({number}) {finite}",
            f"min({number}) {finite}",
            f"{quantile}({number}, {_QUARTILES}) {finite}",
            f"max({number}) {finite}",
            f"count(*) FILTER (WHERE isfinite({number}) AND {number} = 0)",
            f"count(*) FILTER (WHERE isfinite({number}) AND {number} < 0)",
            f"count(*) FILTER (WHERE isinf({number}))",
            f"skewness({number}) {finite}",
            f"kurtosis({number}) {finite}",
        ]
    if kind == "text":
        present = f"FILTER (WHERE NOT {missing})"
        return [f"min(length({column})) {present}", f"max(length({column})) {present}"]
    if kind == "date":
        return [f"min({column})::VARCHAR", f"max({column})::VARCHAR"]
    return []


_POSITIONS = {
    "boolean": [7],
    "number": [7, 8, 9, None, 13, 14, 15, 16, 17, 18],
    "text": [19, 20],
    "date": [21, 22],
    "other": [],
}
"""Where each aggregate lands in a row of `_RESULT` (None: the quartiles)."""


def _literal(value: str | float | bool | None) -> str:
    """Write a fetched value as a SQL literal."""
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
        The fewest non-missing values for an integer or text column to be
        flagged ``id-like``, when all of them are distinct. With
        ``exact=False`` the distinct count is approximate, so ``id-like``
        may not fire.
    high_cardinality : int, default 50
        The most distinct values a text column has before it is flagged
        ``high-cardinality``, which also needs more than half its
        non-missing values distinct, and never goes with ``id-like``.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        One row per column: ``column``, ``type``, ``rows``, ``missing``,
        ``missing_share``, ``distinct``, ``distinct_share``, the numeric,
        text and date statistics, ``exact`` and ``notes``: a list of flags
        among ``all-missing``, ``constant``, ``id-like`` and
        ``high-cardinality``, in that order. The result is computed now
        and kept, so it outlives `data`.

    Raises
    ------
    SqlearnError
        If a name in `cols` is not a column, or `id_rows` or
        `high_cardinality` is not a non-negative integer.

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
    id_rows = _count("id_rows", id_rows)
    high_cardinality = _count("high_cardinality", high_cardinality)
    source = read(data)
    names = columns(source, cols, function="profile")
    types = dict(source.schema)
    exact = bool(exact)
    aggregates = ["count(*)"]
    kinds = {name: _kind(types[name]) for name in names}
    for name in names:
        column = quote(name)
        missing = missing_sql(name, types[name])
        distinct = (
            f"count(DISTINCT {column}) FILTER (WHERE NOT {missing})"
            if exact
            else f"approx_count_distinct({column}) FILTER (WHERE NOT {missing})"
        )
        aggregates += [f"count(*) FILTER (WHERE {missing})", distinct]
        aggregates += _statistics(kinds[name], name, missing, exact)
    counts = source.relation.aggregate(", ".join(aggregates)).fetchall()[0]
    rows = counts[0]
    values = []
    cursor = 1
    for name in names:
        missing, distinct = counts[cursor : cursor + 2]
        cursor += 2
        present = rows - missing
        row: list[str | float | bool | None] = [None] * _FILLED
        row[:7] = [
            name,
            str(types[name]),
            rows,
            missing,
            None if rows == 0 else missing / rows,
            distinct,
            None if present == 0 else min(distinct / present, 1.0),
        ]
        for target, value in zip(
            _POSITIONS[kinds[name]], counts[cursor:], strict=False
        ):
            if target is None:
                row[10:13] = value if value is not None else [None] * 3
            else:
                row[target] = value
        cursor += len(_POSITIONS[kinds[name]])
        is_text = kinds[name] == "text"
        row += [types[name].id in _INTEGERS or is_text, is_text]
        values.append(f"({', '.join(_literal(v) for v in row)})")
    labels = [f"v{i}" for i in range(_FILLED + 2)]
    if values:
        body = f"(VALUES {', '.join(values)}) AS v({', '.join(labels)})"
    else:
        nulls = ", ".join("NULL" for _ in labels)
        body = f"(SELECT {nulls} WHERE false) AS v({', '.join(labels)})"
    select = [
        f"CAST(v.{alias} AS {kind}) AS {quote(label)}"
        for alias, (label, kind) in zip(labels, _RESULT, strict=False)
    ]
    notes = _NOTES.format(id_rows=id_rows, high_cardinality=high_cardinality)
    select += [f'{exact!r}::BOOLEAN AS "exact"', f'{notes}::VARCHAR[] AS "notes"']
    sql = f"SELECT {', '.join(select)} FROM {body}"
    rel = answer(sql)
    return to_output(rel, out if out is not None else get_config().out)
