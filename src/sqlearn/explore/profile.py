"""`profile`: one row per column, with the counts and statistics of each."""

from typing import Any

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._config import connection, get_config
from sqlearn._diagnose import exploring_out_of_memory
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import Source, read
from sqlearn._memory import duckdb_limit
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector, _is_numeric, is_text
from sqlearn.explore._common import answer, columns, literal, missing_sql

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


_SCAN_COLUMNS = 20
"""How many columns a statement of the scan reads.

DuckDB reads a Parquet file a row group at a time on each thread, holding
every column the statement reads (issue #68). On 12.5 million rows of 200
doubles in 122,880-row groups, 8 threads (2026-11-21): under a 1 GB
``memory_limit`` 20 columns peaked at 0.66 GB and 40 at 1.09 GB, 80 ran out;
under 2 GB, 80 fit and 200 ran out."""
_EXACT_COLUMNS = 20
"""The most columns a group of exact distinct counts and quartiles holds."""
_VALUE_BYTES = 32
"""The memory an exact distinct count and quartiles hold for each value.

Measured on 12.5 million rows of 200 random doubles, 8 threads, a 2 GB
``memory_limit`` (2026-11-21): groups of 2 and 4 columns profiled all 200
and a group of 6 ran out (so 27 to 40 bytes a value of the limit); the
process's peak grew by about 20 bytes a value for the count and 11 for
the quartiles. A group holds as many
columns as ``memory_limit`` holds rows of this size, at least one and at
most `_EXACT_COLUMNS`."""


def _fetch(source: Source, aggregates: list[str]) -> tuple[Any, ...]:
    """Run one aggregate statement over the data and return its one row."""
    return source.relation.aggregate(", ".join(aggregates)).fetchall()[0]


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


def _counted(condition: str) -> str:
    """Return the rows where a condition holds, 0 on no rows (`count_if`'s NULL)."""
    return f"count(CASE WHEN {condition} THEN 1 END)"


def _statistics(kind: str, name: str, missing: str) -> list[str]:
    """Return the scan's aggregates that describe a column's kind, in order.

    These keep a small state each (counts, sums, extremes, moments), so a
    scan statement holds them for its whole block. Values are left out by
    ``CASE`` (an aggregate passes over NULL; see `_counted`), never by
    ``FILTER``: DuckDB gives each filtered aggregate its own copy of the
    statement's inputs, so filtered aggregates over many columns hold
    memory that grows with the square of the columns, outside
    ``memory_limit``.
    """
    column = quote(name)
    if kind == "boolean":
        return [f"avg(CAST({column} AS DOUBLE))"]
    if kind == "number":
        number = f"CAST({column} AS DOUBLE)"
        finite = f"CASE WHEN isfinite({number}) THEN {number} END"
        return [
            f"avg({finite})",
            f"stddev_samp({finite})",
            f"min({finite})",
            f"max({finite})",
            _counted(f"isfinite({number}) AND {number} = 0"),
            _counted(f"isfinite({number}) AND {number} < 0"),
            _counted(f"isinf({number})"),
            f"skewness({finite})",
            f"kurtosis({finite})",
        ]
    if kind == "text":
        length = f"CASE WHEN NOT {missing} THEN length({column}) END"
        return [f"min({length})", f"max({length})"]
    if kind == "date":
        return [f"min({column})::VARCHAR", f"max({column})::VARCHAR"]
    return []


def _holistic(kind: str, name: str, missing: str, exact: bool) -> list[str]:
    """Return a column's distinct count and, for a number, its quartiles.

    Exact, these keep every value (a hash for the count, a sort for the
    quartiles), so they run in groups of columns sized to ``memory_limit``
    (`_VALUE_BYTES`); estimated, a small state each, so they join the scan.
    """
    column = quote(name)
    present = f"CASE WHEN NOT {missing} THEN {column} END"
    count = "count(DISTINCT {})" if exact else "approx_count_distinct({})"
    found = [count.format(present)]
    if kind == "number":
        number = f"CAST({column} AS DOUBLE)"
        finite = f"CASE WHEN isfinite({number}) THEN {number} END"
        quantile = "quantile_cont" if exact else "approx_quantile"
        found.append(f"{quantile}({finite}, {_QUARTILES})")
    return found


