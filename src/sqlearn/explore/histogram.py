"""`histogram`: equal-width bins of numeric columns, as numpy makes them."""

import itertools
import math
from typing import Any

import duckdb

from sqlearn._config import get_config
from sqlearn._diagnose import exploring_out_of_memory
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import Source, read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector, _is_numeric
from sqlearn.explore._common import answer, columns, literal

__all__ = ["histogram"]

_VIEW = "__sqlearn_histogram_source"
"""The name the data goes by inside the statements."""
_BLOCK_COLUMNS = 20
"""How many columns a statement reads.

DuckDB reads a Parquet file a row group at a time on each thread, holding
every column the statement reads (issue #68), as `profile`'s scan does."""
_RESULT = [
    ("column", "VARCHAR"),
    ("bin", "INTEGER"),
    ("low", "DOUBLE"),
    ("high", "DOUBLE"),
    ("count", "BIGINT"),
]

Shape = tuple[str, list[float]]
"""A column's bins: its name and its edges, one more than its bins."""


def _bins(value: object) -> int:
    """Return the number of bins, which must be a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SqlearnError(
            f"`histogram` was given bins={value!r}, which is not a positive "
            f"integer. Why: it counts the bins, so it is a whole number from "
            f"1. Fix: pass an integer such as bins=10."
        )
    return value


def _fetch(source: Source, sql: str) -> list[tuple[Any, ...]]:
    """Run one statement over the data, as `_VIEW`, and return its rows."""
    found = source.relation.query(_VIEW, sql)
    assert found is not None  # a SELECT always has a result
    return found.fetchall()


def _number(name: str) -> str:
    """Return a column as a double."""
    return f"CAST({quote(name)} AS DOUBLE)"


def _double(value: float) -> str:
    """Write a double as SQL: a bare decimal would be read as DECIMAL."""
    return f"CAST({literal(float(value))} AS DOUBLE)"


def _edges(low: float, high: float, bins: int) -> list[float]:
    """Return the edges of a column's bins, as numpy makes them.

    `bins` equal widths from `low` to `high`, the last edge `high` itself.
    Where those edges are not finite and increasing (a width that overflows
    past the largest double, or one too small to move from one edge to the
    next), and where the column has one distinct value, one bin from `low`
    to `high` instead.
    """
    if low < high:
        width = (high - low) / bins
        edges = [low + k * width for k in range(bins)] + [high]
        if all(math.isfinite(e) for e in edges) and all(
            a < b for a, b in itertools.pairwise(edges)
        ):
            return edges
    return [low, high]


def _bin_of(name: str, low: float, width: float, bins: int) -> str:
    """Write the SQL for the bin a value falls in, as numpy puts it.

    The first guess is `floor((x - low) / width)`; it is moved by one where
    the value lies on the other side of the edge that `low + k * width`
    gives, which is the edge numpy compares with.
    """
    x = _number(name)
    start = _double(low)
    step = _double(width)
    k = f"least(CAST(floor(({x} - {start}) / {step}) AS INTEGER), {bins - 1})"
    return (
        f"(SELECT CASE WHEN {x} < {start} + g.k * {step} THEN g.k - 1 "
        f"WHEN g.k < {bins - 1} AND {x} >= {start} + (g.k + 1) * {step} "
        f"THEN g.k + 1 ELSE g.k END FROM (SELECT {k} AS k) AS g)"
    )


def _extremes(source: Source, block: list[str]) -> list[tuple[str, float, float]]:
    """Return each column's finite minimum and maximum, in one statement.

    Values are left out by ``CASE``, never by ``FILTER``, as in `profile`:
    DuckDB gives each filtered aggregate its own copy of the statement's
    inputs.
    """
    aggregates = []
    for name in block:
        x = _number(name)
        finite = f"CASE WHEN isfinite({x}) THEN {x} END"
        aggregates += [f"min({finite})", f"max({finite})"]
    (row,) = _fetch(source, f"SELECT {', '.join(aggregates)} FROM {quote(_VIEW)}")
    return [
        (name, float(row[2 * i]), float(row[2 * i + 1]))
        for i, name in enumerate(block)
        if row[2 * i] is not None
    ]


def _counts(source: Source, shapes: list[Shape]) -> dict[tuple[str, int], int]:
    """Count each column's values by bin, in one statement over the block."""
    queries = []
    for name, edges in shapes:
        n = len(edges) - 1
        x = _number(name)
        width = (edges[-1] - edges[0]) / n
        index = "0" if n == 1 else _bin_of(name, edges[0], width, n)
        queries.append(
            f"SELECT {literal(name)} AS c, {index} AS b, count(*) AS n "
            f"FROM {quote(_VIEW)} WHERE isfinite({x}) GROUP BY ALL"
        )
    rows = _fetch(source, " UNION ALL ".join(queries))
    return {(c, b): n for c, b, n in rows}


