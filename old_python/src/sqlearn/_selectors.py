"""Column selectors: choose columns by name or by kind, and combine choices."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from duckdb.sqltypes import DuckDBPyType

__all__ = ["Schema", "Selector", "cols", "to_selector"]

Schema = list[tuple[str, DuckDBPyType]]
"""An ordered list of ``(name, type)`` pairs, as a relation reports them."""

_NUMERIC = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "FLOAT",
        "DOUBLE",
    }
)
_DECIMAL = re.compile(r"DECIMAL\(\d+,\s*\d+\)")


def _is_numeric(dtype: DuckDBPyType) -> bool:
    name = str(dtype)
    return name in _NUMERIC or _DECIMAL.fullmatch(name) is not None


def is_text(dtype: DuckDBPyType) -> bool:
    """Say whether a DuckDB type is text: the one definition of text.

    ``VARCHAR`` is text, with or without a collation (DuckDB reports the
    collated column's type as ``VARCHAR``: the collation lives on the
    expression), and so is any ``ENUM``. ``sq.cols.string()``, the hand-over
    to a model and the metrics' label check all use it.

    Parameters
    ----------
    dtype : DuckDBPyType
        A column's type, as ``rel.types`` gives it.

    Returns
    -------
    bool
        True for text.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._selectors import is_text
    >>> rel = connection().sql("SELECT 'a' AS t, 1 AS n, 'a'::ENUM('a') AS e")
    >>> [is_text(kind) for kind in rel.types]
    [True, False, True]
    """
    return dtype.id in {"varchar", "enum"}


class Selector:
    """A rule that chooses columns, resolved against a schema.

    Selectors combine with ``|`` (or), ``&`` (and), ``-`` (except) and ``~``
    (not), as in Polars. Two selectors with the same rule are equal and print
    the same way.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.cols.numeric() - sq.cols("id")
    (numeric() - cols('id'))
    """

    def resolve(self, schema: Schema) -> list[str]:
        """Return the names this selector chooses, in schema order.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns at this point in the pipeline, in order.

        Returns
        -------
        list of str
            The chosen names. A name given to `cols` but absent from the
            schema is left out.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import INTEGER, VARCHAR
        >>> sq.cols.numeric().resolve([("a", INTEGER), ("b", VARCHAR)])
        ['a']
        """
        return [name for name, dtype in schema if self._matches(name, dtype)]

    def may_match(self, dtype: DuckDBPyType) -> bool:
        """Say whether a column of this type could be chosen.

        Planning uses this for columns whose names are not yet known.

        Parameters
        ----------
        dtype : DuckDBPyType
            The type of the column.

        Returns
        -------
        bool
            False only when no column of this type can be chosen.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import VARCHAR
        >>> sq.cols.numeric().may_match(VARCHAR)
        False
        """
        return self._may(dtype)

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        raise NotImplementedError  # pragma: no cover

    def _may(self, dtype: DuckDBPyType) -> bool:
        raise NotImplementedError  # pragma: no cover

    def _must(self, dtype: DuckDBPyType) -> bool:
        raise NotImplementedError  # pragma: no cover

    def __or__(self, other: "Selector") -> "Selector":
        if not isinstance(other, Selector):
            return NotImplemented
        return _Or(self, other)

    def __and__(self, other: "Selector") -> "Selector":
        if not isinstance(other, Selector):
            return NotImplemented
        return _And(self, other)

    def __sub__(self, other: "Selector") -> "Selector":
        if not isinstance(other, Selector):
            return NotImplemented
        return _Sub(self, other)

    def __invert__(self) -> "Selector":
        return _Not(self)


@dataclass(frozen=True, repr=False)
class _Cols(Selector):
    names: tuple[str, ...]

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return name in self.names

    def _may(self, dtype: DuckDBPyType) -> bool:
        return True

    def _must(self, dtype: DuckDBPyType) -> bool:
        return False

    def __repr__(self) -> str:
        return f"cols({', '.join(repr(n) for n in self.names)})"


@dataclass(frozen=True, repr=False)
class _Kind(Selector):
    label: str

    def _test(self, dtype: DuckDBPyType) -> bool:
        return _is_numeric(dtype) if self.label == "numeric" else is_text(dtype)

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return self._test(dtype)

    def _may(self, dtype: DuckDBPyType) -> bool:
        return self._test(dtype)

    def _must(self, dtype: DuckDBPyType) -> bool:
        return self._test(dtype)

    def __repr__(self) -> str:
        return f"{self.label}()"


@dataclass(frozen=True, repr=False)
class _Or(Selector):
    left: Selector
    right: Selector

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return self.left._matches(name, dtype) or self.right._matches(name, dtype)

    def _may(self, dtype: DuckDBPyType) -> bool:
        return self.left._may(dtype) or self.right._may(dtype)

    def _must(self, dtype: DuckDBPyType) -> bool:
        return self.left._must(dtype) or self.right._must(dtype)

    def __repr__(self) -> str:
        return f"({self.left!r} | {self.right!r})"


@dataclass(frozen=True, repr=False)
class _And(Selector):
    left: Selector
    right: Selector

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return self.left._matches(name, dtype) and self.right._matches(name, dtype)

    def _may(self, dtype: DuckDBPyType) -> bool:
        return self.left._may(dtype) and self.right._may(dtype)

    def _must(self, dtype: DuckDBPyType) -> bool:
        return self.left._must(dtype) and self.right._must(dtype)

    def __repr__(self) -> str:
        return f"({self.left!r} & {self.right!r})"


@dataclass(frozen=True, repr=False)
class _Sub(Selector):
    left: Selector
    right: Selector

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return self.left._matches(name, dtype) and not self.right._matches(name, dtype)

    def _may(self, dtype: DuckDBPyType) -> bool:
        return self.left._may(dtype) and not self.right._must(dtype)

    def _must(self, dtype: DuckDBPyType) -> bool:
        return self.left._must(dtype) and not self.right._may(dtype)

    def __repr__(self) -> str:
        return f"({self.left!r} - {self.right!r})"


@dataclass(frozen=True, repr=False)
class _Not(Selector):
    inner: Selector

    def _matches(self, name: str, dtype: DuckDBPyType) -> bool:
        return not self.inner._matches(name, dtype)

    def _may(self, dtype: DuckDBPyType) -> bool:
        return not self.inner._must(dtype)

    def _must(self, dtype: DuckDBPyType) -> bool:
        return not self.inner._may(dtype)

    def __repr__(self) -> str:
        return f"(~{self.inner!r})"


class _ColsGroup:
    """Choose columns by name, or by kind with ``cols.numeric()``.

    Call it with names to choose those columns; its methods choose by kind.
    The result is a `Selector`, which combines with ``|``, ``&``, ``-`` and
    ``~``.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.cols("age", "income")
    cols('age', 'income')
    >>> sq.cols.numeric() - sq.cols("id")
    (numeric() - cols('id'))
    """

    def __call__(self, *names: str) -> Selector:
        """Choose columns by name.

        Parameters
        ----------
        *names : str
            The column names.

        Returns
        -------
        Selector
            A selector that chooses these columns when they exist.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.cols("age", "income")
        cols('age', 'income')
        """
        return _Cols(tuple(names))

    def numeric(self) -> Selector:
        """Choose every numeric column.

        Integers of any width (signed or unsigned), FLOAT, DOUBLE and DECIMAL
        of any precision count as numeric.

        Returns
        -------
        Selector
            The numeric-columns selector.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.cols.numeric()
        numeric()
        """
        return _Kind("numeric")

    def string(self) -> Selector:
        """Choose every text column: VARCHAR and ENUM.

        Returns
        -------
        Selector
            The text-columns selector.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.cols.string()
        string()
        """
        return _Kind("string")

    def __repr__(self) -> str:
        return "sq.cols"


cols = _ColsGroup()
"""The column chooser: ``sq.cols("a", "b")``, ``sq.cols.numeric()``."""


def _numeric() -> Selector:
    """Return the numeric-columns selector (what ``cols.numeric()`` gives)."""
    return _Kind("numeric")


def _string() -> Selector:
    """Return the text-columns selector (what ``cols.string()`` gives)."""
    return _Kind("string")


def to_selector(value: Selector | str | Sequence[str]) -> Selector:
    """Turn a selector, one name or a sequence of names into a selector.

    Parameters
    ----------
    value : Selector or str or sequence of str
        What the user passed as ``cols=``.

    Returns
    -------
    Selector
        `value` itself when it is a selector, otherwise `cols` of the names.

    Examples
    --------
    >>> from sqlearn._selectors import to_selector
    >>> to_selector(["a", "b"])
    cols('a', 'b')
    """
    if isinstance(value, Selector):
        return value
    if isinstance(value, str):
        return cols(value)
    return cols(*value)
