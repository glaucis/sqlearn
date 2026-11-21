"""`top`: the commonest values of each column."""

from typing import Any

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import read
from sqlearn._output import Output, to_output
from sqlearn._selectors import Selector
from sqlearn.explore._common import answer, columns, literal, missing_sql

__all__ = ["top"]

_VIEW = "__sqlearn_top_source"
"""The name the data goes by inside the counting query."""
_RESULT = [
    ("column", "VARCHAR"),
    ("value", "VARCHAR"),
    ("count", "BIGINT"),
    ("share", "DOUBLE"),
]


def _k(value: object) -> int:
    """Return the number of values kept per column: a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SqlearnError(
            f"`top` was given k={value!r}, which is not a positive integer. "
            f"Why: it counts the values kept for each column, so it is a "
            f"whole number from 1. Fix: pass an integer such as k=10."
        )
    return value


def top(
    data: object,
    cols: Selector | str | list[str] | None = None,
    *,
    k: int = 10,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401
    """List the commonest values of each column and how often they occur.

    Missing values (NULL, and NaN in a float column) count together as one
    value, shown with a NULL `value`, as pandas' ``value_counts(dropna=False)``
    counts NaN. In a float column -0.0 is counted as 0.0, as pandas does.

    Parameters
    ----------
    data : object
        A path or glob ending in .parquet, .csv or .json, a table name, a
        DuckDB relation, or a pandas DataFrame.
    cols : Selector or str or list of str, optional
        The columns to count; by default every column, of any type.
    k : int, default 10
        How many values to keep for each column, at least 1.
    out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
        What to hand back; by default ``sq.get_config().out``, and when that
        is None a DuckDB relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        Up to `k` rows per column, in the data's column order and from the
        commonest down: ``column``, ``value``, ``count`` and ``share``, the
        count over all the column's rows (missing ones included). `value` is
        the value as DuckDB casts it to text. Values with the same count come
        in order of `value` as text, a NULL last. A column with fewer than `k`
        distinct values has fewer rows; a selector that chooses no column, or
        data with no rows, gives an empty result. The result is computed now
        and kept, so it outlives `data`.

    Raises
    ------
    SqlearnError
        If `k` is not a positive integer, or a name in `cols` is not a
        column.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> frame = pd.DataFrame({"colour": ["red", "red", "blue", "green"]})
    >>> sq.explore.top(frame, k=2, out="pandas")
       column value  count  share
    0  colour   red      2   0.50
    1  colour  blue      1   0.25
    """
    k = _k(k)
    source = read(data)
    types = dict(source.schema)
    chosen = columns(source, cols, function="top")
    queries = []
    for position, name in enumerate(chosen):
        value = quote(name)
        if types[name].id in {"float", "double"}:
            value = (
                f"CASE WHEN {value} = 0 THEN CAST(0 AS {types[name]}) ELSE {value} END"
            )
        shown = (
            f"CASE WHEN {missing_sql(name, types[name])} THEN NULL "
            f"ELSE CAST({value} AS VARCHAR) END"
        )
        queries.append(
            f"SELECT {position} AS p, {literal(name)} AS c, {shown} AS v, "
            f"count(*) AS n FROM {quote(_VIEW)} GROUP BY 3"
        )
    rows = []
    if queries:
        ranked = (
            "SELECT p, c, v, n, n / sum(n) OVER (PARTITION BY p) AS s, "
            "row_number() OVER (PARTITION BY p ORDER BY n DESC, v NULLS LAST) "
            f"AS r FROM ({' UNION ALL '.join(queries)})"
        )
        found = source.relation.query(
            _VIEW,
            f"SELECT c, v, n, s FROM ({ranked}) WHERE r <= {k} ORDER BY p, r",
        )
        rows = found.fetchall() if found is not None else []
    labels = ["c", "v", "n", "s"]
    if rows:
        values = ", ".join(f"({', '.join(literal(x) for x in row)})" for row in rows)
        body = f"(VALUES {values}) AS t({', '.join(labels)})"
    else:
        nulls = ", ".join("NULL" for _ in labels)
        body = f"(SELECT {nulls} WHERE false) AS t({', '.join(labels)})"
    select = ", ".join(
        f"CAST(t.{a} AS {kind}) AS {quote(label)}"
        for a, (label, kind) in zip(labels, _RESULT, strict=True)
    )
    rel = answer(f"SELECT {select} FROM {body}")
    return to_output(rel, out if out is not None else get_config().out)