def histogram(
    data: object,
    cols: Selector | str | list[str] | None = None,
    *,
    bins: int = 10,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401
    """Count the values of each numeric column in equal-width bins.

    The bins are those of ``numpy.histogram(values, bins)``: equal widths
    between the column's minimum and maximum, the last bin including its
    upper edge. Missing (NULL or NaN) and infinite values are left out. The
    extremes are read 20 columns a statement, and then the counts, since
    DuckDB holds a Parquet row group of every column a statement reads on
    each thread.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to bin; by default every numeric column (a boolean is
        not numeric). A name must be a numeric column.
    bins : int, default 10
        The number of bins, at least 1.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        One row per column and bin: ``column``, ``bin`` (from 0), ``low``,
        ``high`` and ``count``. A column with one distinct finite value has
        one bin with ``low`` equal to ``high``; a column with no finite
        value has none. A column whose range cannot be cut into `bins`
        finite, increasing edges (a width past the largest double, as from
        -1e308 to 1e308, or too small to move one edge from the next), which
        numpy refuses, has one bin from its minimum to its maximum holding
        all its finite values. The result is computed now and kept, so it
        outlives `data`.

    Raises
    ------
    SqlearnError
        If `bins` is not a positive integer, a column in `cols` is not
        numeric or not a column, or DuckDB runs out of memory (the message
        names the fixes).

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> frame = pd.DataFrame({"x": [0, 1, 2, 10]})
    >>> sq.explore.histogram(frame, bins=2, out="pandas")
      column  bin  low  high  count
    0      x    0  0.0   5.0      3
    1      x    1  5.0  10.0      1
    """
    bins = _bins(bins)
    source = read(data)
    types = dict(source.schema)
    chosen = columns(source, cols, function="histogram")
    if cols is None:
        chosen = [n for n in chosen if _is_numeric(types[n])]
    for name in chosen:
        if not _is_numeric(types[name]):
            raise SqlearnError(
                f"`histogram` was given column {name!r} of type "
                f"{types[name]}, which is not numeric. Why: equal-width bins "
                f"need numbers to measure widths. Fix: pass numeric columns, "
                f"or leave cols= out to take them all."
            )
    blocks = [
        chosen[start : start + _BLOCK_COLUMNS]
        for start in range(0, len(chosen), _BLOCK_COLUMNS)
    ]
    reading: list[str] = []
    try:
        shapes: list[Shape] = []
        for block in blocks:
            reading = block
            shapes += [
                (name, _edges(low, high, bins))
                for name, low, high in _extremes(source, block)
            ]
        tally: dict[tuple[str, int], int] = {}
        for start in range(0, len(shapes), _BLOCK_COLUMNS):
            some = shapes[start : start + _BLOCK_COLUMNS]
            reading = [name for name, _ in some]
            tally.update(_counts(source, some))
        reading = []
        rel = answer(_result(shapes, tally))
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc, source.relation.sql_query(), "histogram", columns=reading
        ) from exc
    return to_output(rel, out if out is not None else get_config().out)


def _result(shapes: list[Shape], tally: dict[tuple[str, int], int]) -> str:
    """Write the query of the result's rows, one per column and bin."""
    values = [
        f"({literal(name)}, {k}, {_double(edges[k])}, "
        f"{_double(edges[k + 1])}, {tally.get((name, k), 0)})"
        for name, edges in shapes
        for k in range(len(edges) - 1)
    ]
    labels = ["c", "b", "l", "h", "n"]
    if values:
        body = f"(VALUES {', '.join(values)}) AS v({', '.join(labels)})"
    else:
        nulls = ", ".join("NULL" for _ in labels)
        body = f"(SELECT {nulls} WHERE false) AS v({', '.join(labels)})"
    select = ", ".join(
        f"CAST(v.{a} AS {kind}) AS {quote(label)}"
        for a, (label, kind) in zip(labels, _RESULT, strict=True)
    )
    return f"SELECT {select} FROM {body}"
