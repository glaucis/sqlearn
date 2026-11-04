"""Reading inputs: turn what the user passes into a relation and a data key."""

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


def _row_count(relation: duckdb.DuckDBPyRelation) -> int:
    return int(relation.count("*").fetchall()[0][0])


def _fingerprint(name: str) -> tuple[int, int]:
    """Hash every value together with its row position, in one query.

    Each row is hashed whole (names and values), combined with its row
    number, and the hashes are XOR-ed: changing a value or moving a row
    changes the result. The row count is returned beside it.
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
    key = ("table", id(con), name, _row_count(relation))
    return Source(relation, key, _schema(relation))


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
    source = Source(relation, ("frame", rows, digest), _schema(relation))
    # Release the registration (and so the reference to the frame) once the
    # source is dropped: the store never keeps the user's data alive.
    weakref.finalize(source, con.unregister, name)
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
        If a path or glob matches nothing, a table is missing, or the input
        is of a kind not accepted.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._inputs import read
    >>> source = read(connection().sql("SELECT 1 AS a"))
    >>> source.key[0], source.relation.fetchall()
    ('relation', [(1,)])
    """
    if isinstance(data, duckdb.DuckDBPyRelation):
        key = ("relation", data.sql_query(), _row_count(data))
        return Source(data, key, _schema(data))
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
