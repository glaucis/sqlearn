"""Results handed over: a lazy relation by default, or what `out=` names."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from sqlearn._compose import copy_sql
from sqlearn._config import connection
from sqlearn._errors import SqlearnError

__all__ = ["Output", "out_csv", "out_json", "out_parquet", "to_output"]


@dataclass(frozen=True)
class Output:
    """Where a result goes when it is not handed back in memory: a file.

    Build one with `out_parquet`, `out_csv` or `out_json`. DuckDB writes the
    file itself (``COPY ... TO``), streaming, never through Python's memory.

    Attributes
    ----------
    path : str
        The file to write.
    format : str
        DuckDB's name for the file format: ``parquet``, ``csv`` or ``json``.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.out.parquet("prepared.parquet")
    Output(path='prepared.parquet', format='parquet')
    """

    path: str
    format: str

    def write(self, rel: duckdb.DuckDBPyRelation) -> str:
        """Write the rows of a relation to the file.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows to write.

        Returns
        -------
        str
            The path written.

        Examples
        --------
        >>> import tempfile
        >>> from pathlib import Path
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> path = Path(tempfile.mkdtemp()) / "one.csv"
        >>> sq.out.csv(path).write(connection().sql("SELECT 1 AS a")) == str(path)
        True
        """
        connection().execute(copy_sql(rel.sql_query(), self.path, self.format))
        return self.path


def out_parquet(path: str | Path) -> Output:
    """Write the result to a Parquet file.

    Parameters
    ----------
    path : str or pathlib.Path
        The file to write.

    Returns
    -------
    Output
        The output, to pass as ``out=``.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.out.parquet("prepared.parquet").format
    'parquet'
    """
    return Output(str(path), "parquet")


def out_csv(path: str | Path) -> Output:
    """Write the result to a CSV file, with a header row.

    Parameters
    ----------
    path : str or pathlib.Path
        The file to write.

    Returns
    -------
    Output
        The output, to pass as ``out=``.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.out.csv("prepared.csv").format
    'csv'
    """
    return Output(str(path), "csv")


def out_json(path: str | Path) -> Output:
    """Write the result to a JSON file, one object per line.

    Parameters
    ----------
    path : str or pathlib.Path
        The file to write.

    Returns
    -------
    Output
        The output, to pass as ``out=``.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.out.json("prepared.json").format
    'json'
    """
    return Output(str(path), "json")


def _library(name: str, module: str, take: Callable[[], object]) -> object:
    try:
        return take()
    except ModuleNotFoundError as exc:
        msg = (
            f"out={name!r} needs {module}, which is not installed. "
            f"Fix: install it (uv add {module}), or choose another output."
        )
        raise SqlearnError(msg) from exc


_NAMES = ("pandas", "polars", "numpy", "arrow")


def to_output(rel: duckdb.DuckDBPyRelation, out: str | Output | None) -> object:
    """Hand a result over in the form asked for.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The result, not yet run.
    out : {"pandas", "polars", "numpy", "arrow"} or Output or None
        None hands back `rel` itself; a name converts it (``"numpy"`` is a
        dict of column name to array); an `Output` writes it to a file.

    Returns
    -------
    object
        The relation, the converted result, or the path written.

    Raises
    ------
    SqlearnError
        If `out` is a name not listed, or names a library not installed.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._output import to_output
    >>> to_output(connection().sql("SELECT 1 AS a"), "numpy")["a"].tolist()
    [1]
    """
    if out is None:
        return rel
    if isinstance(out, Output):
        return out.write(rel)
    if out == "pandas":
        return _library(out, "pandas", rel.df)
    if out == "polars":
        return _library(out, "polars", rel.pl)
    if out == "numpy":
        return _library(out, "numpy", rel.fetchnumpy)
    if out == "arrow":
        return _library(out, "pyarrow", rel.to_arrow_table)
    names = ", ".join(repr(n) for n in _NAMES)
    msg = (
        f"out={out!r} is not an output kind. Pass one of {names}, an output "
        "such as sq.out.parquet(path), or None for a lazy relation."
    )
    raise SqlearnError(msg)
