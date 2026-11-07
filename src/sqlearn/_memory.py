"""The memory budget: what a hand-over may hold, so a fold never swaps.

One budget for the process (``sq.set_config(memory=...)``, by default 80%
of physical memory) is shared by DuckDB and the data handed to a model.
DuckDB's share is its connection's ``memory_limit``, counted as at most
half the budget; the hand-over may use the rest. A fold whose estimated
size is over that is refused before it is fetched (spec section 3.3,
Ruling R11).
"""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Sequence

import duckdb

from sqlearn._config import get_config
from sqlearn._errors import SqlearnError

__all__ = [
    "allowance",
    "budget",
    "check",
    "duckdb_limit",
    "estimate",
    "parse",
    "physical",
]

# The units DuckDB reads and prints: powers of 1000 and of 1024.
_UNITS = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 10**3,
    "kb": 10**3,
    "m": 10**6,
    "mb": 10**6,
    "g": 10**9,
    "gb": 10**9,
    "t": 10**12,
    "tb": 10**12,
    "pb": 10**15,
    "kib": 2**10,
    "mib": 2**20,
    "gib": 2**30,
    "tib": 2**40,
    "pib": 2**50,
}

_SIZE = re.compile(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*([a-z]*)\s*", re.IGNORECASE)

# Bytes a number holds in every form; a text value holds this plus its length.
_NUMBER = 8
_TEXT = 64


def _split(text: str) -> tuple[float, int]:
    """Return a size string's number and its unit's bytes, or refuse it."""
    found = _SIZE.fullmatch(text)
    unit = None if found is None else _UNITS.get(found.group(2).lower())
    if found is None or unit is None:
        msg = (
            f"{text!r} is not a size; a memory size is a number of bytes or a "
            "number with a unit DuckDB reads. Fix: pass bytes (8_000_000_000) "
            "or a string such as '8GB' or '512MiB' (KB, MB, GB, TB in powers "
            "of 1000; KiB, MiB, GiB, TiB in powers of 1024)."
        )
        raise SqlearnError(msg)
    return float(found.group(1)), unit


def parse(text: str) -> int:
    """Return the bytes a size string names, as DuckDB reads and prints them.

    Parameters
    ----------
    text : str
        A number and a unit: ``"8GB"``, ``"61.0 MiB"``. KB, MB, GB, TB and
        PB are powers of 1000; KiB, MiB, GiB, TiB and PiB powers of 1024;
        no unit, B or bytes is bytes.

    Returns
    -------
    int
        The size in bytes.

    Raises
    ------
    SqlearnError
        If `text` is not a size.

    Examples
    --------
    >>> from sqlearn._memory import parse
    >>> parse("8GB"), parse("1 KiB")
    (8000000000, 1024)
    """
    number, unit = _split(text)
    return int(number * unit)


def physical() -> int:
    """Return the machine's physical memory in bytes, without a dependency.

    Returns
    -------
    int
        Physical memory: from ``sysconf`` on POSIX, from
        ``GlobalMemoryStatusEx`` on Windows.

    Examples
    --------
    >>> from sqlearn._memory import physical
    >>> physical() > 0
    True
    """
    if os.name == "nt":  # pragma: no cover  (Windows only)
        return _windows()
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def _windows() -> int:  # pragma: no cover  (Windows only)
    """Return physical memory through ``GlobalMemoryStatusEx``."""

    class Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    kernel = ctypes.windll.kernel32  # ty: ignore[unresolved-attribute]
    kernel.GlobalMemoryStatusEx(ctypes.byref(status))
    return int(status.ullTotalPhys)


def budget() -> int:
    """Return the process's memory budget in bytes.

    Returns
    -------
    int
        ``sq.set_config(memory=...)``, else 80% of physical memory.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._memory import budget
    >>> sq.set_config(memory="4GB")
    >>> budget()
    4000000000
    >>> sq.set_config(memory=None)
    """
    memory = get_config().memory
    return memory if memory is not None else int(0.8 * physical())


def duckdb_limit(con: duckdb.DuckDBPyConnection) -> int:
    """Return a connection's ``memory_limit`` in bytes, rounded up.

    DuckDB prints the limit with one decimal (``"953.6 MiB"``); half of that
    last digit is added, so the limit is never read as smaller than it is.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection to read.

    Returns
    -------
    int
        The limit in bytes; enormous when the connection is unlimited.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._memory import duckdb_limit
    >>> con = duckdb.connect()
    >>> con.execute("SET memory_limit = '1GB'")  # doctest: +ELLIPSIS
    <...>
    >>> round(duckdb_limit(con) / 10**9, 2)
    1.0
    """
    text = con.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
    number, unit = _split(text)
    return int((number + 0.05) * unit)


def allowance(con: duckdb.DuckDBPyConnection) -> int:
    """Return the bytes a hand-over may hold on `con`.

    The budget less DuckDB's share: the connection's ``memory_limit``, but
    never more than half the budget (Ruling R11). sqlearn's own connection
    is given exactly half; a connection the user passed keeps its own
    limit, and its default (80%) or no limit at all counts as half.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection the data is computed in.

    Returns
    -------
    int
        The allowance in bytes.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._memory import allowance
    >>> sq.set_config(memory="4GB")
    >>> round(allowance(connection()) / 10**9, 1)
    2.0
    >>> sq.set_config(memory=None)
    """
    total = budget()
    return total - min(duckdb_limit(con), total // 2)


def estimate(rel: duckdb.DuckDBPyRelation, columns: Sequence[str]) -> int:
    """Estimate the bytes `columns` of `rel` take once fetched.

    Rows times, per column, 8 bytes for a number and 64 bytes plus the
    average length for a text value (a Python string's overhead), from
    one aggregate query over `rel`. It errs towards a larger size.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The data to be fetched.
    columns : sequence of str
        The columns that will be fetched.

    Returns
    -------
    int
        The estimate in bytes.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._memory import estimate
    >>> rel = connection().sql("SELECT 1.0 AS a, 'abcd' AS s")
    >>> estimate(rel, ["a", "s"])
    76
    """
    if not columns:
        return 0
    kinds = dict(zip(rel.columns, rel.types, strict=True))
    text = [c for c in columns if str(kinds[c]) == "VARCHAR"]
    lengths = [
        duckdb.CoalesceOperator(
            duckdb.FunctionExpression(
                "avg", duckdb.FunctionExpression("strlen", duckdb.ColumnExpression(c))
            ),
            duckdb.ConstantExpression(0),
        )
        for c in text
    ]
    count = duckdb.FunctionExpression("count", duckdb.StarExpression())
    rows, *averages = rel.aggregate([count, *lengths]).fetchall()[0]
    per_row = _NUMBER * (len(columns) - len(text))
    per_row += sum(_TEXT + float(a) for a in averages)
    return int(rows * per_row + 0.999999)


def _megabytes(size: int) -> str:
    """Write a size in MB (powers of 1000), as the messages give it."""
    return f"{size / 10**6:,.0f} MB"


def check(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
) -> None:
    """Refuse a fetch of `columns` of `rel` that would not fit in memory.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection the data is computed in.
    rel : duckdb.DuckDBPyRelation
        The data to be fetched.
    columns : sequence of str
        The columns that will be fetched.

    Raises
    ------
    SqlearnError
        If the estimate is over the allowance; swapping is never the
        fallback.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._memory import check
    >>> check(connection(), connection().sql("SELECT 1.0 AS a"), ["a"])
    """
    size = estimate(rel, columns)
    room = allowance(con)
    if size <= room:
        return
    fixes = [
        'feed="stream" on a model with partial_fit, which holds one batch at a time',
        f"a larger budget (sq.set_config(memory=...), now {_megabytes(budget())})",
        "fewer columns",
    ]
    if get_config().connection is not None:
        fixes.append(
            "a smaller SET memory_limit on the connection you passed, which "
            "DuckDB's share is read from"
        )
    msg = (
        f"the data to hand to the model is about {_megabytes(size)} and the "
        f"memory it may use is {_megabytes(max(room, 0))}; loading it would "
        "swap, which sqlearn never does. Fix: " + "; or ".join(fixes) + "."
    )
    raise SqlearnError(msg)
