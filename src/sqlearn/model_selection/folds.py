"""Folds: each row's fold number, from a hash of its values and a seed."""

from typing import Protocol, runtime_checkable

import duckdb

from sqlearn._errors import SqlearnError
from sqlearn._expr import quote

__all__ = [
    "ALIAS",
    "Folds",
    "Grouped",
    "Holdout",
    "KFold",
    "Stratified",
    "TimeSplit",
]

ALIAS = "__sqlearn_row_values"
"""The alias naming the whole row inside the fold expression."""


@runtime_checkable
class Folds(Protocol):
    """A fold scheme: SQL over the rows that says which rows each fold holds out.

    A search takes any object with these members (ADR 0040). The scheme
    numbers the rows in one query, and each fold is two predicates over the
    numbered relation, so nothing is held in Python memory.

    Attributes
    ----------
    splits : int
        How many folds are scored.
    key : tuple
        The scheme's settings, stable across processes, for the learning
        store's keys (for example ``("kfold", 5, 0)``).

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn.model_selection import Folds
    >>> isinstance(sq.folds.kfold(), Folds)
    True
    """

    @property
    def splits(self) -> int:
        """How many folds are scored.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(3).splits
        3
        """
        ...

    @property
    def key(self) -> tuple[object, ...]:
        """The settings, stable across processes.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(3, seed=1).key
        ('kfold', 3, 1)
        """
        ...

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row, plus `name` and helper columns named from `name`.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows to deal into folds.
        name : str
            The column for each row's fold number; helper columns, if any,
            are named with it as prefix.
        target : str or None
            The target column, for a scheme that deals by it (stratified).

        Returns
        -------
        duckdb.DuckDBPyRelation
            Every row of `rel`, with `name` (and any helper columns) added.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> rel = connection().sql("SELECT range AS x FROM range(10)")
        >>> sq.folds.kfold(2).numbered(rel, "f", None).columns
        ['x', 'f']
        """
        ...

    def training(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate true for the rows fold `k` learns from.

        Parameters
        ----------
        name : str
            The fold column `numbered` added.
        k : int
            The fold, from 0 to ``splits - 1``.

        Returns
        -------
        duckdb.Expression
            The predicate over the numbered relation.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> scheme = sq.folds.kfold(2)
        >>> rows = scheme.numbered(
        ...     connection().sql("SELECT range AS x FROM range(10)"), "f", None
        ... )
        >>> rows.filter(scheme.training("f", 0)).count("*").fetchall()
        [(4,)]
        """
        ...

    def held(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate true for the rows fold `k` holds out.

        Parameters
        ----------
        name : str
            The fold column `numbered` added.
        k : int
            The fold, from 0 to ``splits - 1``.

        Returns
        -------
        duckdb.Expression
            The predicate over the numbered relation.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> scheme = sq.folds.kfold(2)
        >>> rows = scheme.numbered(
        ...     connection().sql("SELECT range AS x FROM range(10)"), "f", None
        ... )
        >>> rows.filter(scheme.held("f", 0)).count("*").fetchall()
        [(6,)]
        """
        ...


def _whole_row(rel: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    """Return `rel` aliased so ``ALIAS`` names the whole row."""
    if any(c.lower() == ALIAS for c in rel.columns):
        msg = (
            f"the data has a column named {ALIAS!r}, a name sqlearn keeps "
            "for the whole row when it deals rows into folds. Fix: rename "
            "that column."
        )
        raise SqlearnError(msg)
    return rel.set_alias(ALIAS)


def _whole_number(scheme: str, setting: str, value: object, example: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = (
            f"{scheme} got {setting}={value!r}; it must be a whole number. "
            f"Fix: pass {setting}={example}, say."
        )
        raise SqlearnError(msg)


def _check_by(scheme: str, by: object, holds: str, example: str) -> None:
    """Refuse a `by` that is not a column name, as text."""
    if not isinstance(by, str):
        msg = (
            f"{scheme} got by={by!r}; it names the column that {holds}, as "
            f"text. Fix: pass by={example!r}, say."
        )
        raise SqlearnError(msg)


def _check_folds(scheme: str, n: object, seed: object) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        msg = (
            f"{scheme} got n={n!r}; a cross-validation needs at least 2 folds, "
            "as a whole number. Fix: pass n=5, say."
        )
        raise SqlearnError(msg)
    _whole_number(scheme, "seed", seed, "0")


class _Scheme:
    """What the schemes below share: the predicates, equality and hashing."""

    n: int

    @property
    def splits(self) -> int:
        """How many folds are scored."""
        return self.n

    @property
    def key(self) -> tuple[object, ...]:
        """The settings, stable across processes."""
        raise NotImplementedError

    def training(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate for the rows fold `k` learns from."""
        return duckdb.ColumnExpression(name) != duckdb.ConstantExpression(k)

    def held(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate for the rows fold `k` holds out."""
        return duckdb.ColumnExpression(name) == duckdb.ConstantExpression(k)

    def __eq__(self, other: object) -> bool:
        """Compare by kind and settings."""
        if type(other) is not type(self):
            return NotImplemented
        return self.key == getattr(other, "key", None)

    def __hash__(self) -> int:
        """Hash the settings."""
        return hash(self.key)


class KFold(_Scheme):
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
        _check_folds("KFold", n, seed)
        self.n = n
        self.seed = seed

    @property
    def key(self) -> tuple[object, ...]:
        """The settings as ``("kfold", n, seed)``.

        Returns
        -------
        tuple
            The scheme's name and settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(3, seed=1).key
        ('kfold', 3, 1)
        """
        return ("kfold", self.n, self.seed)

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
        return _whole_row(rel), duckdb.SQLExpression(self.expression(ALIAS))

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None = None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with its fold number as one more column.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the fold column.
        target : str, optional
            The target column; unused, a k-fold deals rows by value alone.

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


class Stratified(_Scheme):
    """Split into `n` folds that each keep the target's class shares.

    Rows are ordered by target, then by ``hash(row, seed)``, and dealt out
    in turn along that order, as scikit-learn's ``StratifiedKFold`` spreads
    each class. The dealing goes by ``dense_rank``, so identical rows share a
    rank and a fold, as with the other schemes that deal by value, and are
    never both trained on and scored. Each class is a run of the order, and
    the dealing carries on from one class to the next: without repeated rows
    every fold holds its share of each class to within one row and the fold
    sizes stay within one row of each other; repeated rows move together, so
    the sizes vary with how many times rows repeat.

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
    >>> sq.folds.stratified(5, seed=0)
    Stratified(n=5, seed=0)
    """

    def __init__(self, n: int = 5, seed: int = 0) -> None:
        _check_folds("Stratified", n, seed)
        self.n = n
        self.seed = seed

    @property
    def key(self) -> tuple[object, ...]:
        """The settings as ``("stratified", n, seed)``.

        Returns
        -------
        tuple
            The scheme's name and settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.stratified(3, seed=1).key
        ('stratified', 3, 1)
        """
        return ("stratified", self.n, self.seed)

    def __repr__(self) -> str:
        """Show the settings.

        Returns
        -------
        str
            ``Stratified(n=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.folds.stratified(3, seed=1))
        'Stratified(n=3, seed=1)'
        """
        return f"Stratified(n={self.n}, seed={self.seed})"

    def expression(self, row_alias: str, target: str) -> str:
        """Return the SQL of a row's fold number.

        Parameters
        ----------
        row_alias : str
            The alias of the relation; in DuckDB it names the whole row.
        target : str
            The target column whose classes are spread.

        Returns
        -------
        str
            The row's dense rank in the order by target then hash, less
            one, modulo `n`: identical rows share it.

        Examples
        --------
        >>> import sqlearn as sq
        >>> print(sq.folds.stratified(2).expression("d", "y"))
        (dense_rank() OVER (ORDER BY "y", hash("d", 0)) - 1) % 2
        """
        return (
            f"(dense_rank() OVER (ORDER BY {quote(target)}, "
            f"hash({quote(row_alias)}, {self.seed})) - 1) % {self.n}"
        )

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None = None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with its fold number as one more column.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the fold column.
        target : str, optional
            The target column; required.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The data's columns, then `name`.

        Raises
        ------
        SqlearnError
            If there is no target, the target is not a column of the data, or
            the data has a column named as the row alias, `ALIAS`.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT range AS i, range % 2 AS y FROM range(10)")
        >>> sq.folds.stratified(2).numbered(rel, "fold", "y").columns
        ['i', 'y', 'fold']
        """
        if target is None:
            msg = (
                "Stratified folds keep each class's share, so they need the "
                "target. Fix: pass target= to train or to the search."
            )
            raise SqlearnError(msg)
        if target not in rel.columns:
            msg = (
                f"Stratified folds got target={target!r}, which is not a "
                f"column of the data (columns: {list(rel.columns)}). Fix: "
                "name one of them."
            )
            raise SqlearnError(msg)
        fold = duckdb.SQLExpression(self.expression(ALIAS, target))
        return _whole_row(rel).project(duckdb.StarExpression(), fold.alias(name))


class Grouped(_Scheme):
    """Split into `n` folds so that every group falls wholly in one fold.

    A row's fold is ``hash(by, seed) % n``, so rows sharing a value of `by`
    (a customer, a patient) are never split between learning and scoring.

    Parameters
    ----------
    by : str
        The column naming each row's group.
    n : int, default 5
        The number of folds, at least 2.
    seed : int, default 0
        The seed mixed into the hash.

    Attributes
    ----------
    by : str
        The group column.
    n : int
        The number of folds.
    seed : int
        The seed.

    Raises
    ------
    SqlearnError
        If `by` is not a string, `n` is below 2 or a setting is not an integer.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.folds.group("customer", 5)
    Grouped(by='customer', n=5, seed=0)
    """

    def __init__(self, by: str, n: int = 5, seed: int = 0) -> None:
        _check_by("Grouped", by, "holds each row's group", "customer")
        _check_folds("Grouped", n, seed)
        self.by = by
        self.n = n
        self.seed = seed

    @property
    def key(self) -> tuple[object, ...]:
        """The settings as ``("group", by, n, seed)``.

        Returns
        -------
        tuple
            The scheme's name and settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.group("g", 3, seed=1).key
        ('group', 'g', 3, 1)
        """
        return ("group", self.by, self.n, self.seed)

    def __repr__(self) -> str:
        """Show the settings.

        Returns
        -------
        str
            ``Grouped(by=..., n=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.folds.group("g", 3, seed=1))
        "Grouped(by='g', n=3, seed=1)"
        """
        return f"Grouped(by={self.by!r}, n={self.n}, seed={self.seed})"

    def expression(self) -> str:
        """Return the SQL of a row's fold number.

        Returns
        -------
        str
            ``hash(<by>, <seed>) % <n>``, the column quoted.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.group("g", 4, seed=2).expression()
        'hash("g", 2) % 4'
        """
        return f"hash({quote(self.by)}, {self.seed}) % {self.n}"

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None = None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with its fold number as one more column.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the fold column.
        target : str, optional
            The target column; unused.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The data's columns, then `name`.

        Raises
        ------
        SqlearnError
            If the data has no column `by`.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT range AS i, range // 3 AS g FROM range(9)")
        >>> sq.folds.group("g").numbered(rel, "fold").columns
        ['i', 'g', 'fold']
        """
        if self.by not in rel.columns:
            msg = (
                f"Grouped folds got by={self.by!r}, which is not a column of "
                f"the data (columns: {list(rel.columns)}). Fix: name one of "
                "them."
            )
            raise SqlearnError(msg)
        fold = duckdb.SQLExpression(self.expression())
        return rel.project(duckdb.StarExpression(), fold.alias(name))


class Holdout(_Scheme):
    """One split: a share of the rows held out, the rest learned from.

    A row is held out when ``hash(row, seed) / 2^64 < test``; the share is
    about `test`, not exact. ``splits`` is 1, and fold 0 is the split.

    Parameters
    ----------
    test : float, default 0.2
        The share of rows held out, above 0 and below 1.
    seed : int, default 0
        The seed mixed into the hash.

    Attributes
    ----------
    test : float
        The share held out.
    seed : int
        The seed.

    Raises
    ------
    SqlearnError
        If `test` is not strictly between 0 and 1 or `seed` is not an integer.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.folds.holdout(test=0.25)
    Holdout(test=0.25, seed=0)
    """

    n = 1

    def __init__(self, test: float = 0.2, seed: int = 0) -> None:
        if (
            isinstance(test, bool)
            or not isinstance(test, (int, float))
            or not 0 < test < 1
        ):
            msg = (
                f"Holdout got test={test!r}; the share of rows held out must "
                "be above 0 and below 1. Fix: pass test=0.2, say."
            )
            raise SqlearnError(msg)
        _whole_number("Holdout", "seed", seed, "0")
        self.test = test
        self.seed = seed

    @property
    def key(self) -> tuple[object, ...]:
        """The settings as ``("holdout", test, seed)``.

        Returns
        -------
        tuple
            The scheme's name and settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.holdout(0.5, seed=1).key
        ('holdout', 0.5, 1)
        """
        return ("holdout", self.test, self.seed)

    def __repr__(self) -> str:
        """Show the settings.

        Returns
        -------
        str
            ``Holdout(test=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.folds.holdout(0.5, seed=1))
        'Holdout(test=0.5, seed=1)'
        """
        return f"Holdout(test={self.test}, seed={self.seed})"

    def expression(self, row_alias: str) -> str:
        """Return the SQL of a row's fold number, 0 when held out, else 1.

        Parameters
        ----------
        row_alias : str
            The alias of the relation; in DuckDB it names the whole row.

        Returns
        -------
        str
            A CASE on ``hash(<alias>, <seed>) / 2^64 < <test>``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> print(sq.folds.holdout(0.5).expression("d"))
        CASE WHEN hash("d", 0) / 18446744073709551616.0 < 0.5 THEN 0 ELSE 1 END
        """
        return (
            f"CASE WHEN hash({quote(row_alias)}, {self.seed}) "
            f"/ 18446744073709551616.0 < {self.test!r} THEN 0 ELSE 1 END"
        )

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None = None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with 0 (held out) or 1 (learned from) as a column.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the fold column.
        target : str, optional
            The target column; unused.

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
        >>> rel = duckdb.sql("SELECT range AS i FROM range(10)")
        >>> sq.folds.holdout().numbered(rel, "fold").columns
        ['i', 'fold']
        """
        fold = duckdb.SQLExpression(self.expression(ALIAS))
        return _whole_row(rel).project(duckdb.StarExpression(), fold.alias(name))

    def rows(
        self, rel: duckdb.DuckDBPyRelation, k: int = 0, *, held: bool
    ) -> duckdb.DuckDBPyRelation:
        """Return the rows the split holds out, or the rows it learns from.

        As `KFold.rows`, for the one split: `k` is 0, the default, so code
        written for a k-fold's ``rows(rel, k, held=...)`` works unchanged.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        k : int, default 0
            The fold; a holdout has only fold 0.
        held : bool
            True for the held-out rows, False for the training rows.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The rows, with the data's columns.

        Raises
        ------
        SqlearnError
            If `k` is not 0, or the data has a column named as the row
            alias, `ALIAS`.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT range AS i FROM range(10)")
        >>> split = sq.folds.holdout(test=0.3)
        >>> rows = split.rows(rel, held=True).count("*").fetchall()[0][0]
        >>> rows + split.rows(rel, held=False).count("*").fetchall()[0][0]
        10
        """
        if type(k) is not int or k != 0:
            msg = (
                f"a holdout has only fold 0 (the split), so k={k!r} names no "
                "fold. Fix: leave k out, or pass k=0."
            )
            raise SqlearnError(msg)
        aliased = _whole_row(rel)
        fold = duckdb.SQLExpression(self.expression(ALIAS))
        zero = duckdb.ConstantExpression(0)
        kept = aliased.filter(fold == zero if held else fold != zero)
        return kept.project(*(duckdb.ColumnExpression(c) for c in rel.columns))


class TimeSplit(_Scheme):
    """Hold out each later period of `by` and learn from everything before it.

    The rows, ordered by `by`, are cut into ``n + 1`` chunks of equal row
    counts, as scikit-learn's ``TimeSeriesSplit`` does. Fold ``k`` holds out
    chunk ``k + 1`` and learns from the rows before it, less the `gap` rows
    nearest it, so early folds learn from fewer rows. Rows sharing a value of
    `by` always fall on one side: a boundary moves to the end of its tie.

    Parameters
    ----------
    by : str
        The column that orders the rows; it may not be NULL in any row.
    n : int, default 5
        The number of folds, at least 2.
    gap : int, default 0
        Rows dropped between the learning rows and the held-out ones.

    Attributes
    ----------
    by : str
        The ordering column.
    n : int
        The number of folds.
    gap : int
        The number of rows dropped.

    Raises
    ------
    SqlearnError
        If `by` is not a string, `n` is below 2 or `gap` is not a whole
        number of at least 0.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.folds.time("day", 3, gap=1)
    TimeSplit(by='day', n=3, gap=1)
    """

    def __init__(self, by: str, n: int = 5, gap: int = 0) -> None:
        _check_by("TimeSplit", by, "orders the rows", "day")
        _check_folds("TimeSplit", n, 0)
        _whole_number("TimeSplit", "gap", gap, "0")
        if gap < 0:
            msg = (
                f"TimeSplit got gap={gap!r}; the rows dropped between learning "
                "and scoring cannot be negative. Fix: pass gap=0, say."
            )
            raise SqlearnError(msg)
        self.by = by
        self.n = n
        self.gap = gap

    @property
    def key(self) -> tuple[object, ...]:
        """The settings as ``("time", by, n, gap)``.

        Returns
        -------
        tuple
            The scheme's name and settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.time("t", 3).key
        ('time', 't', 3, 0)
        """
        return ("time", self.by, self.n, self.gap)

    def __repr__(self) -> str:
        """Show the settings.

        Returns
        -------
        str
            ``TimeSplit(by=..., n=..., gap=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.folds.time("t", 3))
        "TimeSplit(by='t', n=3, gap=0)"
        """
        return f"TimeSplit(by={self.by!r}, n={self.n}, gap={self.gap})"

    def numbered(
        self, rel: duckdb.DuckDBPyRelation, name: str, target: str | None = None
    ) -> duckdb.DuckDBPyRelation:
        """Return every row with its position in time, and the row count.

        The column `name` holds the position (from 0) of the last row of the
        row's tie on `by`; ``<name>_rows`` holds the number of rows.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The data.
        name : str
            The name of the position column; the row count column is named
            from it.
        target : str, optional
            The target column; unused.

        Returns
        -------
        duckdb.DuckDBPyRelation
            The data's columns, then `name` and ``<name>_rows``.

        Raises
        ------
        SqlearnError
            If the data has no column `by`, or `by` is NULL in some row.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT range AS t FROM range(6)")
        >>> sq.folds.time("t", 2).numbered(rel, "pos").columns
        ['t', 'pos', 'pos_rows']
        """
        if self.by not in rel.columns:
            msg = (
                f"TimeSplit got by={self.by!r}, which is not a column of the "
                f"data (columns: {list(rel.columns)}). Fix: name one of them."
            )
            raise SqlearnError(msg)
        column = duckdb.ColumnExpression(self.by)
        if rel.filter(column.isnull()).limit(1).fetchall():
            msg = (
                f"TimeSplit got a NULL in {self.by!r}, so those rows have no "
                "place in time. Fix: drop or fill the rows with a NULL in "
                f"{self.by!r} before the search."
            )
            raise SqlearnError(msg)
        by = quote(self.by)
        # Peers share a frame, so the count runs to the end of the tie.
        position = duckdb.SQLExpression(f"count(*) OVER (ORDER BY {by}) - 1")
        rows = duckdb.SQLExpression("count(*) OVER ()")
        return rel.project(
            duckdb.StarExpression(), position.alias(name), rows.alias(f"{name}_rows")
        )

    def _bound(self, name: str, back: int) -> duckdb.Expression:
        """Return the position ``back`` folds' sizes before the end."""
        size = f"({quote(name + '_rows')} // {self.n + 1})"
        return duckdb.SQLExpression(f"{quote(name + '_rows')} - {back} * {size}")

    def training(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate for the rows fold `k` learns from: those before it.

        Parameters
        ----------
        name : str
            The fold column `numbered` added: each row's position in time.
        k : int
            The fold, from 0 to ``n - 1``.

        Returns
        -------
        duckdb.Expression
            The predicate over the numbered relation.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> scheme = sq.folds.time("t", 2)
        >>> rows = scheme.numbered(
        ...     connection().sql("SELECT range AS t FROM range(6)"), "f", None
        ... )
        >>> sorted(
        ...     t
        ...     for (t,) in rows.filter(scheme.training("f", 1)).project("t").fetchall()
        ... )
        [0, 1, 2, 3]
        """
        edge = self._bound(name, self.n - k) - duckdb.ConstantExpression(self.gap)
        return duckdb.ColumnExpression(name) < edge

    def held(self, name: str, k: int) -> duckdb.Expression:
        """Return the predicate for the rows fold `k` holds out: its block in time.

        Parameters
        ----------
        name : str
            The fold column `numbered` added: each row's position in time.
        k : int
            The fold, from 0 to ``n - 1``.

        Returns
        -------
        duckdb.Expression
            The predicate over the numbered relation.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> scheme = sq.folds.time("t", 2)
        >>> rows = scheme.numbered(
        ...     connection().sql("SELECT range AS t FROM range(6)"), "f", None
        ... )
        >>> sorted(
        ...     t for (t,) in rows.filter(scheme.held("f", 1)).project("t").fetchall()
        ... )
        [4, 5]
        """
        position = duckdb.ColumnExpression(name)
        return (position >= self._bound(name, self.n - k)) & (
            position < self._bound(name, self.n - k - 1)
        )
