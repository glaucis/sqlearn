"""`profile`: one row per column, with the counts and statistics of each."""

import math
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

Measured on 12.5 million rows of 200 random doubles, 8 threads,
``memory="4GB"``, a 1.8 GiB ``memory_limit`` (2026-11-21): groups of 2
and 4 columns profiled all 200 and a group of 6 ran out (so 27 to 40 bytes
a value of the limit); the
process's peak grew by about 20 bytes a value for the count and 11 for
the quartiles. These are doubles: long text values in a distinct count
may take more, and a group of them can still run out, when the error's
fix leads with ``exact=False``. A group holds as many
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


def _finite(name: str) -> str:
    """Return a column as a double, NULL where it is not finite."""
    number = f"CAST({quote(name)} AS DOUBLE)"
    return f"CASE WHEN isfinite({number}) THEN {number} END"


def _moments(name: str, mean: float) -> list[str]:
    """Return the compensated sums of a number's deviations to powers 1 to 4.

    The second pass over a number (issue #28, ADR 0033): ``fsum`` of the
    deviations about the scan's ``favg``, which one-pass power sums lose to
    cancellation when the values are far from 0. The first power is the
    rounding of that mean, which `_shape` takes back out.
    """
    deviation = f"({_finite(name)} - CAST({literal(float(mean))} AS DOUBLE))"
    square = f"({deviation} * {deviation})"
    return [
        f"fsum({deviation})",
        f"fsum({square})",
        f"fsum({square} * {deviation})",
        f"fsum({square} * {square})",
    ]


def _shape(
    n: int, sums: list[float | None]
) -> tuple[float | None, float | None, float | None]:
    """Return pandas' std (ddof 1), skewness and excess kurtosis from sums.

    `sums` are the sums of the deviations about the rounded mean to powers
    1 to 4, over `n` finite values; they are moved to the mean itself (the
    first sum over `n` is how far the rounded mean is from it) by the
    binomial shift. Each statistic is None where pandas' is undefined:
    below 2, 3 and 4 values, and the shape where the values do not vary.
    Each is None too where a sum it needs, or a power of `s2` it divides
    by, is not finite (deviations whose square, cube or fourth power
    overflows the largest double), where pandas gives inf or NaN.
    """
    known = [float(s) for s in sums if s is not None]
    if n < 2 or len(known) < len(sums):
        return None, None, None
    s1, r2, r3, r4 = known
    e = s1 / n
    # Products, not `**`: a float power that overflows raises in Python.
    s2 = r2 - n * e * e
    s3 = r3 - 3 * e * r2 + 2 * n * e * e * e
    s4 = r4 - 4 * e * r3 + 6 * e * e * r2 - 3 * n * e * e * e * e
    if not math.isfinite(s2):
        return None, None, None
    std = math.sqrt(s2 / (n - 1))
    if n < 3 or s2 == 0:
        return std, None, None
    spread = s2 * math.sqrt(s2)
    skewness = None
    if math.isfinite(s3) and math.isfinite(spread):
        skewness = n * math.sqrt(n - 1) / (n - 2) * s3 / spread
    if n < 4 or not (math.isfinite(s4) and math.isfinite(s2 * s2)):
        return std, skewness, None
    adjust = (n + 1) * (n - 1) / ((n - 2) * (n - 3))
    kurtosis = adjust * n * s4 / (s2 * s2) - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    return std, skewness, kurtosis


def _statistics(kind: str, name: str, missing: str) -> list[str]:
    """Return the scan's aggregates that describe a column's kind, in order.

    These keep a small state each (counts, sums, extremes), so a scan
    statement holds them for its whole block; a number's mean is ``favg``,
    summed with compensation, and its finite values are counted for the
    shape the second pass gives (`_moments`). Values are left out by
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
        finite = _finite(name)
        return [
            f"favg({finite})",
            f"min({finite})",
            f"max({finite})",
            _counted(f"isfinite({number}) AND {number} = 0"),
            _counted(f"isfinite({number}) AND {number} < 0"),
            _counted(f"isinf({number})"),
            f"count({finite})",
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
        quantile = "quantile_cont" if exact else "approx_quantile"
        found.append(f"{quantile}({_finite(name)}, {_QUARTILES})")
    return found


_POSITIONS: dict[str, list[int | str]] = {
    "boolean": [7],
    "number": [7, 9, 13, 14, 15, 16, "finite"],
    "text": [19, 20],
    "date": [21, 22],
    "other": [],
}
"""Where each of the scan's statistics lands in a row of `_RESULT`, or the
slot it is kept in (``finite``: a number's finite values)."""


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

    A scan reads every column once for its counts, extremes and mean (a
    compensated ``favg``), 20 columns a statement, since DuckDB holds a
    Parquet row group of every column a statement reads on each thread. The
    standard deviation, skewness and kurtosis come from compensated sums
    (``fsum``) of the deviations about that mean, a second pass; where the
    mean overflows (finite values whose sum passes the largest double),
    ``mean`` shows what ``favg`` gave and the three are NULL. Each of the
    three is NULL too where a sum it needs is not finite: the squared
    deviations for all three, the cubed for skewness, the fourth powers for
    kurtosis (as on ``[-1e308, 1e308, 0]``, where pandas gives inf or NaN).
    The exact distinct counts and quartiles keep every value (a hash and a
    sort, held in memory), so they follow in groups of columns, with the
    deviations, a statement each that reads only its group's columns. A
    group holds as many columns as DuckDB's ``memory_limit`` holds at about
    32 bytes a row, from 1 to 20: on 12.5 million rows and the 1,986 MB
    limit of ``sq.set_config(memory="4GB")``, 4. The exact profile reads the
    data once more per group, so each column twice in all. With
    ``exact=False`` the estimates, a small state each, join the scan, and
    the deviations follow in 20-column blocks: each number is read twice,
    any other column once.

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
    except _OutOfMemory as failed:
        raise exploring_out_of_memory(
            failed.exc,
            source.relation.sql_query(),
            "profile",
            estimates=exact,
            columns=[names[k] for k in failed.places],
        ) from failed.exc
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc, source.relation.sql_query(), "profile", estimates=exact
        ) from exc
    return to_output(rel, out if out is not None else get_config().out)


