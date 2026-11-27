"""Kept preparations: a search's prepared fold tables in a DuckDB file.

With ``keep_prepared=path``, each fold's prepared rows are written once to a
DuckDB file, under the schema ``sqlearn_prepared``, and read back by every
later search on the same data, steps and folds, in this process or another
(spec §4). A table's name carries its key in short: the data's stable key,
the steps' qualified class names and settings, the fold scheme and fold, and
the versions of sqlearn and DuckDB. ``_index`` lists every kept table.

The file is attached to the connection only while it is used and detached
afterwards, so no other process finds it locked. The SQL text here is for
tables sqlearn owns (Ruling R1): every identifier goes through `quote()`,
the path through literal quoting, and values are passed as parameters.
"""

import dataclasses
import datetime
import functools
import hashlib
import os
import types
import uuid
import weakref
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Self

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn._expr import quote
from sqlearn._inputs import _drop_later
from sqlearn._selectors import Selector
from sqlearn._step import Step
from sqlearn.agg.aggregates import Aggregate

__all__ = ["INDEX", "SCHEMA", "KeptFolds", "clear", "prepared", "table_name"]

SCHEMA = "sqlearn_prepared"
"""The schema of the kept tables in the file."""
INDEX = "_index"
"""The table listing each kept table: its data, steps, folds and fold."""
_ALIAS = "__sqlearn_kept"
"""The prefix of the name the file is attached under while it is used."""
_COLUMNS = (
    ("table", "VARCHAR"),
    ("data", "VARCHAR"),
    ("steps", "VARCHAR"),
    ("folds", "VARCHAR"),
    ("fold", "INTEGER"),
    ("sqlearn_version", "VARCHAR"),
    ("created", "TIMESTAMP"),  # UTC
)
_PLAIN = (str, int, float, bool, bytes, type(None))
_FUNCTIONS = (types.FunctionType, types.BuiltinFunctionType, type)


@functools.cache
def _sqlearn_version() -> str:
    return metadata.version("sqlearn")


def _unkeyable(step: str, name: str, what: str) -> SqlearnError:
    """Explain a setting that a kept preparation cannot key by its content."""
    msg = (
        f"the setting {name!r} of the step {step!r} is {what}, which sqlearn "
        "cannot key by its content, so with keep_prepared a kept preparation "
        "could be read back for another value, in this session or a later "
        "one. Fix: give a plain value (a number, text, None, or a list, "
        "tuple, dict or set of them), a module-level function, a step or a "
        "numpy array, or search without keep_prepared."
    )
    return SqlearnError(msg)


def _stable_setting(step: str, name: str, value: object) -> object:
    """Return a setting in a form that is the same in every process.

    Only what can be keyed by content is accepted; a repr is never trusted
    in general, since reprs elide (numpy, pandas) or print addresses. Plain
    values keep their type (so ``True`` and ``1`` differ); lists, tuples,
    dicts and sets are followed (dicts and sets sorted); a module-level
    function or class is its dotted path; a step is its class and settings;
    a numpy array its dtype, shape and the SHA-256 of its bytes. sqlearn's
    own selectors and aggregates are followed through their fields and
    params. Anything else is refused.
    """
    keyed = functools.partial(_stable_setting, step, name)
    kind = type(value)
    if isinstance(value, _PLAIN):
        return (kind.__qualname__, value)
    if isinstance(value, (list, tuple)):
        return (kind.__qualname__, tuple(keyed(v) for v in value))
    if isinstance(value, dict):
        items = [(keyed(k), keyed(v)) for k, v in value.items()]
        return ("dict", tuple(sorted(items, key=repr)))
    if isinstance(value, (set, frozenset)):
        return (kind.__qualname__, tuple(sorted((keyed(v) for v in value), key=repr)))
    if isinstance(value, _FUNCTIONS):
        path = f"{value.__module__}.{value.__qualname__}"
        if "<" in path:  # <lambda>, or a function defined inside another
            raise _unkeyable(
                step, name, f"{path}, a function without a name of its own"
            )
        return path
    if isinstance(value, Step):
        return steps_identity([(f"{step}.{name}", value)])[0][1:]
    if isinstance(value, Selector) and dataclasses.is_dataclass(kind):
        fields = dataclasses.fields(kind)
        return (
            f"{kind.__module__}.{kind.__qualname__}",
            tuple((f.name, keyed(getattr(value, f.name))) for f in fields),
        )
    if isinstance(value, Aggregate):
        return ("sq.agg", value.name, keyed(dict(value.params)))
    if kind.__module__ == "numpy" and kind.__name__ == "ndarray":
        array: Any = value
        if array.dtype.hasobject:
            raise _unkeyable(step, name, "a numpy array of Python objects")
        digest = hashlib.sha256(array.tobytes()).hexdigest()  # C order always
        return ("ndarray", str(array.dtype), tuple(array.shape), digest)
    if (
        kind.__module__ == "numpy"
        and hasattr(value, "dtype")
        and hasattr(value, "item")
    ):
        scalar: Any = value
        return ("numpy", str(scalar.dtype), keyed(scalar.item()))
    raise _unkeyable(step, name, f"a {kind.__module__}.{kind.__qualname__}")


