"""The Gram learn: XᵀX of a step's centred input columns, built in numpy.

A Gram step (`Step.gram`, ADR 0058) learns from the p-by-p matrix XᵀX of its
centred inputs. DuckDB centres the rows and hands them over in batches; numpy
sums each batch's ``xᵀx``. Only this learn brings rows into Python, one batch
at a time; applying stays SQL.
"""

import itertools
from collections.abc import Mapping, Sequence

import duckdb
import numpy as np

from sqlearn._errors import InternalError, SqlearnError
from sqlearn._expr import quote
from sqlearn._feed import MEGABYTES
from sqlearn._memory import _megabytes, allowance, budget

__all__ = ["batch_rows", "check_fits", "gram_matrix"]

_ROW = "__sqlearn_gram_row"
"""The column numbering the centred rows, which batches are cut by."""
_TABLE = "__sqlearn_gram_"
"""The prefix of the temporary tables holding the centred rows."""
_COPIES = 4
"""The copies of the p-by-p matrix a learn may hold: the sum, a batch's
product, and the step's decomposition of it."""
_BATCH_COPIES = 3
"""The copies of one batch a learn holds at its peak: DuckDB's materialised
result, the column arrays ``fetchnumpy`` returns, and their stacked copy."""
_tables = itertools.count()


def batch_rows(columns: int) -> int:
    """Return how many rows each batch of a Gram learn holds.

    About `sqlearn._feed.MEGABYTES` of float64 values, as the streamed
    training batches are sized: ``MEGABYTES * 1_000_000 // (8 * columns)``
    rows, at least one.

    Parameters
    ----------
    columns : int
        The number of columns in a batch.

    Returns
    -------
    int
        The rows per batch.

    Examples
    --------
    >>> from sqlearn._gram import batch_rows
    >>> batch_rows(100)
    125000
    """
    return max(1, MEGABYTES * 1_000_000 // (8 * max(1, columns)))


def check_fits(con: duckdb.DuckDBPyConnection, columns: int) -> None:
    """Refuse a Gram learn whose matrix and batch would not fit in memory.

    It holds 3 copies of one batch (`batch_rows`: DuckDB's result, the
    arrays ``fetchnumpy`` returns, and their stacked copy) and up to 4
    copies of the p-by-p matrix, all float64; together they must fit in
    the allowance (`sqlearn._memory.allowance`).

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection the data is computed in.
    columns : int
        The number of columns, p.

    Raises
    ------
    SqlearnError
        If they would not fit; swapping is never the fallback.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._gram import check_fits
    >>> check_fits(connection(), 3)
    """
    size = 8 * columns * (_COPIES * columns + _BATCH_COPIES * batch_rows(columns))
    room = allowance(con)
    if size <= room:
        return
    msg = (
        f"learning from the Gram matrix of {columns:,} columns needs about "
        f"{_megabytes(size)}, and the memory it may use is "
        f"{_megabytes(max(room, 0))}; it would swap, which sqlearn never does. "
        f"Why: it holds {_COPIES} copies of the {columns:,}-by-{columns:,} "
        f"matrix and {_BATCH_COPIES} copies of one batch of rows, all as "
        "8-byte numbers. Fix: fewer "
        "columns, or a larger budget with sq.set_config(memory=...) (now "
        f"{_megabytes(budget())})."
    )
    raise SqlearnError(msg)


def gram_matrix(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    columns: Sequence[str],
    means: Mapping[str, float],
    *,
    statements: list[str] | None = None,
) -> np.ndarray:
    """Return XᵀX of `columns` of `sql`, each centred on its mean.

    DuckDB casts each column to DOUBLE and subtracts its mean, numbering the
    centred rows into a temporary table (DuckDB spills it to disk when it is
    large). The rows are then fetched by row range, in batches of
    `batch_rows` with ``fetchnumpy``, and each batch's ``bᵀb`` is added in
    order. The table is dropped after, whatever happens. Columns are read
    by position, so two whose names differ only by case stay two.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection holding the data.
    sql : str
        The data reaching the step, as a query.
    columns : sequence of str
        The columns, in order; each must be a column of `sql`, named exactly.
    means : mapping of str to float
        The mean of each column, subtracted from it.
    statements : list of str, optional
        Given a list, the statement numbering the centred rows is appended
        to it (the batch fetches that follow it are not).

    Returns
    -------
    numpy.ndarray
        The p-by-p float64 matrix, rows and columns in the order of `columns`.

    Raises
    ------
    InternalError
        If a value is NULL: the step refuses missing values before any
        batch (`Step.before_gram`).

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._gram import gram_matrix
    >>> sql = "SELECT * FROM (VALUES (1.0), (3.0)) t(a)"
    >>> gram_matrix(connection(), sql, ["a"], {"a": 2.0}).tolist()
    [[2.0]]
    """
    names = con.sql(sql).columns
    places = [names.index(c) for c in columns]
    # Every column of `sql` is renamed by position, so `a` and `A` stay apart.
    aliases = ", ".join(quote(f"__sqlearn_c{k}") for k in range(len(names)))
    centred = ", ".join(
        f"({quote(f'__sqlearn_c{k}')}::DOUBLE - '{float(means[c])!r}'::DOUBLE) "
        f"AS {quote(f'__sqlearn_x{j}')}"
        for j, (k, c) in enumerate(zip(places, columns, strict=True))
    )
    table = quote(f"{_TABLE}{next(_tables)}")
    numbered = (
        f"CREATE TEMP TABLE {table} AS SELECT row_number() OVER () AS "
        f"{quote(_ROW)}, {centred} FROM ({sql}) AS "
        f"{quote('__sqlearn_gram')}({aliases})"
    )
    picks = ", ".join(quote(f"__sqlearn_x{j}") for j in range(len(columns)))
    size = batch_rows(len(columns))
    gram = np.zeros((len(columns), len(columns)))
    try:
        con.execute(numbered)
        if statements is not None:
            statements.append(numbered)
        total = con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
        for start in range(0, total, size):
            batch = con.execute(
                f"SELECT {picks} FROM {table} WHERE {quote(_ROW)} > {start} "
                f"AND {quote(_ROW)} <= {start + size} ORDER BY {quote(_ROW)}"
            ).fetchnumpy()
            parts = [batch[f"__sqlearn_x{j}"] for j in range(len(columns))]
            if any(np.ma.is_masked(part) for part in parts):
                msg = (
                    "a Gram step's input holds a missing value (NULL), which "
                    "XᵀX cannot hold. This is a bug in sqlearn: the step "
                    "refuses missing values before any batch (before_gram). "
                    "Please report it."
                )
                raise InternalError(msg)
            rows = np.column_stack([np.ma.getdata(part) for part in parts])
            gram += rows.T @ rows
    finally:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    return gram
