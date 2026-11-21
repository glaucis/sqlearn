"""`correlations`: pairwise correlations of numeric columns, in chunks of pairs."""

import itertools
from typing import Any

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import read
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
_PAIRS_PER_QUERY = 1000
"""How many pairs one statement computes; measured in
docs/benchmarks/explore-correlations.md."""
_RESULT = [
    ("column_a", "VARCHAR"),
    ("column_b", "VARCHAR"),
    ("correlation", "DOUBLE"),
    ("rows", "BIGINT"),
]


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


def _pairs_query(pairs: list[tuple[str, str]], select: str) -> str:
    """Write one statement that scans the data once for a chunk of pairs."""
    items = ", ".join(
        f"{{'a': {literal(a)}, 'b': {literal(b)}, "
        f"'r': corr({quote(a)}, {quote(b)}), "
        f"'n': regr_count({quote(a)}, {quote(b)})}}"
        for a, b in pairs
    )
    return (
        f"WITH {quote(_CLEAN)} AS (SELECT {select} FROM {quote(_VIEW)}) "
        f"SELECT CAST(t.a AS VARCHAR) AS {quote('column_a')}, "
        f"CAST(t.b AS VARCHAR) AS {quote('column_b')}, "
        f"CAST(CASE WHEN t.n < 2 OR isnan(t.r) THEN NULL ELSE t.r END AS DOUBLE) "
        f"AS {quote('correlation')}, CAST(t.n AS BIGINT) AS {quote('rows')} "
        f"FROM (SELECT unnest([{items}], recursive := true) "
        f"FROM {quote(_CLEAN)}) AS t"
    )


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
    NaN and infinity count as missing. The pairs are computed in statements
    of a fixed number of pairs each, so that a hundred columns or more do
    not become one statement too large to run.

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
        If `method` is not known, or a column in `cols` is not numeric or
        not a column.

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
    casts = ", ".join(
        f"CAST(NULL AS {kind}) AS {quote(label)}" for label, kind in _RESULT
    )
    rel = answer(f"SELECT {casts} WHERE false")
    pairs = list(itertools.combinations(chosen, 2))
    if pairs:
        select = _clean(method, chosen)
        for start in range(0, len(pairs), _PAIRS_PER_QUERY):
            chunk = pairs[start : start + _PAIRS_PER_QUERY]
            found = source.relation.query(_VIEW, _pairs_query(chunk, select))
            if found is not None:
                found.insert_into(rel.alias)
    return to_output(rel, out if out is not None else get_config().out)
