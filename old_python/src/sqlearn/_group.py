"""What the groups share: how a group method reads its columns and prints."""

from collections.abc import Sequence

from sqlearn._errors import SqlearnError
from sqlearn._selectors import Selector

__all__ = [
    "Group",
    "Unset",
    "call_repr",
    "column_names",
    "columns_arg",
    "refuse_positionals",
]


class Unset(str):
    """A text setting's default, told apart from the same text given.

    It is the text itself, so the step reads it as given; only ``is`` tells
    it from a value passed, which lets a group refuse a setting given beside
    a dict that sets it per column.

    Examples
    --------
    >>> from sqlearn._group import Unset
    >>> median = Unset("median")
    >>> median == "median", median is "median"
    (True, False)
    """

    __slots__ = ()


def columns_arg(names: tuple[object, ...], cols: object, *, allow_dict: bool) -> object:
    """Read the columns a group method was given, by name or by ``cols=``.

    Parameters
    ----------
    names : tuple
        The positional arguments: column names, one list or tuple of names,
        or (when `allow_dict`) one dict.
    cols : object
        The ``cols=`` keyword: a selector, a name or a list of names.
    allow_dict : bool
        Whether a single dict (column name to setting) is accepted.

    Returns
    -------
    object
        None when nothing was given (the group's default); one name as a
        str; several as a list; a list or tuple as a list; a dict as itself.

    Raises
    ------
    SqlearnError
        When names and ``cols=`` are both given, or a dict is given where
        none is accepted.

    Examples
    --------
    >>> from sqlearn._group import columns_arg
    >>> columns_arg(("a", "b"), None, allow_dict=False)
    ['a', 'b']
    >>> columns_arg((), None, allow_dict=False) is None
    True
    """
    if not names:
        return cols
    if cols is not None:
        raise SqlearnError(
            f"got the columns {names!r} and also cols={cols!r}. "
            "Why: they say the same thing twice. "
            "Fix: give the columns one way, either by name or as cols=."
        )
    if len(names) > 1:
        return list(names)
    (one,) = names
    if isinstance(one, dict):
        if not allow_dict:
            raise SqlearnError(
                f"got a dict {one!r}, which this method does not take. "
                "Why: only methods with a setting per column read a dict. "
                "Fix: give column names, a list of names or cols=."
            )
        return one
    if isinstance(one, (list, tuple)):
        return list(one)
    return one


def _is_names(value: object) -> bool:
    """Return whether `value` is a column name, or a list or tuple of names."""
    if isinstance(value, list | tuple):
        return all(isinstance(v, str) for v in value)
    return isinstance(value, str)


def refuse_positionals(names: tuple[object, ...], call: str, setting: str) -> None:
    """Refuse a positional that is not a column name, a list of names or a selector.

    A setting given by position (``sq.select.percentile(20)``) would be
    taken as a column, and fail only at learn; it is refused at the call.
    A column selector (``sq.cols.numeric()``) passes, as the other groups
    take one by position; a dict passes, for `columns_arg` to refuse in its
    own words.

    Parameters
    ----------
    names : tuple of object
        The positionals the group method was given.
    call : str
        The method as the user wrote it, such as ``"sq.select.percentile"``.
    setting : str
        The setting the `Fix:` names, such as ``"percentile"``.

    Raises
    ------
    SqlearnError
        If a positional is not a column name, a list of names, a selector
        or a dict.

    Examples
    --------
    >>> from sqlearn._group import refuse_positionals
    >>> import sqlearn as sq
    >>> refuse_positionals(("a", ["b", "c"]), "sq.decompose.pca", "n_components")
    >>> refuse_positionals((sq.cols.numeric(),), "sq.decompose.pca", "n_components")
    >>> refuse_positionals((3,), "sq.decompose.pca", "n_components")
    Traceback (most recent call last):
    ...
    sqlearn.errors.SqlearnError: sq.decompose.pca got 3 as a positional. ...
    """
    for value in names:
        if isinstance(value, dict | Selector) or _is_names(value):
            continue
        number = isinstance(value, int | float) and not isinstance(value, bool)
        shown = repr(value) if number else "..."
        msg = (
            f"{call} got {value!r} as a positional. Why: a positional is a "
            "column name, one list of names or a column selector, so a "
            "setting there is not a "
            f"setting. Fix: give a setting by name, as {setting}={shown}, and "
            "each column by its name."
        )
        raise SqlearnError(msg)


def column_names(cols: object) -> list[str] | None:
    """Return `cols` as a list of names, or None when it is not names.

    A dict step compares its keys with any ``cols=`` it is given by this.

    Parameters
    ----------
    cols : object
        A name, a sequence of names, or anything else (such as a selector).

    Returns
    -------
    list of str or None
        The names, in order; None when `cols` is not a name or names.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._group import column_names
    >>> column_names("a"), column_names(("a", "b")), column_names(sq.cols.numeric())
    (['a'], ['a', 'b'], None)
    """
    if isinstance(cols, str):
        return [cols]
    if isinstance(cols, Sequence) and all(isinstance(c, str) for c in cols):
        return list(cols)
    return None


def call_repr(path: str, *args: object, **kwargs: object) -> str:
    """Write the call that builds a step, for its ``repr``.

    A step group's step prints as the shortest call that rebuilds it; the
    step picks which arguments to give, and this writes them.

    Parameters
    ----------
    path : str
        What is called, such as ``"sq.impute.median"``.
    *args : object
        The positional arguments, written by their ``repr``.
    **kwargs : object
        The keyword arguments, in order, written as ``name=repr``.

    Returns
    -------
    str
        The call, such as ``sq.impute.median(cols='age')``.

    Examples
    --------
    >>> from sqlearn._group import call_repr
    >>> call_repr("sq.impute.constant", 0, cols=["a"])
    "sq.impute.constant(0, cols=['a'])"
    """
    parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
    return f"{path}({', '.join(parts)})"


class Group:
    """Base of the step groups (``sq.scale``, ``sq.impute`` and so on).

    A group prints as ``sq.<name>`` and lists its shortcuts in ``dir()``.

    Parameters
    ----------
    name : str
        The group's name after ``sq.``.

    Examples
    --------
    >>> from sqlearn._group import Group
    >>> Group("scale")
    sq.scale
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"sq.{self._name}"

    def __dir__(self) -> list[str]:
        """List the group's shortcuts (its public methods)."""
        return sorted(
            n for n in set(dir(type(self))) | set(vars(self)) if not n.startswith("_")
        )