_Identity = tuple[tuple[str, str, tuple[tuple[str, object], ...]], ...]


def steps_identity(steps: Sequence[tuple[str, Step]]) -> _Identity:
    """Return the steps as their names, qualified class names and settings.

    Parameters
    ----------
    steps : sequence of tuple of (str, Step)
        The named steps that prepare a fold (the model left out).

    Returns
    -------
    tuple
        One ``(name, module.class, settings)`` per step, settings sorted by
        name; the same in every process.

    Raises
    ------
    SqlearnError
        If a setting cannot be keyed by its content: a lambda, a function
        defined inside another, or a value of a type not listed in
        `_stable_setting` (a ``functools.partial``, a pandas object, ...).

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn.model_selection.kept import steps_identity
    >>> steps_identity([("scale", sq.scale.standard())])[0][:2]
    ('scale', 'sqlearn.preprocessing.scale.Scale')
    """
    return tuple(
        (
            name,
            f"{type(step).__module__}.{type(step).__qualname__}",
            tuple(
                sorted(
                    (k, _stable_setting(name, k, v)) for k, v in step.settings().items()
                )
            ),
        )
        for name, step in steps
    )


def table_name(
    stable: tuple[object, ...],
    steps: Sequence[tuple[str, Step]],
    folds_key: tuple[object, ...],
    k: int,
) -> str:
    """Return the name of fold `k`'s kept table, its key in short.

    Parameters
    ----------
    stable : tuple
        The data's stable key (`Source.stable_key`), with whatever else
        the prepared rows depend on (the search passes the target too).
    steps : sequence of tuple of (str, Step)
        The named steps that prepare the fold.
    folds_key : tuple
        The fold scheme's `key`.
    k : int
        The fold.

    Returns
    -------
    str
        ``fold_<k>_`` and the first 12 hex digits of the SHA-256 of the
        key's repr, with sqlearn's and DuckDB's versions.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn.model_selection.kept import table_name
    >>> name = table_name(
    ...     ("file", ()), [("scale", sq.scale.standard())], ("kfold", 3, 0), 1
    ... )
    >>> name.startswith("fold_1_"), len(name)
    (True, 19)
    """
    key = (
        stable,
        steps_identity(steps),
        folds_key,
        k,
        _sqlearn_version(),
        duckdb.__version__,
    )
    digest = hashlib.sha256(repr(key).encode()).hexdigest()[:12]
    return f"fold_{k}_{digest}"


