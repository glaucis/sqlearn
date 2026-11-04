"""Reading inputs: turn what the user passes into a relation and a data key."""

import contextlib
import glob
import itertools
import os
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._selectors import Schema

__all__ = ["DataKey", "Source", "read"]

DataKey = tuple[Any, ...]
"""A hashable tuple that changes whenever the data it names changes."""

_READERS = {".parquet": "read_parquet", ".csv": "read_csv", ".json": "read_json"}
_ACCEPTED = (
    "a path or glob ending in .parquet, .csv or .json, a table name, "
    "a DuckDB relation, or a pandas DataFrame"
)
_frame_ids = itertools.count()
_connection_tokens: weakref.WeakKeyDictionary[duckdb.DuckDBPyConnection, int] = (
    weakref.WeakKeyDictionary()
)
_token_ids = itertools.count()


class _Frame(Protocol):
    """What is needed of a pandas frame, so pandas is never imported here."""

    def copy(self) -> Any: ...  # noqa: ANN401


@dataclass(frozen=True)
class Source:
    """An input read as a DuckDB relation, with its key and schema.

    Attributes
    ----------
    relation : duckdb.DuckDBPyRelation
        The data as a relation on the configured connection.
    key : tuple
        A hashable key that changes whenever the data changes.
    schema : list of tuple of (str, DuckDBPyType)
        The ordered ``(name, type)`` pairs of the relation.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._inputs import read
    >>> source = read(connection().sql("SELECT 1 AS a"))
    >>> [name for name, _ in source.schema]
    ['a']
    """

    relation: duckdb.DuckDBPyRelation
    key: DataKey
    schema: Schema


def _schema(relation: duckdb.DuckDBPyRelation) -> Schema:
    return list(zip(relation.columns, relation.types, strict=True))


def _names_and_types(schema: Schema) -> tuple[tuple[str, str], ...]:
    """Return the schema as text, for a key: DuckDB's row hash skips names."""
    return tuple((name, str(dtype)) for name, dtype in schema)


def _row_count(relation: duckdb.DuckDBPyRelation) -> int:
    return int(relation.count("*").fetchall()[0][0])


def _connection_token(con: duckdb.DuckDBPyConnection) -> int:
    """Return the number given to `con` on first sight, never given to another.

    A table or relation is known by its connection (ADR 0014). `id(con)` is
    not enough: once a connection is closed and collected, a new one can get
    the same id while the store still holds keys made with it. A counter
    never repeats, and the weak mapping does not keep a connection alive.
    """
    token = _connection_tokens.get(con)
    if token is None:
        token = _connection_tokens[con] = next(_token_ids)
    return token


def _fingerprint(name: str) -> tuple[int, int]:
    """Hash every value together with its row position, in one query.

    Each row is hashed whole, combined with its row number, and the hashes
    are XOR-ed: changing a value or moving a row changes the result. The
    hash does not cover the column names, so the key adds the schema. The row
    count is returned beside it.
    """
    sql = (
        "SELECT count(*), coalesce(bit_xor(hash(t, rn)), 0) FROM "
        f"(SELECT *, row_number() OVER () AS rn FROM {quote(name)}) AS t"
    )
    rows = connection().sql(sql).fetchall()
    return int(rows[0][0]), int(rows[0][1])


def _is_pandas_frame(data: object) -> bool:
    return any(
        cls.__name__ == "DataFrame" and cls.__module__.startswith("pandas")
        for cls in type(data).__mro__
    )


def _read_files(pattern: str) -> Source:
    suffix = Path(pattern).suffix.lower()
    matches = sorted(glob.glob(pattern))
    if not matches:
        msg = (
            f"No file matches {pattern!r}. Check the path or glob; it must "
            "point at existing .parquet, .csv or .json files."
        )
        raise SqlearnError(msg)
    stats = []
    for path in matches:
        info = os.stat(path)
        stats.append((path, info.st_size, info.st_mtime_ns))
    paths = ", ".join("'" + p.replace("'", "''") + "'" for p in matches)
    relation = connection().sql(f"SELECT * FROM {_READERS[suffix]}([{paths}])")
    return Source(relation, ("file", tuple(stats)), _schema(relation))


