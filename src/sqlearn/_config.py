"""The global configuration: the output kind and the DuckDB connection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import duckdb

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

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.get_config().out is None
    True
    """

    out: str | Output | None = None
    connection: duckdb.DuckDBPyConnection | None = None


_config = Config()
_default_connection: duckdb.DuckDBPyConnection | None = None
_UNSET: object = object()


def set_config(
    *,
    out: str | Output | object | None = _UNSET,
    connection: duckdb.DuckDBPyConnection | object | None = _UNSET,
) -> None:
    """Set the global configuration; a field left out keeps its value.

    Parameters
    ----------
    out : str or Output, optional
        The default output kind; None restores the library's default.
    connection : duckdb.DuckDBPyConnection, optional
        The connection to compute in; None restores the shared in-memory one.

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
    _config = replace(_config, **changes)  # type: ignore[arg-type]


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
        opened on first use and reused.

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
    return _default_connection


def _reset() -> None:
    """Restore the defaults and drop the shared connection (for tests)."""
    global _config, _default_connection
    _config = Config()
    _default_connection = None
