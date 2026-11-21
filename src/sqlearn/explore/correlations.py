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
_METHODS = ("pearson",)
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


def _method(method: object) -> str:
    """Return the method, which must be one of `_METHODS`."""
    if method not in _METHODS:
        listed = " or ".join(repr(m) for m in _METHODS)
        raise SqlearnError(
            f"`correlations` was given method={method!r}, which it does not "
            f"know. Why: each method is a way to rank or weigh the values, "
            f"and only the listed ones are written and checked against "
            f"pandas. Fix: pass method={listed}."
        )
    return str(method)


def _clean(method: str, names: list[str]) -> str:
    """Write the select list of the columns each pair is computed from.

    Every value is a DOUBLE; NaN and infinity become NULL, so a pair uses
    the rows where both values are present and finite. This is where a
    method that transforms the values (ranks) goes.
    """
    del method  # only "pearson" so far: the values themselves
    parts = []
    for name in names:
        x = f"CAST({quote(name)} AS DOUBLE)"
        parts.append(f"CASE WHEN isfinite({x}) THEN {x} END AS {quote(name)}")
    return ", ".join(parts)


def _pairs_query(pairs: list[tuple[int, int, str, str]], select: str) -> str:
    """Write one statement that scans the data once for a tile of pairs."""
    items = ", ".join(
        f"{{'p': {i}, 'q': {j}, 'a': {literal(a)}, 'b': {literal(b)}, "
        f"'r': corr({quote(a)}, {quote(b)}), "
        f"'n': regr_count({quote(a)}, {quote(b)})}}"
        for i, j, a, b in pairs
    )
    return (
        f"WITH {quote(_CLEAN)} AS (SELECT {select} FROM {quote(_VIEW)}) "
        f"SELECT CAST(t.p AS INTEGER) AS {quote(_ORDER[0])}, "
        f"CAST(t.q AS INTEGER) AS {quote(_ORDER[1])}, "
        f"CAST(t.a AS VARCHAR) AS {quote('column_a')}, "
        f"CAST(t.b AS VARCHAR) AS {quote('column_b')}, "
        f"CAST(CASE WHEN t.n < 2 OR isnan(t.r) THEN NULL ELSE t.r END AS DOUBLE) "
        f"AS {quote('correlation')}, CAST(t.n AS BIGINT) AS {quote('rows')} "
        f"FROM (SELECT unnest([{items}], recursive := true) "
        f"FROM {quote(_CLEAN)}) AS t"
    )


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
    method : {"pearson"}, default "pearson"
        How to correlate. Pearson is DuckDB's ``corr``.
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
    staging = answer(f"SELECT {casts} WHERE false")
    try:
        for i, first in enumerate(blocks):
            for second in blocks[i:]:
                if second is first:
                    tile = list(itertools.combinations(first, 2))
                else:
                    tile = list(itertools.product(first, second))
                if not tile:
                    continue
                used = sorted({k for pair in tile for k in pair})
                select = _clean(method, [chosen[k] for k in used])
                pairs = [(p, q, chosen[p], chosen[q]) for p, q in tile]
                _run(source, _pairs_query(pairs, select), staging.alias)
    except duckdb.OutOfMemoryException as exc:
        raise exploring_out_of_memory(
            exc, source.relation.sql_query(), "correlations"
        ) from exc
    labels = ", ".join(quote(label) for label, _ in _RESULT)
    order = ", ".join(quote(label) for label in _ORDER)
    rel = answer(f"SELECT {labels} FROM {quote(staging.alias)} ORDER BY {order}")
    connection().execute(f"DROP TABLE {quote(staging.alias)}")
    return to_output(rel, out if out is not None else get_config().out)