def _read_table(name: str) -> Source:
    con = connection()
    try:
        relation = con.table(name)
    except duckdb.CatalogException as exc:
        msg = f"{name!r} is not a file or a table on the connection. Pass {_ACCEPTED}."
        raise SqlearnError(msg) from exc
    schema = _schema(relation)
    key = (
        "table",
        _connection_token(con),
        name,
        _row_count(relation),
        _names_and_types(schema),
    )
    return Source(relation, key, schema)


def _read_frame(frame: _Frame) -> Source:
    con = connection()
    name = f"_sqlearn_frame_{next(_frame_ids)}"
    try:
        con.register(name, frame)
    except duckdb.Error:
        # DuckDB cannot scan negatively strided arrays (a reversed frame):
        # only then fall back to a contiguous copy.
        con.register(name, frame.copy())
    relation = con.table(name)
    rows, digest = _fingerprint(name)
    schema = _schema(relation)
    source = Source(relation, ("frame", rows, digest, _names_and_types(schema)), schema)
    # Release the registration (and so the reference to the frame) once the
    # source is dropped: the store never keeps the user's data alive.
    weakref.finalize(source, con.unregister, name)
    return source


def _drop_view(con: duckdb.DuckDBPyConnection, name: str) -> None:
    with contextlib.suppress(duckdb.Error):
        con.execute(f"DROP VIEW IF EXISTS {quote(name)}")


def _read_relation(data: duckdb.DuckDBPyRelation) -> Source:
    """Read a relation through a view on its own connection.

    The view keeps the relation's own scans (a Python frame found by name)
    alive, and lets sqlearn's connection read it by name. A relation of
    another connection cannot be seen there, so it is refused.
    """
    try:
        key = (
            "relation",
            _connection_token(connection()),
            data.sql_query(),
            _row_count(data),
            _names_and_types(_schema(data)),
        )
    except duckdb.Error as exc:
        msg = (
            f"DuckDB cannot read the relation passed: {exc}\n"
            "Fix: check that the tables and files it reads still exist."
        )
        raise SqlearnError(msg) from exc
    name = f"_sqlearn_relation_{next(_frame_ids)}"
    data.create_view(name, replace=False)
    con = connection()
    try:
        relation = con.table(name)
    except duckdb.CatalogException as exc:
        data.query("_sqlearn_self", f"DROP VIEW {quote(name)}")
        msg = (
            "The relation passed belongs to another DuckDB connection than "
            "the one sqlearn computes in. sqlearn runs every query on one "
            "connection, so it cannot read it. Fix: call "
            "sq.set_config(connection=con) with the relation's connection, "
            "or pass a table name, a file or a pandas frame."
        )
        raise SqlearnError(msg) from exc
    source = Source(relation, key, _schema(relation))
    weakref.finalize(source, _drop_view, con, name)
    return source


def read(data: object) -> Source:
    """Read an input as a relation, keyed so the store knows when it changes.

    Parameters
    ----------
    data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
        A path or glob ending in ``.parquet``, ``.csv`` or ``.json``; any
        other string names a table on the connection; a relation; or a
        pandas frame.

    Returns
    -------
    Source
        The relation, its key and its schema.

    Raises
    ------
    SqlearnError
        If a path or glob matches nothing, a table is missing, a relation
        belongs to another connection or cannot be read, or the input is of
        a kind not accepted.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._inputs import read
    >>> source = read(connection().sql("SELECT 1 AS a"))
    >>> source.key[0], source.relation.fetchall()
    ('relation', [(1,)])
    """
    if isinstance(data, duckdb.DuckDBPyRelation):
        return _read_relation(data)
    if isinstance(data, (str, Path)):
        text = str(data)
        if Path(text).suffix.lower() in _READERS:
            return _read_files(text)
        return _read_table(text)
    if _is_pandas_frame(data):
        return _read_frame(cast("_Frame", data))
    module = type(data).__module__.split(".")[0]
    if module in {"polars", "pyarrow"}:
        msg = (
            f"{module} data is not read yet: it comes after the core (see "
            f"spec §7). Pass {_ACCEPTED}."
        )
        raise SqlearnError(msg)
    msg = f"Cannot read a {type(data).__name__}. The accepted inputs are {_ACCEPTED}."
    raise SqlearnError(msg)
