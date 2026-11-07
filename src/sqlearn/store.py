"""The store of learned values, shared by every pipeline in the process.

Beside it, the prepared folds a search keeps in a DuckDB file
(``keep_prepared``): `prepared` lists them and ``clear(prepared=path)``
removes them.
"""

import os

import duckdb

from sqlearn._store import STORE
from sqlearn.model_selection import kept

__all__ = ["clear", "prepared"]


def clear(prepared: str | os.PathLike[str] | None = None) -> None:
    """Forget every learned value, or remove a file's kept preparations.

    The store notices a changed file, frame or table by its name, size and
    modification time, but not a DuckDB table changed in place with the same
    row count. Clear the store after such a change.

    Parameters
    ----------
    prepared : str or os.PathLike, optional
        A DuckDB file given to a search as ``keep_prepared``. When given,
        every prepared fold kept there and its index rows are dropped (the
        in-process store is left as it is); do this after changing the code
        of a step of your own, which a kept preparation does not notice. A
        missing file is left missing.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> import sqlearn as sq
    >>> sq.store.clear()
    >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
    >>> sq.store.clear(prepared=path)
    """
    if prepared is not None:
        kept.clear(prepared)
        return
    STORE.clear()


def prepared(path: str | os.PathLike[str]) -> duckdb.DuckDBPyRelation:
    """List the prepared folds a search keeps in a DuckDB file.

    Parameters
    ----------
    path : str or os.PathLike
        The DuckDB file given to a search as ``keep_prepared``.

    Returns
    -------
    duckdb.DuckDBPyRelation
        One row per kept table: ``table`` (its name in the file's schema
        ``sqlearn_prepared``), ``data``, ``steps`` and ``folds`` (the key it
        was kept under, as text), ``fold``, ``sqlearn_version`` and
        ``created``. No row when the file is missing (it is not made). The
        rows are copied out, so the file is not left open.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> import sqlearn as sq
    >>> path = pathlib.Path(tempfile.mkdtemp()) / "kept.duckdb"
    >>> sq.store.prepared(path).count("*").fetchall()
    [(0,)]
    """
    return kept.prepared(path)