def _utc_now() -> datetime.datetime:
    """Return the time now in UTC, without a zone: plain TIMESTAMP needs no pytz."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class KeptFolds:
    """The kept fold tables of one DuckDB file, attached while in use.

    Opening attaches the file (made if missing) to sqlearn's connection
    under a private name and makes the schema ``sqlearn_prepared`` and its
    ``_index``. If the connection already has that file attached (it is the
    connection's own database, say), that database is used and left as it
    is. `close` (or leaving a ``with`` block) detaches what was attached.

    Parameters
    ----------
    path : str or os.PathLike
        The DuckDB file.
    read_only : bool, default False
        Attach without writing: no schema or index is made.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> from sqlearn.model_selection.kept import KeptFolds
    >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
    >>> with KeptFolds(path) as kept:
    ...     kept.get("fold_0_000000000000") is None
    True
    """

    def __init__(self, path: str | os.PathLike[str], read_only: bool = False) -> None:
        self.path = os.path.realpath(Path(path))
        self._con = connection()
        self._attached = False
        databases = self._con.sql(
            "SELECT database_name, path FROM duckdb_databases()"
        ).fetchall()
        known = [
            name
            for name, where in databases
            if where is not None and os.path.realpath(where) == self.path
        ]
        if known:
            self.database = known[0]
        else:
            # Each opening its own name: two files open at once never collide.
            self.database = f"{_ALIAS}_{uuid.uuid4().hex}"
            mode = " (READ_ONLY)" if read_only else ""
            try:
                self._con.execute(
                    f"ATTACH {_literal(self.path)} AS {quote(self.database)}{mode}"
                )
            except duckdb.Error as exc:
                msg = (
                    f"sqlearn could not open {self.path!r}, the file that "
                    f"keep_prepared names: {exc}\nWhy: the prepared folds "
                    "are kept in that DuckDB file, so it must be a DuckDB "
                    "database this DuckDB version can write, not open in "
                    "another process. Fix: close the other process that has "
                    "it open (one process writes a DuckDB file at a time), "
                    "or name another file, or delete this one if it is not "
                    "a database you need."
                )
                raise SqlearnError(msg) from exc
            self._attached = True
        if not read_only:
            try:
                self._con.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema()}")
                columns = ", ".join(f"{quote(c)} {t}" for c, t in _COLUMNS)
                self._con.execute(
                    f"CREATE TABLE IF NOT EXISTS {self.qualified(INDEX)} ({columns})"
                )
            except BaseException:
                self.close()
                raise

    def _schema(self) -> str:
        return f"{quote(self.database)}.{quote(SCHEMA)}"

    def qualified(self, name: str) -> str:
        """Return a table's name in the file, each part quoted.

        Parameters
        ----------
        name : str
            The table's name in the schema.

        Returns
        -------
        str
            ``database.sqlearn_prepared.name``, quoted; the database is the
            name the file is attached under.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> with KeptFolds(path) as kept:
        ...     kept.qualified("t").split(".")[1:]
        ['"sqlearn_prepared"', '"t"']
        """
        return f"{self._schema()}.{quote(name)}"

    def tables(self) -> list[str]:
        """Return the names of the tables in the schema, the index left out.

        Returns
        -------
        list of str
            The kept tables, indexed or not.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> with KeptFolds(path) as kept:
        ...     kept.tables()
        []
        """
        column = duckdb.ColumnExpression
        rows = (
            self._con.sql("FROM duckdb_tables()")
            .filter(
                (column("database_name") == duckdb.ConstantExpression(self.database))
                & (column("schema_name") == duckdb.ConstantExpression(SCHEMA))
                & (column("table_name") != duckdb.ConstantExpression(INDEX))
            )
            .project(column("table_name"))
            .fetchall()
        )
        return sorted(name for (name,) in rows)

    def get(self, name: str) -> str | None:
        """Return a kept table's qualified name, or None when it is not kept.

        A table counts as kept when the index lists it and it exists.

        Parameters
        ----------
        name : str
            The table's name, from `table_name`.

        Returns
        -------
        str or None
            The qualified name, quoted, to read the table by.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> with KeptFolds(path) as kept:
        ...     _ = kept.put("fold_0_x", "SELECT 1 AS a", ("d", "s", "f", 0))
        ...     kept.get("fold_0_x") == kept.qualified("fold_0_x")
        True
        """
        listed = (
            self._con.table(self.qualified(INDEX))
            .filter(duckdb.ColumnExpression("table") == duckdb.ConstantExpression(name))
            .count("*")
            .fetchall()[0][0]
        )
        if not listed or name not in self.tables():
            return None
        return self.qualified(name)

    def put(self, name: str, sql: str, row: tuple[str, str, str, int]) -> str:
        """Write a table from a query and list it in the index.

        A table of that name left over without its index row is replaced.

        Parameters
        ----------
        name : str
            The table's name, from `table_name`.
        sql : str
            The query whose rows the table holds.
        row : tuple of (str, str, str, int)
            The index's ``data``, ``steps``, ``folds`` and ``fold``.

        Returns
        -------
        str
            The qualified name, quoted.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> with KeptFolds(path) as kept:
        ...     table = kept.put("fold_0_x", "SELECT 1 AS a", ("d", "s", "f", 0))
        ...     kept.tables()
        ['fold_0_x']
        """
        table = self.qualified(name)
        index = self.qualified(INDEX)
        self._con.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}")
        try:
            self._con.execute(f"DELETE FROM {index} WHERE {quote('table')} = ?", [name])
            self._con.execute(
                f"INSERT INTO {index} VALUES (?, ?, ?, ?, ?, ?, ?)",
                [name, *row, _sqlearn_version(), _utc_now()],
            )
        except BaseException:
            self._con.execute(f"DROP TABLE IF EXISTS {table}")
            raise
        return table

    def clear(self) -> None:
        """Drop every kept table and every index row.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> with KeptFolds(path) as kept:
        ...     _ = kept.put("fold_0_x", "SELECT 1 AS a", ("d", "s", "f", 0))
        ...     kept.clear()
        ...     kept.tables()
        []
        """
        for name in self.tables():
            self._con.execute(f"DROP TABLE IF EXISTS {self.qualified(name)}")
        self._con.execute(f"DELETE FROM {self.qualified(INDEX)}")

    def close(self) -> None:
        """Detach the file, if it was attached on opening.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> from sqlearn.model_selection.kept import KeptFolds
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
        >>> KeptFolds(path).close()
        """
        if self._attached:
            self._attached = False
            self._con.execute(f"DETACH {quote(self.database)}")

    def __enter__(self) -> Self:
        """Return the kept folds, for a ``with`` block."""
        return self

    def __exit__(self, *_: object) -> None:
        """Detach the file on leaving the block."""
        self.close()


def prepared(path: str | os.PathLike[str]) -> duckdb.DuckDBPyRelation:
    """Return the index of a file's kept tables, copied out of the file.

    Parameters
    ----------
    path : str or os.PathLike
        The DuckDB file given as ``keep_prepared``.

    Returns
    -------
    duckdb.DuckDBPyRelation
        One row per kept table; no row when the file or its index is
        missing (the file is not made).

    Examples
    --------
    >>> import tempfile, pathlib
    >>> from sqlearn.model_selection.kept import prepared
    >>> prepared(pathlib.Path(tempfile.mkdtemp()) / "none.duckdb").columns[:2]
    ['table', 'data']
    """
    con = connection()
    name = f"_sqlearn_prepared_{uuid.uuid4().hex}"  # never one a live relation reads
    columns = ", ".join(f"{quote(c)} {t}" for c, t in _COLUMNS)
    con.execute(f"CREATE TEMP TABLE {quote(name)} ({columns})")
    rel = con.table(name)
    weakref.finalize(rel, _drop_later, con, quote(name))
    if os.path.exists(path):
        with KeptFolds(path, read_only=True) as kept:
            found = (
                con.sql("FROM duckdb_tables()")
                .filter(
                    (
                        duckdb.ColumnExpression("database_name")
                        == duckdb.ConstantExpression(kept.database)
                    )
                    & (
                        duckdb.ColumnExpression("schema_name")
                        == duckdb.ConstantExpression(SCHEMA)
                    )
                    & (
                        duckdb.ColumnExpression("table_name")
                        == duckdb.ConstantExpression(INDEX)
                    )
                )
                .count("*")
                .fetchall()[0][0]
            )
            if found:
                con.execute(f"INSERT INTO {quote(name)} FROM {kept.qualified(INDEX)}")
    return rel


def clear(path: str | os.PathLike[str]) -> None:
    """Drop a file's kept tables and their index rows; a missing file is left.

    Parameters
    ----------
    path : str or os.PathLike
        The DuckDB file given as ``keep_prepared``.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> from sqlearn.model_selection.kept import clear
    >>> clear(pathlib.Path(tempfile.mkdtemp()) / "none.duckdb")
    """
    if not os.path.exists(path):
        return
    with KeptFolds(path) as kept:
        kept.clear()
