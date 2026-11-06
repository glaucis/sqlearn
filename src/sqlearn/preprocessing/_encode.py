"""Encode: turn categories into numbers, ``sq.encode`` and its shortcuts."""

from collections.abc import Sequence
from typing import TypedDict, Unpack, cast

from sqlearn._errors import SqlearnError
from sqlearn._group import Group, columns_arg
from sqlearn._selectors import Selector
from sqlearn.preprocessing.onehot import OneHot
from sqlearn.preprocessing.ordinal import Ordinal

__all__ = ["EncodeGroup", "encode"]

_METHODS = ("onehot", "ordinal")
"""The encoding methods, each with a shortcut of its name."""


class _Settings(TypedDict, total=False):
    """The settings every shortcut takes."""

    cols: Selector | str | Sequence[str] | None
    keep: bool


class EncodeGroup(Group):
    """Encode categories: ``sq.encode(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` picks the encoder. Each shortcut
    is a method, and builds exactly the step the general form builds with it.
    The encoders take no ``suffix=``: the new columns are named after the
    categories (``onehot``) or replace the column (``ordinal``).

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.encode.onehot("city")
    sq.encode.onehot(cols='city')
    >>> sq.encode("city", method="ordinal")
    sq.encode.ordinal(cols='city')
    """

    def __call__(
        self,
        *names: object,
        method: str = "onehot",
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
    ) -> OneHot | Ordinal:
        """Build the step that encodes columns by `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the text columns.
        method : {"onehot", "ordinal"}, default "onehot"
            The encoder.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the encoded ones.

        Returns
        -------
        OneHot or Ordinal
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, or `method`
            is not a method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode(cols=sq.cols("city", "plan"), method="onehot")
        sq.encode.onehot(cols=cols('city', 'plan'))
        """
        if method not in _METHODS:
            listed = ", ".join(repr(m) for m in _METHODS)
            msg = (
                f"sq.encode got method={method!r}, which is not a method. "
                f"Why: the methods are {listed}. Fix: use one of them, or a "
                "shortcut such as sq.encode.onehot()."
            )
            raise SqlearnError(msg)
        chosen = columns_arg(names, cols, allow_dict=False)
        step = OneHot if method == "onehot" else Ordinal
        if chosen is None:
            return step(keep=keep)
        return step(cols=cast("str | list[str] | Selector", chosen), keep=keep)

    def onehot(self, *names: object, **kw: Unpack[_Settings]) -> OneHot:
        """Make one 0/1 column per category (``method="onehot"``).

        As scikit-learn's ``OneHotEncoder(handle_unknown="ignore")``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the text columns.
        **kw : object
            The general form's other settings (``cols``, ``keep``).

        Returns
        -------
        OneHot
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.onehot(keep=True)
        sq.encode.onehot(keep=True)
        """
        return cast("OneHot", self(*names, method="onehot", **kw))

    def ordinal(self, *names: object, **kw: Unpack[_Settings]) -> Ordinal:
        """Replace each category by its position among the sorted ones.

        As scikit-learn's ``OrdinalEncoder(handle_unknown="use_encoded_value",
        unknown_value=-1)``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the text columns.
        **kw : object
            The general form's other settings (``cols``, ``keep``).

        Returns
        -------
        Ordinal
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.ordinal("size")
        sq.encode.ordinal(cols='size')
        """
        return cast("Ordinal", self(*names, method="ordinal", **kw))


encode = EncodeGroup("encode")
"""The encoding steps: ``sq.encode(...)``, ``sq.encode.onehot(...)`` and so on."""
