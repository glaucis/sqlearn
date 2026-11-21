"""`correlations`: pairwise correlations of numeric columns, in tiles of columns."""

import contextlib
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
_TABLE = "__sqlearn_correlations_"
"""The prefix of the temporary tables Spearman writes."""
_ROW = "__sqlearn_rid"
"""The row number Spearman's tables are joined on."""
_METHODS = ("pearson", "spearman")
"""The methods `correlations` knows."""
_BLOCK_COLUMNS = 20
"""How many columns make a block; each statement pairs two blocks, so it
reads at most twice this many columns. Measured in
docs/benchmarks/explore-correlations.md."""
_RESULT = [
    ("column_a", "VARCHAR"),
    ("column_b", "VARCHAR"),
    ("correlation", "DOUBLE"),
    ("rows", "BIGINT"),
]
_ORDER = ["__sqlearn_pa", "__sqlearn_pb"]
"""The positions of a pair's columns, which put the tiles' rows in order."""
_tables = itertools.count()

Pair = tuple[int, int, str, str]
"""A pair: the two columns' positions, then their names."""


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


def _column(k: int) -> str:
    """Return the name the column at position `k` goes by in the queries.

    Naming by position keeps apart columns whose names differ only by case.
    """
    return quote(f"__sqlearn_c{k}")


def _clean(chosen: list[str], places: list[int]) -> str:
    """Write the select list of the columns each pair is computed from.

    Every value is a DOUBLE; NaN and infinity become NULL, so a pair uses
    the rows where both values are present and finite.
    """
    parts = []
    for k in places:
        x = f"CAST({quote(chosen[k])} AS DOUBLE)"
        parts.append(f"CASE WHEN isfinite({x}) THEN {x} END AS {_column(k)}")
    return ", ".join(parts)


def _rank(column: str, missing: str | None = None) -> str:
    """Write the average rank of a cleaned column, named as the column is.

    `rank()` is one more than the rows below the value and `count(*)` over
    the same window (its frame ends at the last tie) is the rows at or
    below it, so their mean is the mean of the ties' ranks: one sort per
    column. With `missing`, the rows where it is true are left out (NULL)
    and the rest ranked among themselves; without, the column has no
    missing value.
    """
    if missing is None:
        window = f"(ORDER BY {column})"
    else:
        window = f"(PARTITION BY {missing} ORDER BY {column})"
    rank = f"CAST(rank() OVER {window} + count(*) OVER {window} AS DOUBLE) / 2"
    if missing is None:
        return f"{rank} AS {column}"
    return f"CASE WHEN NOT ({missing}) THEN {rank} END AS {column}"


def _new_table(made: list[str]) -> str:
    """Name a new temporary table, listed in `made` before it is written."""
    name = f"{_TABLE}{next(_tables)}"
    made.append(name)
    return quote(name)


def _number(source: Source, chosen: list[str], made: list[str]) -> str:
    """Copy the cleaned columns, numbered, into a table: the one scan."""
    table = _new_table(made)
    clean = _clean(chosen, list(range(len(chosen))))
    source.relation.query(
        _VIEW,
        f"CREATE TEMP TABLE {table} AS SELECT row_number() OVER () AS "
        f"{quote(_ROW)}, {clean} FROM {quote(_VIEW)}",
    )
    return table


def _complete(numbered: str, count: int) -> set[int]:
    """Return the positions of the columns with no missing value."""
    found = set()
    for start in range(0, count, _BLOCK_COLUMNS):
        block = range(start, min(start + _BLOCK_COLUMNS, count))
        counts = ", ".join(f"count({_column(k)})" for k in block)
        sql = f"SELECT count(*), {counts} FROM {numbered}"
        ((total, *present),) = connection().execute(sql).fetchall()
        found.update(k for k, n in zip(block, present, strict=True) if n == total)
    return found


def _rank_block(numbered: str, places: list[int], made: list[str]) -> str:
    """Rank each complete column of a block once, into one table by row.

    Each column is ranked from the row number and its own values only, so a
    sort holds two columns whatever the width; the ranks are then joined on
    the row number.
    """
    con = connection()
    singles = []
    for k in places:
        single = _new_table(made)
        con.execute(
            f"CREATE TEMP TABLE {single} AS SELECT {quote(_ROW)}, "
            f"{_rank(_column(k))} FROM (SELECT {quote(_ROW)}, {_column(k)} "
            f"FROM {numbered})"
        )
        singles.append(single)
    block = _new_table(made)
    joins = "".join(f" JOIN {s} USING ({quote(_ROW)})" for s in singles[1:])
    con.execute(f"CREATE TEMP TABLE {block} AS SELECT * FROM {singles[0]}{joins}")
    for single in singles:
        con.execute(f"DROP TABLE {single}")
    return block


