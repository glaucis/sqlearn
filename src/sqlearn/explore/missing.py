"""`missing`: the commonest patterns of missing values across columns."""

from typing import Any

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector
from sqlearn.explore._common import answer, columns, literal, missing_sql

__all__ = ["missing"]

_VIEW = "__sqlearn_missing_source"
"""The name the data goes by inside the counting query."""
_MAX_COLUMNS = 64
_RESULT = [("missing", "VARCHAR[]"), ("count", "BIGINT"), ("share", "DOUBLE")]


def _patterns(value: object) -> int:
    """Return the number of patterns kept: a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SqlearnError(
            f"`missing` was given patterns={value!r}, which is not a "
            f"positive integer. Why: it counts the patterns kept, so it is a "
            f"whole number from 1. Fix: pass an integer such as patterns=10."
        )
    return value


def missing(
    data: object,
    cols: Selector | str | list[str] | None = None,
    *,
    patterns: int = 10,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401
    """List the commonest patterns of missing values across columns.

    A pattern is the set of chosen columns that are missing together in a
    row (NULL, and NaN in a float column). Rows are counted in one pass.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to look at; by default every column, of any type. At
        most 64 columns may be chosen.
    patterns : int, default 10
        How many patterns to keep, at least 1.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        Up to `patterns` rows, the commonest first: ``missing`` (a list of
        the names of the columns missing in the pattern, in the data's column
        order; the pattern with nothing missing is the empty list), ``count``
        and ``share``, the count over all the rows. Patterns with the same
        count are ordered by their columns in the data's order, a pattern
        with a column present before one with it missing. A selector that
        chooses no column, or data with no rows, gives an empty result. The
        result is computed now and kept, so it outlives `data`.

    Raises
    ------
    SqlearnError
        If `patterns` is not a positive integer, a name in `cols` is not a
        column, or more than 64 columns are chosen.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> frame = pd.DataFrame({"a": [1, None, 3, None], "b": [1, 2, None, None]})
    >>> sq.explore.missing(frame, out="pandas")
      missing  count  share
    0      []      1   0.25
    1     [b]      1   0.25
    2     [a]      1   0.25
    3  [a, b]      1   0.25
    """
    keep = _patterns(patterns)
    source = read(data)
    types = dict(source.schema)
    chosen = columns(source, cols, function="missing")
    if len(chosen) > _MAX_COLUMNS:
        raise SqlearnError(
            f"`missing` was asked about {len(chosen)} columns, more than "
            f"{_MAX_COLUMNS}. Why: a pattern is a combination of columns, "
            f"so a wide table has too many patterns to be useful. Fix: "
            f"choose up to {_MAX_COLUMNS} columns with cols=."
        )
    rows = []
    if chosen:
        flags = [
            f"{missing_sql(name, types[name])} AS f{i}" for i, name in enumerate(chosen)
        ]
        keys = ", ".join(f"f{i}" for i in range(len(chosen)))
        counted = (
            f"SELECT {keys}, n, n / sum(n) OVER () AS s FROM ("
            f"SELECT {', '.join(flags)}, count(*) AS n FROM {quote(_VIEW)} "
            f"GROUP BY ALL)"
        )
        found = source.relation.query(
            _VIEW,
            f"{counted} ORDER BY n DESC, {keys} LIMIT {keep}",
        )
        rows = found.fetchall() if found is not None else []
    width = len(chosen)
    listed = [
        (
            [name for name, gone in zip(chosen, row[:width], strict=True) if gone],
            row[width],
            row[width + 1],
        )
        for row in rows
    ]
    labels = ["m", "n", "s"]
    if listed:
        values = ", ".join(
            f"([{', '.join(literal(x) for x in m)}]::VARCHAR[], {n}, {literal(s)})"
            for m, n, s in listed
        )
        body = f"(VALUES {values}) AS t({', '.join(labels)})"
    else:
        body = f"(SELECT NULL, NULL, NULL WHERE false) AS t({', '.join(labels)})"
    select = ", ".join(
        f"CAST(t.{a} AS {kind}) AS {quote(label)}"
        for a, (label, kind) in zip(labels, _RESULT, strict=True)
    )
    rel = answer(f"SELECT {select} FROM {body}")
    return to_output(rel, out if out is not None else get_config().out)
