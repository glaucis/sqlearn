"""`correlations`: pairwise correlations of numeric columns, in tiles of columns."""

import itertools
from typing import Any

import duckdb

from sqlearn._config import connection, get_config
from sqlearn._diagnose import exploring_out_of_memory
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import Source, read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector, _is_numeric
from sqlearn.explore._common import answer, columns, literal

__all__ = ["correlations"]

_VIEW = "__sqlearn_correlations_source"
"""The name the data goes by inside the pair queries."""
_CLEAN = "__sqlearn_correlations_clean"
"""The name the cleaned columns go by inside the pair queries."""
_RANKED = "__sqlearn_correlations_ranked"
"""The name the ranked columns go by inside the Spearman queries."""
_METHODS = ("pearson", "spearman")
"""The methods `correlations` knows."""
_BLOCK_COLUMNS = 20
"""How many columns make a block; each statement pairs two blocks, so it
reads at most twice this many columns. Measured in
docs/benchmarks/explore-correlations.md."""
_RANKED_BLOCK_COLUMNS = 5
"""The block for Spearman. DuckDB carries every column a statement reads
through each rank's sort, so a tile's time and memory grow faster than its
columns: measured in docs/benchmarks/explore-correlations.md."""
_RESULT = [
    ("column_a", "VARCHAR"),
    ("column_b", "VARCHAR"),
    ("correlation", "DOUBLE"),
    ("rows", "BIGINT"),
]
_ORDER = ["__sqlearn_pa", "__sqlearn_pb"]
"""The positions of a pair's columns, which put the tiles' rows in order."""


def _method(method: object) -> str:
    """Return the method, which must be one of `_METHODS`."""
    if method not in _METHODS:
        listed = " or ".join(f"method={m!r}" for m in _METHODS)
        raise SqlearnError(
            f"`correlations` was given method={method!r}, which it does not "
            f"know. Why: each method is a way to rank or weigh the values, "
            f"and only the listed ones are written and checked against "
            f"pandas. Fix: pass {listed}."
        )
    return str(method)


def _clean(names: list[str]) -> str:
    """Write the select list of the columns each pair is computed from.

    Every value is a DOUBLE; NaN and infinity become NULL, so a pair uses
    the rows where both values are present and finite.
    """
    parts = []
    for name in names:
        x = f"CAST({quote(name)} AS DOUBLE)"
        parts.append(f"CASE WHEN isfinite({x}) THEN {x} END AS {quote(name)}")
    return ", ".join(parts)


def _rank(name: str, missing: str | None = None) -> str:
    """Write the average rank of a cleaned column.

    `rank()` is one more than the rows below the value and `count(*)` over
    the same window (its frame ends at the last tie) is the rows at or
    below it, so their mean is the mean of the ties' ranks: one sort per
    column. With `missing`, the rows where it is true are left out (NULL)
    and the rest ranked among themselves; without, the column has no
    missing value.
    """
    column = quote(name)
    if missing is None:
        window = f"(ORDER BY {column})"
    else:
        window = f"(PARTITION BY {missing} ORDER BY {column})"
    rank = f"CAST(rank() OVER {window} + count(*) OVER {window} AS DOUBLE) / 2"
    if missing is None:
        return f"{rank} AS {column}"
    return f"CASE WHEN NOT ({missing}) THEN {rank} END AS {column}"


def _complete(source: Source, names: list[str]) -> set[str]:
    """Return the columns with no missing value, counting a block at a time."""
    found = set()
    for start in range(0, len(names), _BLOCK_COLUMNS):
        block = names[start : start + _BLOCK_COLUMNS]
        counts = ", ".join(f"count({quote(name)})" for name in block)
        sql = (
            f"SELECT count(*), {counts} FROM "
            f"(SELECT {_clean(block)} FROM {quote(_VIEW)})"
        )
        rel = source.relation.query(_VIEW, sql)
        assert rel is not None  # a SELECT always has a result
        ((total, *present),) = rel.fetchall()
        found.update(n for n, k in zip(block, present, strict=True) if k == total)
    return found


