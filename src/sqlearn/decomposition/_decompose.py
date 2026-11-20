"""Decompose: project the columns on fewer, ``sq.decompose`` and its shortcut."""

from collections.abc import Sequence
from typing import cast

from sqlearn._errors import SqlearnError
from sqlearn._group import Group, columns_arg
from sqlearn._selectors import Selector, _numeric
from sqlearn.decomposition.pca import PCA

__all__ = ["DecomposeGroup", "decompose"]

_METHODS = ("pca",)


def _is_names(value: object) -> bool:
    """Return whether `value` is a column name, or a list or tuple of names."""
    if isinstance(value, list | tuple):
        return all(isinstance(v, str) for v in value)
    return isinstance(value, str)


def _refuse_positionals(names: tuple[object, ...], method: str) -> None:
    """Refuse a positional that is not a column name or a list of names.

    A setting given by position (``sq.decompose.pca(3)``) would be taken as
    a column, and fail only at learn; it is refused at the call. A dict
    passes, for `columns_arg` to refuse in its own words.
    """
    for value in names:
        if isinstance(value, dict) or _is_names(value):
            continue
        number = isinstance(value, int | float) and not isinstance(value, bool)
        shown = repr(value) if number else "..."
        msg = (
            f"sq.decompose.{method} got {value!r} as a positional. Why: a "
            "positional is a column name, or one list of names, so a setting "
            "there is not a setting. Fix: give a setting by name, as "
            f"n_components={shown}, and each column by its name."
        )
        raise SqlearnError(msg)


class DecomposeGroup(Group):
    """Decompose columns: ``sq.decompose.pca(...)``.

    Called, it is the general form: `method` picks the decomposition, and
    ``pca`` is the only one. The shortcut builds exactly the step the
    general form builds with its method: a dynamic step that replaces its
    columns by their projection on the components it learned. It takes the
    numeric columns by default.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.decompose.pca(n_components=3)
    sq.decompose.pca(n_components=3)
    >>> sq.decompose.pca("a", "b", whiten=True)
    sq.decompose.pca(whiten=True, cols=['a', 'b'])
    >>> sq.decompose(method="pca", n_components=0.95)
    sq.decompose.pca(n_components=0.95)
    """

    def __call__(
        self,
        *names: object,
        method: str = "pca",
        n_components: float | None = None,
        whiten: bool = False,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> PCA:
        """Build the decomposition of `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        method : {"pca"}, default "pca"
            The decomposition.
        n_components : int or float, optional
            How many components to keep (see `PCA`).
        whiten : bool, default False
            Whether to scale each output to unit variance (see `PCA`).
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        PCA
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, a
            positional is not a column name or a list of names, `method` is
            not a method, or a setting is out of range.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.decompose("a", "b", n_components=1)
        sq.decompose.pca(n_components=1, cols=['a', 'b'])
        """
        if method not in _METHODS:
            listed = ", ".join(repr(m) for m in _METHODS)
            msg = (
                f"sq.decompose got method={method!r}, which is not a method. "
                f"Why: the methods are {listed}. Fix: use one of them, or the "
                "shortcut sq.decompose.pca()."
            )
            raise SqlearnError(msg)
        _refuse_positionals(names, method)
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        picked = _numeric() if columns is None else columns
        return PCA(n_components=n_components, whiten=whiten, cols=picked)

    def pca(
        self,
        *names: object,
        n_components: float | None = None,
        whiten: bool = False,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> PCA:
        """Project the columns on their principal components.

        As scikit-learn's ``PCA``: it learns the components of the columns'
        covariance, largest first, and replaces the columns by the
        projections on the kept ones (see `PCA`).

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        n_components : int or float, optional
            How many components to keep: None for the smaller of the rows
            and the columns, a whole number from 0 up to that, or a
            fraction strictly between 0 and 1 of the variance to explain.
        whiten : bool, default False
            Whether to divide each output by the square root of its
            explained variance.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        PCA
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, a
            positional is not a column name, or `n_components` or `whiten`
            is not a setting.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.decompose.pca(cols=sq.cols("a", "b"), n_components=2)
        sq.decompose.pca(n_components=2, cols=cols('a', 'b'))
        """
        return self(
            *names, method="pca", n_components=n_components, whiten=whiten, cols=cols
        )


decompose = DecomposeGroup("decompose")
"""The decompositions: ``sq.decompose.pca(...)``."""
