"""Reading inputs: turn what the user passes into a relation and a data key."""

import contextlib
import glob
import itertools
import os
import warnings
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnError, SqlearnWarning
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
_PACKAGE = (str(Path(__file__).parent),)
"""sqlearn's own files: a warning is placed at the first frame outside them."""
Storage = tuple[tuple[int, ...], tuple[int, ...], int]
"""A file table's storage: its blocks, the row groups edited since the last
checkpoint, and the number of its segments not yet written to the file."""
_last_blocks: dict[tuple[str, str], Storage] = {}
"""The storage each (database file, table) had when sqlearn last read it."""
_connection_tokens: weakref.WeakKeyDictionary[duckdb.DuckDBPyConnection, int] = (
    weakref.WeakKeyDictionary()
)
_token_ids = itertools.count()
_pending: list[tuple[weakref.ref[duckdb.DuckDBPyConnection], str, bool]] = []
"""Registrations (False) and tables (True) whose owner is gone, released at the next `read`."""  # noqa: E501


def _release_later(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Queue a registration for release; what every finaliser calls.

    The garbage collector may run a finaliser in the middle of a query, when
    the connection refuses any call. So a finaliser never touches the
    connection: it only queues the name, and the next `read` (the start of
    every public call) unregisters it.
    """
    _pending.append((weakref.ref(con), name, False))


def _drop_later(con: duckdb.DuckDBPyConnection, table: str) -> None:
    """Queue a table sqlearn made for dropping at the next `read`.

    As `_release_later`, for a table: `table` is its qualified name, each
    part quoted.
    """
    _pending.append((weakref.ref(con), table, True))


def _release_pending() -> None:
    """Release every queued registration and table whose connection is open."""
    while _pending:
        ref, name, table = _pending.pop()
        con = ref()
        if con is not None:
            with contextlib.suppress(duckdb.Error):
                if table:
                    con.execute(f"DROP TABLE IF EXISTS {name}")
                else:
                    con.unregister(name)


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
    stable : tuple, optional
        A key that names the same data in any process, or None when the
        input has none; read it with `stable_key`.

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
    stable: DataKey | None = None

    def stable_key(self) -> DataKey | None:
        """Return a key naming the same data in any process, or None.

        `key` may hold a connection's token, valid in this process only.
        This key does not: a file by its absolute path, size and
        modification time; a pandas frame by its content hash (DuckDB's,
        the same in every process for one DuckDB version); a table in a
        database file by the file, its name, row count, columns and
        storage (its block ids, read from metadata), so an edit in place
        is seen once checkpointed, and the first edit of a row group
        already before. A relation, or a table of an in-memory database,
        has none.

        Returns
        -------
        tuple or None
            The key, or None when the input has no stable identity.

        Examples
        --------
        >>> from sqlearn._config import connection
        >>> from sqlearn._inputs import read
        >>> read(connection().sql("SELECT 1 AS a")).stable_key() is None
        True
        """
        return self.stable


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
    stable = ("file", tuple((os.path.realpath(p), n, t) for p, n, t in stats))
    return Source(relation, ("file", tuple(stats)), _schema(relation), stable)


def _file_table(
    con: duckdb.DuckDBPyConnection, name: str
) -> tuple[str, str, str] | None:
    """Return the database file and names of a base table, or None.

    `name` is ``table``, ``schema.table``, ``database.table`` or
    ``database.schema.table``, unquoted. The names returned are
    ``schema.table``, for the key, and the quoted
    ``"database"."schema"."table"``, for SQL. None when it names a view, a
    temporary table or a table of an in-memory database: those have no
    identity outside this process.
    """
    parts = name.split(".")
    if len(parts) > 3 or any(not p for p in parts):
        return None
    current = con.sql("SELECT current_database(), current_schema()").fetchall()[0]
    if len(parts) == 1:
        candidates = [(current[0], current[1], parts[0])]
    elif len(parts) == 2:
        candidates = [(current[0], parts[0], parts[1]), (parts[0], "main", parts[1])]
    else:
        candidates = [(parts[0], parts[1], parts[2])]
    tables = con.sql("FROM duckdb_tables()")
    column = duckdb.ColumnExpression

    def same(col: str, value: str) -> duckdb.Expression:
        lowered = duckdb.FunctionExpression("lower", column(col))
        return lowered == duckdb.ConstantExpression(value.lower())

    temporary = tables.filter(
        column("temporary") & same("table_name", parts[-1])
    ).count("*")
    if len(parts) == 1 and temporary.fetchall()[0][0]:
        return None  # a temporary table shadows the database's
    for database, schema, table in candidates:
        found = (
            tables.filter(
                same("database_name", database)
                & same("schema_name", schema)
                & same("table_name", table)
                & ~column("temporary")
            )
            .join(con.sql("FROM duckdb_databases()").set_alias("d"), "database_name")
            .project(
                column("path"),
                column("database_name"),
                column("schema_name"),
                column("table_name"),
            )
            .fetchall()
        )
        if found:
            path, database_name, schema_name, table_name = found[0]
            if path is None:
                return None  # an in-memory database
            sql_name = ".".join(
                quote(p) for p in (database_name, schema_name, table_name)
            )
            return (
                os.path.realpath(str(path)),
                f"{schema_name}.{table_name}",
                sql_name,
            )
    return None


def _storage_blocks(con: duckdb.DuckDBPyConnection, qualified: str) -> Storage:
    """Return a table's storage, from its metadata: no row is scanned.

    Read in one pass over ``pragma_storage_info(qualified)``, which lists
    the table's segments (its cost grows with them, not with the rows):

    - the sorted distinct ids of the blocks written to the file. A
      checkpoint after an edit writes the edited segments to new blocks, so
      the ids change with the data; with no edit they stay;
    - the row groups edited since the last checkpoint. An ``UPDATE`` still
      in the write-ahead log leaves the blocks as they were but marks its
      row groups; a second edit of a marked row group before the checkpoint
      changes nothing here;
    - the number of segments not yet written to the file (a small table just
      created, rows just inserted), which get their blocks at the
      checkpoint.
    """
    sql = (
        "SELECT coalesce(list(DISTINCT block_id ORDER BY block_id) "
        "FILTER (WHERE persistent), []), "
        "coalesce(list(DISTINCT row_group_id ORDER BY row_group_id) "
        "FILTER (WHERE has_updates), []), "
        "count(*) FILTER (WHERE NOT persistent) "
        "FROM pragma_storage_info(?)"
    )
    blocks, groups, unwritten = con.execute(sql, [qualified]).fetchall()[0]
    return (
        tuple(int(b) for b in blocks),
        tuple(int(g) for g in groups),
        int(unwritten),
    )


def _storage(con: duckdb.DuckDBPyConnection, where: tuple[str, str, str]) -> Storage:
    """Return a file table's storage, warning when it changed since last read.

    The warning is raised once per change, not on every read. It is not
    raised when only the blocks of what was unwritten at the last read came
    (a checkpoint writing them): the key changes, so the table is prepared
    again, but no edit can be told from the checkpoint itself.
    """
    path, qualified, sql_name = where
    storage = _storage_blocks(con, sql_name)
    last = _last_blocks.get((path, qualified))
    _last_blocks[(path, qualified)] = storage
    if last is None or last == storage:
        return storage
    written = not last[1] and not last[2]
    if written or last[0] == storage[0]:
        text = (
            f"the table {qualified} in {os.path.basename(path)} changed since "
            "sqlearn last read it; what was learned or prepared from it before "
            "is not reused. Why: its storage differs from what was read then, "
            "so its values may differ though its rows and columns do not. "
            "Fix: nothing to do; to have every edit seen, run CHECKPOINT after "
            "editing the table."
        )
        warnings.warn(text, SqlearnWarning, skip_file_prefixes=_PACKAGE)
    return storage


def _read_table(name: str) -> Source:
    con = connection()
    try:
        relation = con.table(name)
    except duckdb.CatalogException as exc:
        msg = f"{name!r} is not a file or a table on the connection. Pass {_ACCEPTED}."
        raise SqlearnError(msg) from exc
    schema = _schema(relation)
    rows = _row_count(relation)
    key: DataKey = (
        "table",
        _connection_token(con),
        name,
        rows,
        _names_and_types(schema),
    )
    where = _file_table(con, name)
    if where is None:
        return Source(relation, key, schema, None)
    # A table in a file is also known by its storage: an edit keeping the
    # row count and columns changes it (#50).
    storage = _storage(con, where)
    stable = ("table", where[0], where[1], rows, _names_and_types(schema), storage)
    return Source(relation, (*key, storage), schema, stable)


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
    key = ("frame", rows, digest, _names_and_types(schema))
    # Every part is the frame's content, so the same in any process.
    source = Source(relation, key, schema, key)
    # Release the registration (and so the reference to the frame) once the
    # source is dropped: the store never keeps the user's data alive.
    weakref.finalize(source, _release_later, con, name)
    return source


def _read_relation(data: duckdb.DuckDBPyRelation) -> Source:
    """Read a relation through a temporary view registered on the connection.

    The registration keeps the relation's own scans (a Python frame found by
    name) alive and lets sqlearn read it by name; being temporary, it is never
    written to the user's database, and works on a read-only one. A relation
    of another connection cannot be registered there, so it is refused.
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
    con = connection()
    try:
        con.register(name, data)
    except duckdb.InvalidInputException as exc:
        msg = (
            "The relation passed belongs to another DuckDB connection than "
            "the one sqlearn computes in. sqlearn runs every query on one "
            "connection, so it cannot read it. Fix: call "
            "sq.set_config(connection=con) with the relation's connection, "
            "or pass a table name, a file or a pandas frame."
        )
        raise SqlearnError(msg) from exc
    relation = con.table(name)
    source = Source(relation, key, _schema(relation))
    weakref.finalize(source, _release_later, con, name)
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
    _release_pending()
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