def _pairs_query(
    pairs: list[tuple[int, int, str, str]], select: str, ranks: str | None = None
) -> str:
    """Write one statement that scans the data once for a tile of pairs.

    `select` is the cleaned columns' select list; `ranks`, when given, the
    select list over them that the pairs are correlated on instead.
    """
    items = ", ".join(
        f"{{'p': {i}, 'q': {j}, 'a': {literal(a)}, 'b': {literal(b)}, "
        f"'r': corr({quote(a)}, {quote(b)}), "
        f"'n': regr_count({quote(a)}, {quote(b)})}}"
        for i, j, a, b in pairs
    )
    tables = f"WITH {quote(_CLEAN)} AS (SELECT {select} FROM {quote(_VIEW)})"
    values = _CLEAN
    if ranks is not None:
        tables += f", {quote(_RANKED)} AS (SELECT {ranks} FROM {quote(_CLEAN)})"
        values = _RANKED
    return (
        f"{tables} "
        f"SELECT CAST(t.p AS INTEGER) AS {quote(_ORDER[0])}, "
        f"CAST(t.q AS INTEGER) AS {quote(_ORDER[1])}, "
        f"CAST(t.a AS VARCHAR) AS {quote('column_a')}, "
        f"CAST(t.b AS VARCHAR) AS {quote('column_b')}, "
        f"CAST(CASE WHEN t.n < 2 OR isnan(t.r) THEN NULL ELSE t.r END AS DOUBLE) "
        f"AS {quote('correlation')}, CAST(t.n AS BIGINT) AS {quote('rows')} "
        f"FROM (SELECT unnest([{items}], recursive := true) "
        f"FROM {quote(values)}) AS t"
    )


def _statements(
    method: str, chosen: list[str], tile: list[tuple[int, int]], complete: set[str]
) -> list[tuple[list[tuple[int, int, str, str]], list[str], str | None]]:
    """Cut a tile into statements: its pairs, the columns read, their ranks.

    Pearson is one statement. Spearman ranks each column with no missing
    value once and correlates their pairs in one statement; a pair touching
    a column with missing values is ranked over its own complete rows, in a
    statement of its own.
    """

    def names(pairs: list[tuple[int, int, str, str]]) -> list[str]:
        return [chosen[k] for k in sorted({k for p, q, _, _ in pairs for k in (p, q)})]

    named = [(p, q, chosen[p], chosen[q]) for p, q in tile]
    if method == "pearson":
        return [(named, names(named), None)]
    whole = [pair for pair in named if {pair[2], pair[3]} <= complete]
    sparse = [pair for pair in named if not {pair[2], pair[3]} <= complete]
    statements = []
    if whole:
        read = names(whole)
        statements.append((whole, read, ", ".join(_rank(n) for n in read)))
    for pair in sparse:
        a, b = pair[2], pair[3]
        missing = f"{quote(a)} IS NULL OR {quote(b)} IS NULL"
        statements.append(([pair], [a, b], f"{_rank(a, missing)}, {_rank(b, missing)}"))
    return statements


def _run(source: Source, sql: str, table: str) -> None:
    """Run one tile's statement over the data and append its rows to `table`."""
    found = source.relation.query(_VIEW, sql)
    assert found is not None  # a SELECT always has a result
    found.insert_into(table)


