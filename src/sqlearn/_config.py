"""The global configuration: the output kind, the connection, the memory budget."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import duckdb

from sqlearn._errors import SqlearnError

if TYPE_CHECKING:
    from sqlearn._output import Output

__all__ = ["Config", "connection", "get_config", "set_config"]


@dataclass(frozen=True)
class Config:
    """The settings `set_config` changes.

    Attributes
    ----------
    out : str or Output or None
        The default output kind, or None for the library's default.
    connection : duckdb.DuckDBPyConnection or None
        The connection to compute in, or None for a shared in-memory one.
    memory : int or None
        The memory budget in bytes, or None for 80% of physical memory.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.get_config().out is None
    True
    """

    out: str | Output | None = None
    connection: duckdb.DuckDBPyConnection | None = None
    memory: int | None = None


_config = Config()
_default_connection: duckdb.DuckDBPyConnection | None = None
_UNSET: object = object()


def set_config(
    *,
    out: str | Output | object | None = _UNSET,
    connection: duckdb.DuckDBPyConnection | object | None = _UNSET,
    memory: int | str | object | None = _UNSET,
) -> None:
    """Set the global configuration; a field left out keeps its value.

    Parameters
    ----------
    out : str or Output, optional
        The default output kind; None restores the library's default.
    connection : duckdb.DuckDBPyConnection, optional
        The connection to compute in; None restores the shared in-memory one.
        sqlearn never changes a connection passed here, save one addition:
        the first streamed prediction attaches a private in-memory
        database, ``__sqlearn_feed``, which holds the predictions and stays
        attached. The connection's ``memory_limit`` counts as at most half
        the memory budget; when it is above half, a `SqlearnWarning` says
        so, once per process.
    memory : int or str, optional
        The memory budget the process shares between DuckDB and the data
        handed to a model: bytes, or a size DuckDB reads (``"8GB"``,
        ``"512MiB"``); None restores the default, 80% of physical memory.
        sqlearn's own connection is given half of it as DuckDB's
        ``memory_limit``; a fold that would not fit in the rest is refused
        before it is fetched, never swapped.

    Raises
    ------
    SqlearnError
        If `memory` is not a positive number of bytes nor a size.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.set_config(out="pandas")
    >>> sq.get_config().out
    'pandas'
    >>> sq.set_config(out=None)
    """
    global _config
    changes: dict[str, object] = {}
    if out is not _UNSET:
        changes["out"] = out
    if connection is not _UNSET:
        changes["connection"] = connection
    if memory is not _UNSET:
        changes["memory"] = _bytes(memory)
    _config = replace(_config, **changes)  # type: ignore[arg-type]
    if memory is not _UNSET and _default_connection is not None:
        _limit(_default_connection)  # the shared connection follows (R3)


def _bytes(memory: object) -> int | None:
    """Return a memory budget in bytes, or refuse what is not a size."""
    from sqlearn._memory import parse

    if memory is None:
        return None
    if isinstance(memory, str):
        size = parse(memory)
    elif isinstance(memory, int) and not isinstance(memory, bool):
        size = memory
    else:
        size = 0
    if size <= 0:
        msg = (
            f"memory={memory!r} is not a size; the budget is a positive number "
            "of bytes. Fix: pass bytes (8_000_000_000) or a string such as "
            "'8GB', or None for the default."
        )
        raise SqlearnError(msg)
    return size


def _limit(con: duckdb.DuckDBPyConnection) -> None:
    """Give sqlearn's own connection half the budget as DuckDB's limit."""
    from sqlearn._memory import budget

    con.execute("SET memory_limit = ?", [f"{budget() // 2}B"])


def get_config() -> Config:
    """Return the current configuration.

    Returns
    -------
    Config
        The frozen configuration.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.get_config().connection is None
    True
    """
    return _config


def connection() -> duckdb.DuckDBPyConnection:
    """Return the configured connection, else the shared in-memory one.

    Returns
    -------
    duckdb.DuckDBPyConnection
        The configured connection; failing that, one in-memory connection
        opened on first use and reused, its ``memory_limit`` half the
        memory budget.

    Examples
    --------
    >>> from sqlearn import _config
    >>> _config.connection() is _config.connection()
    True
    """
    global _default_connection
    if _config.connection is not None:
        return _config.connection
    if _default_connection is None:
        _default_connection = duckdb.connect()
        _limit(_default_connection)
    return _default_connection


def _reset() -> None:
    """Restore the defaults and drop the shared connection (for tests)."""
    global _config, _default_connection
    _config = Config()
    _default_connection = None
