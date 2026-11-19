"""Select: keep the columns worth keeping, ``sq.select`` and its shortcuts."""

from collections.abc import Sequence
from typing import cast

from sqlearn._group import Group, columns_arg
from sqlearn._selectors import Selector, _numeric
from sqlearn.feature_selection.univariate import SelectKBest
from sqlearn.feature_selection.variance import VarianceThreshold

__all__ = ["SelectGroup", "select"]


class SelectGroup(Group):
    """Select columns: ``sq.select.variance(...)`` and the other selectors.

    Each shortcut is a method building a feature selector: a dynamic step
    that keeps some of its columns, unchanged, and drops the others, by what
    it learned. They choose among the numeric columns by default.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.select.variance(threshold=0.5)
    sq.select.variance(threshold=0.5)
    >>> sq.select.variance("a", "b")
    sq.select.variance(cols=['a', 'b'])
    >>> sq.select.best(k=5, score="chi2")
    sq.select.best(k=5, score='chi2')
    """

    def variance(
        self,
        *names: object,
        threshold: float = 0.0,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> VarianceThreshold:
        """Keep the columns whose variance is above `threshold`.

        As scikit-learn's ``VarianceThreshold``: at ``threshold=0`` it drops
        the constant columns (see `VarianceThreshold`).

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        threshold : float, default 0.0
            The variance a column must be above to be kept; from 0 up.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        VarianceThreshold
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, or
            `threshold` is negative or not a number.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select.variance(cols=sq.cols("a", "b"), threshold=0.1)
        sq.select.variance(threshold=0.1, cols=cols('a', 'b'))
        """
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        return VarianceThreshold(
            threshold=threshold, cols=_numeric() if columns is None else columns
        )

    def best(
        self,
        *names: object,
        k: int | str = 10,
        score: str = "f_classif",
        cols: Selector | str | Sequence[str] | None = None,
    ) -> SelectKBest:
        """Keep the `k` columns that score best against the target.

        As scikit-learn's ``SelectKBest``: each column is scored against the
        target by `score` and the `k` highest are kept (see `SelectKBest`).

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        k : int or "all", default 10
            How many columns to keep; from 0 up, or ``"all"``.
        score : str, default "f_classif"
            ``"f_classif"`` (classes), ``"f_regression"`` (a number) or
            ``"chi2"`` (classes, columns of counts or frequencies).
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        SelectKBest
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, `k` is not
            a whole number from 0 up or ``"all"``, or `score` is unknown.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select.best("a", "b", k=1, score="f_regression")
        sq.select.best(k=1, score='f_regression', cols=['a', 'b'])
        """
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        return SelectKBest(
            k=k, score=score, cols=_numeric() if columns is None else columns
        )


select = SelectGroup("select")
"""The feature selectors: ``sq.select.variance(...)`` and so on."""