def correlations(
    data: object,
    cols: Selector | str | list[str] | None = None,
    *,
    method: str = "pearson",
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401
    """Correlate every pair of numeric columns.

    Each pair uses the rows where both values are present, as pandas'
    ``DataFrame.corr`` does, so one sparse column does not empty the rest.
    NaN and infinity count as missing. The columns are cut into blocks and
    each statement pairs two blocks, reading only those columns, so that a
    hundred columns or more neither become one statement too large to run
    nor read every column at once.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to correlate; by default every numeric column (a boolean
        is not numeric). A name must be a numeric column. Integer and
        DECIMAL columns are read as DOUBLE.
    method : {"pearson", "spearman"}, default "pearson"
        How to correlate. Pearson is DuckDB's ``corr``. Spearman is Pearson
        on average ranks (ties share the mean of their ranks), each pair
        ranked over its own complete rows, as pandas'
        ``DataFrame.corr(method="spearman")``.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        One row per unordered pair, the first column before the second in
        the data's column order: ``column_a``, ``column_b``,
        ``correlation`` and ``rows``, the count of rows where both values
        are present and finite. ``correlation`` is NULL (pandas gives NaN)
        where the pair has fewer than two such rows or either column has no
        variance over them. Fewer than two columns give no rows; two or
        more columns with no rows give their pairs with a NULL correlation
        and ``rows`` 0. The result is computed now and kept, so it outlives
        `data`.

    Raises
    ------
    SqlearnError
        If `method` is not known, a column in `cols` is not numeric or not a
        column, or DuckDB runs out of memory (the message names the fixes).

    Notes
    -----
    A statement reads two blocks of columns, so memory follows the block, not
    the width of the data. A Parquet file with large row groups still holds a
    whole row group of the columns read on each thread: when that exceeds
    DuckDB's memory limit the call is refused with a ``Fix:`` (fewer
    ``cols=``, more memory with ``sq.set_config(memory=...)``, fewer threads,
    or the file rewritten with smaller row groups).

    Spearman first counts each column's missing values, a block at a time.
    Its blocks are a quarter as wide, since DuckDB carries every column
    read through each rank's sort. A column with none is ranked in each
    statement that reads it, one sort of the rows, and its pairs with other
    such columns share that statement. A pair touching a column with
    missing values is ranked again over that pair's complete rows, in a
    statement of its own that reads only its two columns: two sorts per
    pair, so each sparse column costs two sorts for every other column
    chosen. A sort holds the rows it ranks, so Spearman's memory follows
    the rows as well as the block.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> frame = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 4.0, 6.0]})
    >>> sq.explore.correlations(frame, out="pandas")
      column_a column_b  correlation  rows
    0        a        b          1.0     3
    """
    method = _method(method)
    source = read(data)
    types = dict(source.schema)
    chosen = columns(source, cols, function="correlations")
    if cols is None:
        chosen = [n for n in chosen if _is_numeric(types[n])]
    for name in chosen:
        if not _is_numeric(types[name]):
            raise SqlearnError(
                f"`correlations` was given column {name!r} of type "
                f"{types[name]}, which is not numeric. Why: a correlation "
                f"needs numbers to measure. Fix: pass numeric columns, or "
                f"leave cols= out to take them all."
            )
    count = len(chosen)
    size = _BLOCK_COLUMNS if method == "pearson" else _RANKED_BLOCK_COLUMNS
    blocks = [
        list(range(start, min(start + size, count))) for start in range(0, count, size)
    ]
    head = [(_ORDER[0], "INTEGER"), (_ORDER[1], "INTEGER"), *_RESULT]
    casts = ", ".join(f"CAST(NULL AS {kind}) AS {quote(label)}" for label, kind in head)
    staging = answer(f"SELECT {casts} WHERE false")
    try:
        complete = _complete(source, chosen) if method == "spearman" else set()
        for i, first in enumerate(blocks):
            for second in blocks[i:]:
                if second is first:
                    tile = list(itertools.combinations(first, 2))
                else:
                    tile = list(itertools.product(first, second))
                if not tile:
                    continue
                for pairs, names, ranks in _statements(method, chosen, tile, complete):
                    sql = _pairs_query(pairs, _clean(names), ranks)
                    _run(source, sql, staging.alias)
        labels = ", ".join(quote(label) for label, _ in _RESULT)
        order = ", ".join(quote(label) for label in _ORDER)
        rel = answer(f"SELECT {labels} FROM {quote(staging.alias)} ORDER BY {order}")
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc, source.relation.sql_query(), "correlations"
        ) from exc
    finally:
        connection().execute(f"DROP TABLE {quote(staging.alias)}")
    return to_output(rel, out if out is not None else get_config().out)
