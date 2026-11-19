"""Select: keep the columns worth keeping, ``sq.select`` and its shortcuts."""

from collections.abc import Sequence
from typing import cast

from sqlearn._errors import SqlearnError
from sqlearn._group import Group, columns_arg
from sqlearn._selectors import Selector, _numeric
from sqlearn.feature_selection.univariate import SelectKBest, SelectPercentile
from sqlearn.feature_selection.variance import VarianceThreshold

__all__ = ["SelectGroup", "select"]

_METHODS = ("variance", "best", "percentile")
_OWN = {
    "threshold": "variance",
    "k": "best",
    "percentile": "percentile",
}


class SelectGroup(Group):
    """Select columns: ``sq.select.variance(...)`` and the other feature selectors.

    Called, it is the general form: `method` picks the feature selector. Each
    shortcut is a method building a feature selector: a dynamic step that
    keeps some of its columns, unchanged, and drops the others, by what it
    learned, and it builds exactly the step the general form builds with its
    method. They choose among the numeric columns by default.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.select.variance(threshold=0.5)
    sq.select.variance(threshold=0.5)
    >>> sq.select.variance("a", "b")
    sq.select.variance(cols=['a', 'b'])
    >>> sq.select.best(k=5, score="chi2")
    sq.select.best(k=5, score='chi2')
    >>> sq.select(method="percentile", percentile=20)
    sq.select.percentile(percentile=20)
    """

    def __call__(
        self,
        *names: object,
        method: str = "variance",
        threshold: float | None = None,
        k: int | str | None = None,
        percentile: float | None = None,
        score: str | None = None,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> VarianceThreshold | SelectKBest | SelectPercentile:
        """Build the feature selector of `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        method : {"variance", "best", "percentile"}, default "variance"
            The feature selector.
        threshold : float, optional
            The setting of ``variance`` alone; its default when not given.
        k : int or "all", optional
            The setting of ``best`` alone; its default when not given.
        percentile : float, optional
            The setting of ``percentile`` alone; its default when not given.
        score : str, optional
            The score of ``best`` and ``percentile``; their default when
            not given.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        VarianceThreshold or SelectKBest or SelectPercentile
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, `method` is
            not a method, or a setting is given that does not belong to it.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select("a", "b", method="best", k=2)
        sq.select.best(k=2, cols=['a', 'b'])
        """
        if method not in _METHODS:
            listed = ", ".join(repr(m) for m in _METHODS)
            msg = (
                f"sq.select got method={method!r}, which is not a method. "
                f"Why: the methods are {listed}. Fix: use one of them, or a "
                "shortcut such as sq.select.variance()."
            )
            raise SqlearnError(msg)
        given = {"threshold": threshold, "k": k, "percentile": percentile}
        given["score"] = score
        for setting, value in given.items():
            if value is None:
                continue
            owners = [_OWN[setting]] if setting in _OWN else ["best", "percentile"]
            if method not in owners:
                msg = (
                    f"sq.select got method={method!r} and {setting}={value!r}. "
                    f"Why: {setting} is a setting of "
                    f"{' and '.join(repr(o) for o in owners)} alone. Fix: "
                    f"leave it out, or use method={owners[0]!r}."
                )
                raise SqlearnError(msg)
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        picked = _numeric() if columns is None else columns
        if method == "variance":
            return VarianceThreshold(
                threshold=0.0 if threshold is None else threshold, cols=picked
            )
        kept = "f_classif" if score is None else score
        if method == "best":
            return SelectKBest(k=10 if k is None else k, score=kept, cols=picked)
        return SelectPercentile(
            percentile=10 if percentile is None else percentile,
            score=kept,
            cols=picked,
        )

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
        return cast(
            "VarianceThreshold",
            self(*names, method="variance", threshold=threshold, cols=cols),
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
        return cast(
            "SelectKBest",
            self(*names, method="best", k=k, score=score, cols=cols),
        )

    def percentile(
        self,
        *names: object,
        percentile: float = 10,
        score: str = "f_classif",
        cols: Selector | str | Sequence[str] | None = None,
    ) -> SelectPercentile:
        """Keep the top `percentile` per cent of the columns by score.

        As scikit-learn's ``SelectPercentile``: each column is scored against
        the target by `score` and the best `percentile` per cent are kept
        (see `SelectPercentile`).

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        percentile : float, default 10
            The share of columns to keep, from 0 to 100.
        score : str, default "f_classif"
            ``"f_classif"`` (classes), ``"f_regression"`` (a number) or
            ``"chi2"`` (classes, columns of counts or frequencies).
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        SelectPercentile
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given,
            `percentile` is not a number from 0 to 100, or `score` is
            unknown.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select.percentile("a", "b", percentile=50)
        sq.select.percentile(percentile=50, cols=['a', 'b'])
        """
        return cast(
            "SelectPercentile",
            self(
                *names,
                method="percentile",
                percentile=percentile,
                score=score,
                cols=cols,
            ),
        )


select = SelectGroup("select")
"""The feature selectors: ``sq.select.variance(...)`` and so on."""
