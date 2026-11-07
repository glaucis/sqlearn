"""Folds: each row's fold number, from a hash of its values and a seed."""

import duckdb

from sqlearn._errors import SqlearnError
from sqlearn._expr import quote

__all__ = ["ALIAS", "KFold"]

ALIAS = "__sqlearn_row_values"
"""The alias naming the whole row inside the fold expression."""


class KFold:
    """Split the rows into `n` folds by a hash of each row and a seed.

    A row's fold is ``hash(row, seed) % n``: the same in every query, with
    no column stored, and identical rows fall in the same fold. Fold ``k``
    holds out the rows numbered ``k`` and learns from the others. Changing
    the seed deals the rows out again.

    Parameters
    ----------
    n : int, default 5
        The number of folds, at least 2.
    seed : int, default 0
        The seed mixed into the hash.

    Attributes
    ----------
    n : int
        The number of folds.
    seed : int
        The seed.

    Raises
    ------
    SqlearnError
        If `n` is below 2 or either setting is not an integer.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.folds.kfold(5, seed=0)
    KFold(n=5, seed=0)
    """

    def __init__(self, n: int = 5, seed: int = 0) -> None:
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            msg = (
                f"KFold got n={n!r}; a cross-validation needs at least 2 folds, "
                "as a whole number. Fix: pass n=5, say."
            )
            raise SqlearnError(msg)
        if isinstance(seed, bool) or not isinstance(seed, int):
            msg = (
                f"KFold got seed={seed!r}; the seed is mixed into a hash and "
                "must be a whole number. Fix: pass seed=0, say."
            )
            raise SqlearnError(msg)
        self.n = n
        self.seed = seed

    def __repr__(self) -> str:
        """Show the settings.

        Returns
        -------
        str
            ``KFold(n=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.folds.kfold(3, seed=1))
        'KFold(n=3, seed=1)'
        """
        return f"KFold(n={self.n}, seed={self.seed})"

    def __eq__(self, other: object) -> bool:
        """Compare by settings.

        Parameters
        ----------
        other : object
            The object compared.

        Returns
        -------
        bool
            True when `other` is a KFold with the same settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(3) == sq.folds.kfold(3, seed=0)
        True
        """
        if not isinstance(other, KFold):
            return NotImplemented
        return (self.n, self.seed) == (other.n, other.seed)

    def __hash__(self) -> int:
        """Hash the settings.

        Returns
        -------
        int
            The hash.

        Examples
        --------
        >>> import sqlearn as sq
        >>> hash(sq.folds.kfold()) == hash(sq.folds.kfold())
        True
        """
        return hash((self.n, self.seed))

    def expression(self, row_alias: str) -> str:
        """Return the SQL of a row's fold number.

        Parameters
        ----------
        row_alias : str
            The alias of the relation; in DuckDB it names the whole row.

        Returns
        -------
        str
            ``hash(<alias>, <seed>) % <n>``, the alias quoted.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(5, seed=0).expression("d")
        'hash("d", 0) % 5'
        """
        return f"hash({quote(row_alias)}, {self.seed}) % {self.n}"

    def _fold(
        self, rel: duckdb.DuckDBPyRelation
    ) -> tuple[duckdb.DuckDBPyRelation, duckdb.Expression]:
        if any(c.lower() == ALIAS for c in rel.columns):
            msg = (
                f"the data has a column named {ALIAS!r}, a name sqlearn keeps "
                "for the whole row when it deals rows into folds. Fix: rename "
                "that column."
            )
            raise SqlearnError(msg)
        return rel.set_alias(ALIAS), duckdb.SQLExpression(self.expression(ALIAS))

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with its fold number as one more column.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the fold column.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The data's columns, then `name`.

        Raises
        ------
        SqlearnError
            If the data has a column named as the row alias, `ALIAS`.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT 1 AS a")
        >>> sq.folds.kfold().numbered(rel, "fold").columns
        ['a', 'fold']
        """
        aliased, fold = self._fold(rel)
        return aliased.project(duckdb.StarExpression(), fold.alias(name))

    def rows(
        self, rel: duckdb.DuckDBPyRelation, k: int, *, held: bool
    ) -> duckdb.DuckDBPyRelation:
        """Return the rows fold `k` holds out, or the rows it learns from.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        k : int
            The fold, from 0 to ``n - 1``.
        held : bool
            True for the held-out rows, False for the training rows.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The rows, with the data's columns.

        Raises
        ------
        SqlearnError
            If the data has a column named as the row alias, `ALIAS`.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT range AS i FROM range(10)")
        >>> kfold = sq.folds.kfold()
        >>> rows = kfold.rows(rel, 0, held=True).count("*").fetchall()[0][0]
        >>> rows + kfold.rows(rel, 0, held=False).count("*").fetchall()[0][0]
        10
        """
        aliased, fold = self._fold(rel)
        k_value = duckdb.ConstantExpression(k)
        kept = aliased.filter(fold == k_value if held else fold != k_value)
        return kept.project(*(duckdb.ColumnExpression(c) for c in rel.columns))