_POSITIONS = {
    "boolean": [7],
    "number": [7, 8, 9, 13, 14, 15, 16, 17, 18],
    "text": [19, 20],
    "date": [21, 22],
    "other": [],
}
"""Where each of the scan's statistics lands in a row of `_RESULT`."""


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

    A scan reads every column once for its counts, extremes and moments,
    20 columns a statement, since DuckDB holds a Parquet row group of every
    column a statement reads on each thread. The exact distinct counts and
    quartiles keep every value (a hash and a sort, held in memory), so they
    follow in groups of columns, a statement each that reads only its
    group's columns. A group holds as many columns as DuckDB's
    ``memory_limit`` holds at about 32 bytes a row, from 1 to 20: on 12.5
    million rows and a 2 GB limit, 4. The exact profile reads the data once
    more per group, so each column twice in all. With ``exact=False`` the
    estimates, a small state each, join the scan, and each column is read
    once.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to profile; by default all. A name must be a column.
    exact : bool, default True
        Count distinct values and take the quartiles exactly; False
        estimates them (HyperLogLog and t-digest), in less memory and one
        read of the data.
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
        `high_cardinality` is not a non-negative integer, or DuckDB runs
        out of memory; the fix then names ``exact=False`` first when the
        profile is exact.

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
    kinds = {name: _kind(types[name]) for name in names}
    try:
        rel = _profile(source, names, types, kinds, exact, id_rows, high_cardinality)
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc, source.relation.sql_query(), "profile", estimates=exact
        ) from exc
    return to_output(rel, out if out is not None else get_config().out)


def _gather(
    source: Source,
    names: list[str],
    types: dict[str, DuckDBPyType],
    kinds: dict[str, str],
    exact: bool,
) -> tuple[int, list[list[Any]]]:
    """Return the rows and each column's values, in the statements' order.

    A column's values are its missing count, its kind's statistics, its
    distinct count and, for a number, its quartiles. The scan, in blocks of
    `_SCAN_COLUMNS` columns, reads all but the exact distinct counts and
    quartiles, which follow in groups, a statement each, sized by the rows
    the scan counted.
    """
    absent = [missing_sql(name, types[name]) for name in names]
    scan: list[list[tuple[int, str]]] = []
    holistic: list[list[tuple[int, str]]] = []
    for k, name in enumerate(names):
        cheap = [(k, _counted(absent[k]))]
        cheap += [(k, a) for a in _statistics(kinds[name], name, absent[k])]
        held = [(k, a) for a in _holistic(kinds[name], name, absent[k], exact)]
        if exact:
            holistic.append(held)
        else:
            cheap += held
        scan.append(cheap)
    found: list[list[Any]] = [[] for _ in names]
    blocks = [
        [a for cheap in scan[start : start + _SCAN_COLUMNS] for a in cheap]
        for start in range(0, len(scan), _SCAN_COLUMNS)
    ] or [[]]
    rows = _run(source, [(-1, "count(*)"), *blocks[0]], found)
    for block in blocks[1:]:
        _run(source, block, found)
    size = max(
        1,
        min(_EXACT_COLUMNS, duckdb_limit(connection()) // max(1, rows * _VALUE_BYTES)),
    )
    for start in range(0, len(holistic), size):
        _run(
            source, [a for held in holistic[start : start + size] for a in held], found
        )
    return rows, found


def _run(
    source: Source, statement: list[tuple[int, str]], found: list[list[Any]]
) -> int:
    """Run one statement, append each column's values, return the rows counted."""
    rows = 0
    fetched = _fetch(source, [aggregate for _, aggregate in statement])
    for (k, _), value in zip(statement, fetched, strict=True):
        if k < 0:
            rows = int(value)
        else:
            found[k].append(value)
    return rows


def _profile(
    source: Source,
    names: list[str],
    types: dict[str, DuckDBPyType],
    kinds: dict[str, str],
    exact: bool,
    id_rows: int,
    high_cardinality: int,
) -> duckdb.DuckDBPyRelation:
    """Run the scan and the groups, and gather their values into the result."""
    rows, found = _gather(source, names, types, kinds, exact)
    values = []
    for name, held in zip(names, found, strict=True):
        missing, *statistics = held[: 1 + len(_POSITIONS[kinds[name]])]
        distinct, *quartiles = held[1 + len(statistics) :]
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
        for target, value in zip(_POSITIONS[kinds[name]], statistics, strict=True):
            row[target] = value
        if quartiles and quartiles[0] is not None:
            row[10:13] = quartiles[0]
        is_text = kinds[name] == "text"
        row += [types[name].id in _INTEGERS or is_text, is_text]
        values.append(f"({', '.join(literal(v) for v in row)})")
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
    return answer(f"SELECT {', '.join(select)} FROM {body}")
