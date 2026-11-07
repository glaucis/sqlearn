"""The search's names as groups: ``sq.search`` and ``sq.folds`` (ADR 0039)."""

from sqlearn._group import Group
from sqlearn._pipeline import Pipeline
from sqlearn.metrics import Metric, accuracy
from sqlearn.model_selection.folds import KFold
from sqlearn.model_selection.methods import Grid, Method, Params, Range, range
from sqlearn.model_selection.search import Search

__all__ = ["FoldsGroup", "SearchGroup", "folds", "search"]


class SearchGroup(Group):
    """Search over settings: ``sq.search(pipe, ...)`` and its shortcuts.

    Called, it builds a `Search`. The shortcuts build what a search takes:
    ``grid`` the method that tries every setting, ``range`` a span of numbers.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.search.grid().knows_all
    True
    >>> sq.search.range(0.01, 10, log=True)
    Range(low=0.01, high=10, log=True)
    """

    def __call__(
        self,
        pipe: Pipeline,
        params: Params | list[Params] | None = None,
        metric: Metric = accuracy,
        method: Method | None = None,
        folds: KFold | None = None,
    ) -> Search:
        """Build the search of a pipeline over settings.

        Parameters
        ----------
        pipe : Pipeline
            A pipeline ending in a model; never changed.
        params : dict or list of dict, optional
            Settings to try, keyed ``step__setting`` (see `Search`).
        metric : Metric, default sq.metrics.accuracy
            The score, computed in SQL on each fold's held-out rows.
        method : Method, optional
            How settings are picked; by default ``sq.search.grid()``.
        folds : KFold, optional
            The folds; by default ``sq.folds.kfold(5, seed=0)``.

        Returns
        -------
        Search
            The search, ready for ``train``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> pipe = sq.Pipeline([("model", LogisticRegression())])
        >>> search = sq.search(pipe, params={"model__C": [1.0]})
        >>> search.params
        {'model__C': [1.0]}
        """
        return Search(pipe, params, metric, method, folds)

    def grid(self) -> Grid:
        """Return the method that tries every setting of the grid.

        Returns
        -------
        Grid
            The grid method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().knows_all
        True
        """
        return Grid()

    def range(self, low: float, high: float, log: bool = False) -> Range:
        """Return a span of numbers to search, from `low` to `high`.

        Parameters
        ----------
        low : float
            The lowest value.
        high : float
            The highest value.
        log : bool, default False
            Whether values are drawn on a log scale.

        Returns
        -------
        Range
            The span.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.range(1, 5).high
        5
        """
        return range(low, high, log)


class FoldsGroup(Group):
    """The ways to cut data into folds: ``sq.folds.kfold(...)`` and others.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.folds.kfold(3, seed=1)
    KFold(n=3, seed=1)
    """

    def kfold(self, n: int = 5, seed: int = 0) -> KFold:
        """Deal rows into `n` folds by a hash of the row and `seed`.

        Parameters
        ----------
        n : int, default 5
            The number of folds, at least 2.
        seed : int, default 0
            Mixed into the hash.

        Returns
        -------
        KFold
            The fold scheme.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.folds.kfold(3, seed=1)
        KFold(n=3, seed=1)
        """
        return KFold(n, seed)


search = SearchGroup("search")
"""The search group (``sq.search``)."""

folds = FoldsGroup("folds")
"""The folds group (``sq.folds``)."""