def _pairs_query(pairs: list[Pair], values: str) -> str:
    """Write one statement that reads `values` once for a tile of pairs.

    `values` is a table or subquery holding the pairs' columns, each named
    by `_column` from its position.
    """
    items = ", ".join(
        f"{{'p': {i}, 'q': {j}, 'a': {literal(a)}, 'b': {literal(b)}, "
        f"'r': corr({_column(i)}, {_column(j)}), "
        f"'n': regr_count({_column(i)}, {_column(j)})}}"
        for i, j, a, b in pairs
    )
    return (
        f"SELECT CAST(t.p AS INTEGER) AS {quote(_ORDER[0])}, "
        f"CAST(t.q AS INTEGER) AS {quote(_ORDER[1])}, "
        f"CAST(t.a AS VARCHAR) AS {quote('column_a')}, "
        f"CAST(t.b AS VARCHAR) AS {quote('column_b')}, "
        f"CAST(CASE WHEN t.n < 2 OR isnan(t.r) THEN NULL ELSE t.r END AS DOUBLE) "
        f"AS {quote('correlation')}, CAST(t.n AS BIGINT) AS {quote('rows')} "
        f"FROM (SELECT unnest([{items}], recursive := true) FROM {values}) AS t"
    )


def _ranked_statements(
    pairs: list[Pair], complete: set[int], ranks: str | None, numbered: str
) -> list[tuple[list[Pair], str]]:
    """Cut a Spearman tile into statements: their pairs and what they read.

    The pairs of two complete columns read `ranks`, the tile's blocks of
    ranks. A pair touching a column with missing values is ranked over its
    own complete rows from the numbered copy, in a statement of its own
    that reads only its two columns.
    """
    whole = [pair for pair in pairs if {pair[0], pair[1]} <= complete]
    statements = []
    if whole:
        assert ranks is not None  # both blocks hold a complete column
        statements.append((whole, ranks))
    for pair in pairs:
        if not {pair[0], pair[1]} <= complete:
            a, b = _column(pair[0]), _column(pair[1])
            missing = f"{a} IS NULL OR {b} IS NULL"
            both = f"{_rank(a, missing)}, {_rank(b, missing)}"
            statements.append(([pair], f"(SELECT {both} FROM {numbered})"))
    return statements


def _run(sql: str, table: str, source: Source | None = None) -> None:
    """Run one statement and append its rows to `table`.

    With `source`, the statement reads the data as `_VIEW`; without, it reads
    sqlearn's own tables.
    """
    if source is None:
        found = connection().sql(sql)
    else:
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

    Spearman reads the data once, into a temporary copy of the chosen
    columns, cleaned and numbered by row, on sqlearn's connection: as large
    as those columns, it goes to disk when it does not fit DuckDB's memory
    limit, and it is dropped at the end, whether the call succeeds or
    fails. Each column with no missing value is then ranked once, a sort of
    its rows that holds only it and the row number, and the ranks of two
    blocks, joined on the row number, are correlated as Pearson's are. A
    pair touching a column with missing values is ranked again over that
    pair's complete rows, from the copy, in a statement of its own that
    reads only its two columns: two sorts per pair, so each sparse column
    costs two sorts for every other column chosen.

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
    blocks = [
        list(range(start, min(start + _BLOCK_COLUMNS, count)))
        for start in range(0, count, _BLOCK_COLUMNS)
    ]
    head = [(_ORDER[0], "INTEGER"), (_ORDER[1], "INTEGER"), *_RESULT]
    casts = ", ".join(f"CAST(NULL AS {kind}) AS {quote(label)}" for label, kind in head)
    made = [answer(f"SELECT {casts} WHERE false").alias]
    staging = quote(made[0])
    numbered = ""
    complete: set[int] = set()
    ranked: list[str | None] = []
    try:
        if method == "spearman" and count > 1:
            numbered = _number(source, chosen, made)
            complete = _complete(numbered, count)
            for block in blocks:
                places = [k for k in block if k in complete]
                ranked.append(_rank_block(numbered, places, made) if places else None)
        for i, first in enumerate(blocks):
            for j in range(i, len(blocks)):
                second = blocks[j]
                if j == i:
                    tile = list(itertools.combinations(first, 2))
                else:
                    tile = list(itertools.product(first, second))
                if not tile:
                    continue
                pairs = [(p, q, chosen[p], chosen[q]) for p, q in tile]
                if method == "pearson":
                    used = sorted({k for pair in tile for k in pair})
                    values = f"(SELECT {_clean(chosen, used)} FROM {quote(_VIEW)})"
                    _run(_pairs_query(pairs, values), staging, source)
                    continue
                ranks = ranked[i]
                if j != i and ranks is not None and ranked[j] is not None:
                    ranks = f"{ranks} JOIN {ranked[j]} USING ({quote(_ROW)})"
                for some, values in _ranked_statements(
                    pairs, complete, ranks, numbered
                ):
                    _run(_pairs_query(some, values), staging)
        labels = ", ".join(quote(label) for label, _ in _RESULT)
        order = ", ".join(quote(label) for label in _ORDER)
        rel = answer(f"SELECT {labels} FROM {staging} ORDER BY {order}")
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc,
            source.relation.sql_query(),
            "correlations",
            sorts=method == "spearman",
        ) from exc
    finally:
        for name in made:
            with contextlib.suppress(duckdb.Error):
                connection().execute(f"DROP TABLE IF EXISTS {quote(name)}")
    return to_output(rel, out if out is not None else get_config().out)
