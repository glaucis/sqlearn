"""Row numbers from work tickets, so that DuckDB can share them between threads.

DuckDB runs ``range`` on one thread, but it shares the scan of a stored table
among threads, a row group of ``ROW_GROUP`` rows at a time. A **work ticket**
is one row of a ticket table: a number that stands for one block of row
numbers. Widening the tickets by ``unnest`` gives the row numbers in order,
and the work on them is spread over the threads (spec
``docs/specs/datasets-many-threads.md``).

Examples
--------
>>> import duckdb
>>> con = duckdb.connect()
>>> _ = con.execute("CREATE TABLE t AS SELECT range AS ticket FROM range(4)")
>>> [r[0] for r in con.sql(ticket_rows(10, "t", 4)).fetchall()]
[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
"""

import re
import threading
import warnings
from collections.abc import Callable
from pathlib import Path

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnWarning

DATABASE = "meta_sqlearn"
"""The in-memory database that holds the ticket tables."""
ROW_GROUP = 122_880
"""The rows DuckDB scans as one part of a stored table."""
MIN_GROUPS = 8
"""The fewest row groups of tickets in a table."""
FAN_OUT = 4_096
"""The most children one ticket widens into per step, so no list is large."""
_LOCK = threading.Lock()
_TABLE = re.compile(r"tickets_([1-9][0-9]*)")
_PACKAGE = (str(Path(__file__).parents[1]),)


class _UnusableError(Exception):
    """Tickets cannot be used on this connection; the message says why."""


def row_source(rows: int, parallel: bool) -> str | None:
    """Return the SQL of the row numbers for a generator, or None for ``range``.

    Parameters
    ----------
    rows : int
        The number of rows, at least 1 and at most ``2**63 - 1``.
    parallel : bool
        Whether to number the rows from work tickets.

    Returns
    -------
    str or None
        None when not `parallel`, or when tickets cannot be used (the database
        ``meta_sqlearn`` is not sqlearn's, DuckDB refused to make a table, or
        the connection sees no ticket table because a transaction began before
        any): the caller reads ``range(rows)``, and a `SqlearnWarning` says
        why.
        Otherwise a query as for `ticket_rows`, over the largest ticket table
        the connection sees in ``meta_sqlearn``, one for the thread count
        made if need be.
    """
    if not parallel:
        return None
    con = connection()
    try:
        _make_table(con)
        tables = _visible_tables(con)
        if not tables:
            # A transaction of the user's that began before any ticket table.
            raise _UnusableError("this connection sees no ticket table")
    except (_UnusableError, duckdb.Error) as error:
        _warn(error)
        return None
    groups = max(tables)
    return ticket_rows(rows, tables[groups], groups * ROW_GROUP)


def _warn(error: Exception) -> None:
    """Warn that generators fall back to one thread, and why."""
    detail = str(error).strip()
    text = (
        f"sqlearn cannot use its work tickets in {DATABASE}: {detail}. "
        "Why: the generators number their rows from tickets in an in-memory "
        f"database named {DATABASE}, so that every thread has work; they now "
        "run on one thread, with the same rows. Fix: detach or rename the "
        f"other database called {DATABASE} (sqlearn never writes to one that "
        "is not its own), or pass parallel=False to silence this warning."
    )
    warnings.warn(text, SqlearnWarning, skip_file_prefixes=_PACKAGE)


def _make_table(con: duckdb.DuckDBPyConnection) -> None:
    """Make sure a ticket table for the current thread count exists.

    A ticket table is never changed, replaced or dropped: a larger one is
    added beside the smaller ones, so a relation built earlier keeps reading
    the table it names. One lock serialises the writers in this process.
    """
    with _LOCK:
        # A cursor has its own transaction, so the user's is neither joined
        # nor ended, and it may attach a database even when the user's is
        # read-only.
        cursor = con.cursor()
        try:
            cursor.execute(
                f"ATTACH IF NOT EXISTS ':memory:' AS {DATABASE} (READ_WRITE)"
            )
            _check_ownership(cursor)
            row = cursor.execute("SELECT current_setting('threads')").fetchone()
            assert row is not None
            wanted = max(MIN_GROUPS, int(row[0]))
            if max(_all_tables(cursor), default=0) < wanted:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {DATABASE}.main.tickets_{wanted} AS "
                    f"SELECT range AS ticket FROM range({wanted * ROW_GROUP}) "
                    "ORDER BY range"
                )
        finally:
            cursor.close()


