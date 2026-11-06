"""Encode: turn categories into numbers, ``sq.encode`` and its shortcuts."""

from collections.abc import Sequence
from typing import TypedDict, Unpack, cast

from sqlearn._errors import SqlearnError
from sqlearn._group import Group, columns_arg
from sqlearn._selectors import Selector, _string
from sqlearn.preprocessing.onehot import OneHot
from sqlearn.preprocessing.ordinal import Ordinal
from sqlearn.preprocessing.target import TargetEncoder

__all__ = ["EncodeGroup", "encode"]

_METHODS = ("onehot", "ordinal", "target")
"""The encoding methods, each with a shortcut of its name."""


class _Settings(TypedDict, total=False):
    """The settings every shortcut takes."""

    cols: Selector | str | Sequence[str] | None
    keep: bool


class _TargetSettings(_Settings, total=False):
    """The settings of the target shortcut."""

    smooth: str | float
    cv: int
    seed: int
    target_type: str


class EncodeGroup(Group):
    """Encode categories: ``sq.encode(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` picks the encoder. Each shortcut
    is a method, and builds exactly the step the general form builds with it.
    The encoders take no ``suffix=``: the new columns are named after the
    categories (``onehot``) or replace the column (``ordinal``, ``target``).

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
        smooth: str | float | None = None,
        cv: int | None = None,
        seed: int | None = None,
        target_type: str | None = None,
    ) -> OneHot | Ordinal | TargetEncoder:
        """Build the step that encodes columns by `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the text columns.
        method : {"onehot", "ordinal", "target"}, default "onehot"
            The encoder.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the encoded ones.
        smooth, cv, seed, target_type : optional
            The settings of ``target`` (see `TargetEncoder`), only with it;
            its defaults when not given.

        Returns
        -------
        OneHot or Ordinal or TargetEncoder
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, `method` is
            not a method, or a setting of ``target`` is given with another.

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
        given = {
            k: v
            for k, v in {
                "smooth": smooth,
                "cv": cv,
                "seed": seed,
                "target_type": target_type,
            }.items()
            if v is not None
        }
        if given and method != "target":
            setting = next(iter(given))
            msg = (
                f"sq.encode got method={method!r} and {setting}="
                f"{given[setting]!r}. Why: {setting} is a setting of the "
                "target encoder alone. Fix: leave it out, or use "
                "method='target'."
            )
            raise SqlearnError(msg)
        columns = cast("str | list[str] | Selector | None", chosen)
        if method == "target":
            return TargetEncoder(
                cols=_string() if columns is None else columns,
                keep=keep,
                smooth="auto" if smooth is None else smooth,
                cv=5 if cv is None else cv,
                seed=0 if seed is None else seed,
                target_type="auto" if target_type is None else target_type,
            )
        step = OneHot if method == "onehot" else Ordinal
        if columns is None:
            return step(keep=keep)
        return step(cols=columns, keep=keep)

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

    def target(self, *names: object, **kw: Unpack[_TargetSettings]) -> TargetEncoder:
        """Replace each category by the target's mean in it, smoothed.

        As scikit-learn's ``TargetEncoder``, for a binary or a continuous
        target, cross-fitted in ``train`` (see `TargetEncoder`). It learns
        from the target: learn it with ``learn(data, target=...)``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the text columns.
        **kw : object
            The general form's other settings (``cols``, ``keep``,
            ``smooth``, ``cv``, ``seed``, ``target_type``).

        Returns
        -------
        TargetEncoder
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.target("plan", smooth=10.0)
        sq.encode.target(cols='plan', smooth=10.0)
        """
        return cast("TargetEncoder", self(*names, method="target", **kw))


encode = EncodeGroup("encode")
"""The encoding steps: ``sq.encode(...)``, ``sq.encode.onehot(...)`` and so on."""
