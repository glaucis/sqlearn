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

from collections.abc import Callable

from sqlearn._config import connection

DATABASE = "meta_sqlearn"
"""The in-memory database that holds the ticket tables."""
ROW_GROUP = 122_880
"""The rows DuckDB scans as one part of a stored table."""
MIN_GROUPS = 8
"""The fewest row groups of tickets in a table."""
FAN_OUT = 4_096
"""The most children one ticket widens into per step, so no list is large."""


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
        None when not `parallel`: the caller reads ``range(rows)``. Otherwise
        a query as for `ticket_rows`, over a ticket table in ``meta_sqlearn``
        on sqlearn's connection, made if need be.
    """
    if not parallel:
        return None
    tickets = 8 * ROW_GROUP
    table = f"{DATABASE}.tickets_8"
    # A cursor has its own transaction, so the user's is neither joined nor
    # ended, and it may attach a database even when the user's is read-only.
    cursor = connection().cursor()
    try:
        cursor.execute(f"ATTACH IF NOT EXISTS ':memory:' AS {DATABASE} (READ_WRITE)")
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {table} AS "
            f"SELECT range AS ticket FROM range({tickets}) ORDER BY range"
        )
    finally:
        cursor.close()
    return ticket_rows(rows, table, tickets)


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