def _check_ownership(cursor: duckdb.DuckDBPyConnection) -> None:
    """Raise `_UnusableError` unless ``meta_sqlearn`` holds only sqlearn's tickets.

    It is sqlearn's when it is in memory and every table in it is
    ``tickets_<groups>`` with the one ``BIGINT`` column ``ticket``, exactly
    ``groups * ROW_GROUP`` rows, and ``ticket`` equal to ``rowid`` throughout.
    """
    path = cursor.execute(
        f"SELECT path FROM duckdb_databases() WHERE database_name = '{DATABASE}'"
    ).fetchone()
    if path is not None and path[0] is not None:
        raise _UnusableError(f"a database file ({path[0]}) is attached as {DATABASE}")
    tables = cursor.execute(
        "SELECT schema_name, table_name FROM duckdb_tables() "
        f"WHERE database_name = '{DATABASE}'"
    ).fetchall()
    for schema, name in tables:
        match = _TABLE.fullmatch(name)
        if match is None or schema != "main":
            raise _UnusableError(
                f"the table {schema}.{name} in it is not a ticket table"
            )
        columns = cursor.execute(
            "SELECT column_name, data_type FROM duckdb_columns() "
            f"WHERE database_name = '{DATABASE}' AND schema_name = 'main' "
            f"AND table_name = '{name}'"
        ).fetchall()
        if columns != [("ticket", "BIGINT")]:
            raise _UnusableError(f"the table {name} in it has other columns")
        row = cursor.execute(
            f"SELECT count(*), count(*) FILTER (WHERE ticket <> rowid) "
            f"FROM {DATABASE}.main.{name}"
        ).fetchone()
        if row != (int(match[1]) * ROW_GROUP, 0):
            raise _UnusableError(f"the table {name} in it does not hold the tickets")


def _all_tables(con: duckdb.DuckDBPyConnection) -> dict[int, str]:
    """Return the committed ticket tables, as row groups to full table name.

    Only ``meta_sqlearn.main.tickets_<groups>`` counts: a table of the user's
    with another name, schema or database is not a ticket table.
    """
    rows = con.execute(
        "SELECT table_name FROM duckdb_tables() "
        f"WHERE database_name = '{DATABASE}' AND schema_name = 'main'"
    ).fetchall()
    found = {}
    for (name,) in rows:
        match = _TABLE.fullmatch(name)
        if match is not None:
            found[int(match[1])] = f"{DATABASE}.main.{name}"
    return found


def _visible_tables(con: duckdb.DuckDBPyConnection) -> dict[int, str]:
    """Return the ticket tables `con` itself sees, as groups to full name.

    The tables are listed on a cursor, then each is only bound on `con`
    (never executed), so a result the user has begun to read stays whole, and
    a table made after the user's transaction began is left out.
    """
    cursor = con.cursor()
    try:
        candidates = _all_tables(cursor)
    finally:
        cursor.close()
    visible = {}
    for groups, name in candidates.items():
        try:
            con.sql(f"SELECT ticket FROM {name}")
        except duckdb.CatalogException:
            continue
        visible[groups] = name
    return visible


def ticket_rows(rows: int, table: str, tickets: int) -> str:
    """Return the SQL of the row numbers ``0`` to ``rows - 1``, from tickets.

    Parameters
    ----------
    rows : int
        The number of rows, at least 1 and at most ``2**63 - 1``.
    table : str
        A table, qualified if need be, with the column ``ticket`` holding
        ``0`` to ``tickets - 1`` in order.
    tickets : int
        The number of tickets in `table`.

    Returns
    -------
    str
        A query with one ``BIGINT`` column ``range``, in order, equal to
        ``SELECT range FROM range(rows)``.

    Examples
    --------
    >>> import duckdb
    >>> con = duckdb.connect()
    >>> _ = con.execute("CREATE TABLE t AS SELECT range AS ticket FROM range(3)")
    >>> con.sql(ticket_rows(5, "t", 3)).fetchall()
    [(0,), (1,), (2,), (3,), (4,)]
    """
    used = min(tickets, rows)
    size = -(-rows // used)
    scan = (
        f"SELECT ticket::HUGEINT * {size} AS a, {size}::HUGEINT AS w "
        f"FROM {table} WHERE ticket < {used}"
    )
    return _row_numbers(rows, scan, size)


def _row_numbers(
    rows: int,
    scan: str,
    size: int,
    each_list: Callable[[str], str] = str,
) -> str:
    """Widen the blocks of `scan` into row numbers.

    `scan` gives ``a`` and ``w`` (``HUGEINT``): a block's start and width,
    every block at most `size` wide. While a block is wider than ``FAN_OUT``
    it is split into children; the last step lists the row numbers. Starts and
    ends are ``HUGEINT``, clamped to `rows` before the cast to ``BIGINT``,
    because at ``2**63 - 1`` rows the sums overflow it. `each_list` wraps
    every ``range(...)`` list before it is unnested.
    """

    def blocks(step: str) -> str:
        return each_list(
            f"range(least(a, {rows})::BIGINT, least(a + w, {rows})::BIGINT{step})"
        )

    while size > FAN_OUT:
        child = -(-size // FAN_OUT)
        # The last child of a block may be narrower: it ends where the block does.
        scan = (
            f"SELECT s AS a, least({child}::HUGEINT, e - s) AS w FROM ("
            f"SELECT unnest({blocks(f', {child}')})::HUGEINT AS s, a + w AS e "
            f"FROM ({scan}))"
        )
        size = child
    return f"SELECT unnest({blocks('')}) AS range FROM ({scan})"