Aggregate = tuple[int, int | str, str]
"""One aggregate of a statement: the column's place, its slot, its SQL."""


class _OutOfMemory(Exception):  # noqa: N818  (carries DuckDB's error out)
    """DuckDB's out-of-memory error, with the places of the columns read."""

    def __init__(self, exc: duckdb.OutOfMemoryException, places: list[int]) -> None:
        super().__init__(str(exc))
        self.exc = exc
        self.places = places


def _gather(
    source: Source,
    names: list[str],
    types: dict[str, DuckDBPyType],
    kinds: dict[str, str],
    exact: bool,
) -> tuple[int, list[dict[int | str, Any]]]:
    """Return the rows and each column's values, by slot.

    A column's slots are ``missing``, its kind's statistics (`_POSITIONS`),
    ``distinct``, and for a number ``quartiles`` and the sums of its
    deviations ``s1`` to ``s4``. The scan, in blocks of
    `_SCAN_COLUMNS` columns, reads all but the exact distinct counts and
    quartiles and the deviations, which need the scan's mean. Exact, those
    follow in groups, a statement each, sized by the rows the scan counted;
    estimated, the deviations follow in blocks of their own.
    """
    absent = [missing_sql(name, types[name]) for name in names]
    scan: list[list[Aggregate]] = []
    held: list[list[Aggregate]] = []
    for k, name in enumerate(names):
        kind = kinds[name]
        cheap: list[Aggregate] = [(k, "missing", _counted(absent[k]))]
        cheap += [
            (k, slot, a)
            for slot, a in zip(
                _POSITIONS[kind], _statistics(kind, name, absent[k]), strict=True
            )
        ]
        estimates: list[Aggregate] = [
            (k, slot, a)
            for slot, a in zip(
                ("distinct", "quartiles"),
                _holistic(kind, name, absent[k], exact),
                strict=False,  # a number has quartiles, nothing else does
            )
        ]
        if exact:
            held.append(estimates)
        else:
            cheap += estimates
            held.append([])
        scan.append(cheap)
    found: list[dict[int | str, Any]] = [{} for _ in names]
    blocks = _blocks(scan, _SCAN_COLUMNS) or [[]]
    rows = _run(source, [(-1, "rows", "count(*)"), *blocks[0]], found)
    for block in blocks[1:]:
        _run(source, block, found)
    for k, name in enumerate(names):
        mean = found[k].get(7) if kinds[name] == "number" else None
        # A mean that overflowed (finite values summing past the largest
        # double) has no deviations to sum: the shape stays NULL.
        if mean is not None and math.isfinite(mean):
            held[k] += [
                (k, slot, a)
                for slot, a in zip(
                    ("s1", "s2", "s3", "s4"), _moments(name, mean), strict=True
                )
            ]
    size = _SCAN_COLUMNS
    if exact:
        limit = duckdb_limit(connection())
        size = max(1, min(_EXACT_COLUMNS, limit // max(1, rows * _VALUE_BYTES)))
    for block in _blocks([h for h in held if h], size):
        _run(source, block, found)
    return rows, found


def _blocks(columns: list[list[Aggregate]], size: int) -> list[list[Aggregate]]:
    """Cut the columns' aggregates into statements of `size` columns each."""
    return [
        [a for aggregates in columns[start : start + size] for a in aggregates]
        for start in range(0, len(columns), size)
    ]


def _run(
    source: Source, statement: list[Aggregate], found: list[dict[int | str, Any]]
) -> int:
    """Run one statement, keep each column's values, return the rows counted."""
    rows = 0
    try:
        fetched = _fetch(source, [aggregate for _, _, aggregate in statement])
    except duckdb.OutOfMemoryException as exc:
        places = sorted({k for k, _, _ in statement if k >= 0})
        raise _OutOfMemory(exc, places) from exc
    for (k, slot, _), value in zip(statement, fetched, strict=True):
        if k < 0:
            rows = int(value)
        else:
            found[k][slot] = value
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
        missing, distinct = held["missing"], held["distinct"]
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
        for slot, value in held.items():
            if isinstance(slot, int):
                row[slot] = value
        if held.get("quartiles") is not None:
            row[10:13] = held["quartiles"]
        if kinds[name] == "number":
            row[8], row[17], row[18] = _shape(
                held["finite"], [held.get(f"s{p}") for p in range(1, 5)]
            )
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
