"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib import metadata as _metadata

from sqlearn import _native

# The start-up check, before anything imports duckdb: the engine is compiled
# into DuckDB's binary, and the official duckdb has none (ADR 0061).
try:
    import _duckdb
except ImportError as _exc:
    raise ImportError(_native.MISSING) from _exc

_native.load(_duckdb.__file__)

from sqlearn import errors

__all__ = ["__version__", "errors", "version"]

__version__: str = _metadata.version("sqlearn")


def version() -> str:
    """Return what this sqlearn was built as, in one line.

    The engine answers it: sqlearn's version, DuckDB's version and commit,
    the C++ compiler and the build type. ``SELECT sqlearn_version()`` gives
    the same line in any DuckDB database.

    Returns
    -------
    str
        ``sqlearn <version>, DuckDB <version> (<commit>), <compiler>,
        <build type>``, the commit cut to its first ten digits.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.version()  # doctest: +ELLIPSIS
    'sqlearn ..., DuckDB ... (...), ...'
    """
    return _native.describe()
