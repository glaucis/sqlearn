"""`histogram`: equal-width bins of numeric columns, as numpy makes them."""

from typing import Any

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector, _is_numeric
from sqlearn.explore._common import answer, columns
from sqlearn.explore.profile import _literal

__all__ = ["histogram"]

_VIEW = "__sqlearn_histogram_source"
"""The name the data goes by inside the counting query."""
_RESULT = [
    ("column", "VARCHAR"),
    ("bin", "INTEGER"),
    ("low", "DOUBLE"),
    ("high", "DOUBLE"),
    ("count", "BIGINT"),
]


def _bins(value: object) -> int:
    """Return the number of bins, which must be a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SqlearnError(
            f"`histogram` was given bins={value!r}, which is not a positive "
            f"integer. Why: it counts the bins, so it is a whole number from "
            f"1. Fix: pass an integer such as bins=10."
        )
    return value


def _bin_of(name: str, low: float, width: float, bins: int) -> str:
    """Write the SQL for the bin a value falls in, as numpy puts it.

    The first guess is `floor((x - low) / width)`; it is moved by one where
    the value lies on the other side of the edge that `low + k * width`
    gives, which is the edge numpy compares with.
    """
    x = f"CAST({quote(name)} AS DOUBLE)"
    start = f"{float(low)!r}::DOUBLE"
    step = f"{float(width)!r}::DOUBLE"
    k = f"least(CAST(floor(({x} - {start}) / {step}) AS INTEGER), {bins - 1})"
    return (
        f"(SELECT CASE WHEN {x} < {start} + g.k * {step} THEN g.k - 1 "
        f"WHEN g.k < {bins - 1} AND {x} >= {start} + (g.k + 1) * {step} "
        f"THEN g.k + 1 ELSE g.k END FROM (SELECT {k} AS k) AS g)"
    )


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
    upper edge. Missing (NULL or NaN) and infinite values are left out.

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
        value has none. The result is computed now and kept, so it outlives
        `data`.

    Raises
    ------
    SqlearnError
        If `bins` is not a positive integer, or a column in `cols` is not
        numeric or not a column.

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
    extremes: list[tuple[str, float, float]] = []
    if chosen:
        aggregates = []
        for name in chosen:
            x = f"CAST({quote(name)} AS DOUBLE)"
            finite = f"FILTER (WHERE isfinite({x}))"
            aggregates += [f"min({x}) {finite}", f"max({x}) {finite}"]
        row = source.relation.aggregate(", ".join(aggregates)).fetchall()[0]
        extremes = [
            (name, float(row[2 * i]), float(row[2 * i + 1]))
            for i, name in enumerate(chosen)
            if row[2 * i] is not None
        ]
    queries = []
    shapes = []
    for name, low, high in extremes:
        n = 1 if low == high else bins
        width = (high - low) / n
        shapes.append((name, low, high, n, width))
        x = f"CAST({quote(name)} AS DOUBLE)"
        index = "0" if n == 1 else _bin_of(name, low, width, n)
        queries.append(
            f"SELECT {_literal(name)} AS c, {index} AS b, count(*) AS n "
            f"FROM {quote(_VIEW)} WHERE isfinite({x}) GROUP BY ALL"
        )
    tally: dict[tuple[str, int], int] = {}
    if queries:
        found = source.relation.query(_VIEW, " UNION ALL ".join(queries))
        rows = found.fetchall() if found is not None else []
        tally = {(c, b): n for c, b, n in rows}
    values = []
    for name, low, high, n, width in shapes:
        for k in range(n):
            upper = high if k == n - 1 else low + (k + 1) * width
            first = float(low + k * width)
            values.append(
                f"({_literal(name)}, {k}, {first!r}::DOUBLE, "
                f"{float(upper)!r}::DOUBLE, {tally.get((name, k), 0)})"
            )
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
    rel = answer(f"SELECT {select} FROM {body}")
    return to_output(rel, out if out is not None else get_config().out)
