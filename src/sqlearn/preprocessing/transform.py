"""Transform: change each value by a function, ``sq.transform`` and its shortcuts.

None of these learns anything: each is static and chains into the stage
around it. A value outside a function's domain is refused when the rows are
fetched, not passed on as ``-inf`` or ``nan``. Any other transformation is
``sq.Step(apply=...)``; there is no ``sq.transform.custom``.
"""

import math
from collections.abc import Sequence
from typing import TypedDict, Unpack, cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn import fn
from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, is_missing
from sqlearn._group import Group, call_repr, columns_arg
from sqlearn._selectors import Schema, Selector, _string, to_selector
from sqlearn._step import Learned, Step
from sqlearn.preprocessing.scale import _numeric_inputs

__all__ = ["Transform", "TransformGroup", "transform"]

METHODS = ("log", "log1p", "sqrt", "clip", "lower", "upper")
"""The functions `Transform` applies."""

_TEXT = ("lower", "upper")

_WHY = {
    "log": "taking the logarithm needs numbers",
    "log1p": "taking the logarithm needs numbers",
    "sqrt": "taking the square root needs numbers",
    "clip": "clipping compares each value with numbers",
}


def _method(method: object) -> str:
    """Return `method` when it is a method's name, else refuse it."""
    if isinstance(method, str) and method in METHODS:
        return method
    names = ", ".join(repr(m) for m in METHODS)
    msg = (
        f"sq.transform got method={method!r}, which is not a method. Why: the "
        f"methods are {names}; there is no custom one. Fix: use one of them, "
        "or write your own transformation as sq.Step(apply=...)."
    )
    raise SqlearnError(msg)


def _bound(setting: str, value: object) -> float | None:
    """Return a clip bound when it is None or a finite number, else refuse it."""
    if value is None:
        return None
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return value
    msg = (
        f"sq.transform.clip got {setting}={value!r}, which is not a bound. Why: "
        "each value is compared with it, so it is a finite number. Fix: give "
        f"one, such as {setting}=0, or None for no bound on that side."
    )
    raise SqlearnError(msg)


def _refusal(method: str, name: str, found: str, fix: str) -> Expression:
    """Return ``error(...)``: a refusal DuckDB raises when the row is fetched."""
    msg = (
        f"sq.transform.{method} found {found} in column {name!r}. Why: "
        f"{_DOMAIN[method]}, as numpy's would give -inf or nan with a warning. "
        f"Fix: {fix}"
    )
    return duckdb.FunctionExpression("error", const(msg))


_DOMAIN = {
    "log": "the logarithm is defined only above 0",
    "log1p": "log1p is defined only above -1",
    "sqrt": "the square root is defined only from 0",
}


class Transform(Step):
    """Change each value of the chosen columns by one function.

    Build it with `sq.transform <TransformGroup>` or one of its shortcuts. It
    learns nothing: it is static and chains into the stage around it. NULL
    stays NULL. The methods:

    =======  =================================  ===============
    method   result                             numpy
    =======  =================================  ===============
    log      natural logarithm, DOUBLE          ``np.log``
    log1p    ``log(1 + x)``, DOUBLE, exact      ``np.log1p``
             for small ``x``
    sqrt     square root, DOUBLE                ``np.sqrt``
    clip     ``x`` held between the bounds      ``np.clip``
    lower    text in lower case                 ``str.lower``
    upper    text in upper case                 ``str.upper``
    =======  =================================  ===============

    ``log`` of a value at or below 0, ``log1p`` of one at or below -1 and
    ``sqrt`` of a negative one are refused when the rows are fetched, by a
    DuckDB error naming the step, the column and the fix (``clip`` first, or
    ``log1p``): numpy gives ``-inf`` or ``nan`` with a warning. NaN passes as
    numpy gives it, and so does infinity above the domain. ``clip`` keeps the
    column's type where numpy would: integer bounds on an integer column give
    integers, a float bound gives DOUBLE.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to change; by default the numeric ones, and for ``lower``
        and ``upper`` the text ones.
    method : {"log", "log1p", "sqrt", "clip", "lower", "upper"}
        The function. There is no default.
    lower : float, optional
        ``clip``'s lower bound; None for none. Only with ``clip``.
    upper : float, optional
        ``clip``'s upper bound; None for none. Only with ``clip``.
    keep : bool, default False
        Keep the input column and add the result beside it.
    suffix : str, optional
        Suffix of the result's column when `keep` is True; defaults to the
        step's name.

    Raises
    ------
    SqlearnError
        If `method` is not one, ``clip`` has no bound or its lower bound is
        above its upper, a bound is not a finite number, or a bound is given
        with another method.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [1.0, 4.0, 9.0]})
    >>> pipe = sq.Pipeline([sq.transform.sqrt()]).learn(data)
    >>> pipe.apply(data, out="pandas")["x"].tolist()
    [1.0, 2.0, 3.0]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        *,
        method: str,
        lower: float | None = None,
        upper: float | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        method = _method(method)
        if method == "clip":
            low, high = _bound("lower", lower), _bound("upper", upper)
            if low is None and high is None:
                msg = (
                    "sq.transform.clip got neither lower= nor upper=. Why: it "
                    "holds values between bounds, and numpy's clip needs one. "
                    "Fix: give at least one, such as lower=0."
                )
                raise SqlearnError(msg)
            if low is not None and high is not None and low > high:
                msg = (
                    f"sq.transform.clip got lower={low!r} above upper={high!r}. "
                    "Why: no value lies between them. Fix: give the lower "
                    "bound first, or equal to the upper."
                )
                raise SqlearnError(msg)
            lower, upper = low, high
        else:
            for setting, value in (("lower", lower), ("upper", upper)):
                if value is not None:
                    msg = (
                        f"sq.transform got method={method!r} and "
                        f"{setting}={value!r}. Why: only clip has bounds. "
                        f"Fix: leave {setting}= out, or use method='clip'."
                    )
                    raise SqlearnError(msg)
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.method = method
        self.lower = lower
        self.upper = upper

    def default_name(self) -> str:
        """Return the method, whatever the bounds.

        Returns
        -------
        str
            ``log``, ``log1p``, ``sqrt``, ``clip``, ``lower`` or ``upper``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.clip(lower=0).default_name()
        'clip'
        """
        return str(self.method)

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.lower is not None:
            kwargs["lower"] = self.lower
        if self.upper is not None:
            kwargs["upper"] = self.upper
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr(f"sq.transform.{self.method}", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to change, refusing any of the wrong kind.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns, in schema order: by default the numeric ones,
            or for ``lower`` and ``upper`` the text ones.

        Raises
        ------
        StepError
            If a chosen column is text under a numeric method, or not text
            under ``lower`` or ``upper``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE, VARCHAR
        >>> sq.transform.log().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        >>> sq.transform.lower().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['c']
        """
        method = str(self.method)
        if method not in _TEXT:
            return _numeric_inputs(self.cols, schema, method, _WHY[method])
        selector = _string() if self.cols is None else to_selector(self.cols)
        chosen = selector.resolve(schema)
        types: dict[str, DuckDBPyType] = dict(schema)
        text = set(_string().resolve(schema))
        for c in chosen:
            if c not in text:
                msg = (
                    f"cannot {method} column {c!r}, which is {types[c]}. Why: "
                    f"changing case needs text. Fix: choose text columns with "
                    "cols=, or cast the column to text before this step."
                )
                raise StepError(msg, step="", position=0)
        return chosen

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Apply the function to the column.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            Unused: the step learns nothing.

        Returns
        -------
        duckdb.Expression
            The changed column: DOUBLE for ``log``, ``log1p`` and ``sqrt``
            (a value outside the domain raises when fetched), the column's
            own type for ``clip`` and the case functions; NULL stays NULL.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> x = duckdb.ColumnExpression("a")
        >>> str(sq.transform.upper().apply(x, Learned.values({})))
        'upper("a")'
        """
        method, name = str(self.method), x.get_name()
        if method == "lower":
            return fn.lower(x)
        if method == "upper":
            return fn.upper(x)
        if method == "clip":
            return self._clip(x)
        v = x.cast("DOUBLE")
        if method == "log":
            bad = _refusal(
                method,
                name,
                "a value at or below 0",
                "clip the column above 0 first, or use sq.transform.log1p "
                "for values from 0.",
            )
            return duckdb.CaseExpression(v <= const(0.0), bad).otherwise(fn.ln(v))
        if method == "sqrt":
            bad = _refusal(
                method,
                name,
                "a negative value",
                "clip the column from 0 first, with sq.transform.clip(lower=0).",
            )
            return duckdb.CaseExpression(v < const(0.0), bad).otherwise(fn.sqrt(v))
        return self._log1p(v, name)

    @staticmethod
    def _log1p(v: Expression, name: str) -> Expression:
        """Return log(1 + v), exact for small v (Kahan), refusing v <= -1."""
        bad = _refusal(
            "log1p",
            name,
            "a value at or below -1",
            "clip the column above -1 first, with sq.transform.clip(lower=...).",
        )
        u = const(1.0) + v
        exact = fn.ln(u) * (v / (u - const(1.0)))
        return (
            duckdb.CaseExpression(v <= const(-1.0), bad)
            .when(duckdb.FunctionExpression("isinf", v), v)
            .when(u == const(1.0), v)
            .otherwise(exact)
        )

    def _clip(self, x: Expression) -> Expression:
        """Return x held between the bounds; NULL and NaN pass as they are."""
        out = x
        if self.lower is not None:
            out = fn.greatest(out, const(self.lower))
        if self.upper is not None:
            out = fn.least(out, const(self.upper))
        return duckdb.CaseExpression(is_missing(x), x).otherwise(out)


class _Settings(TypedDict, total=False):
    """The settings every shortcut passes on."""

    cols: Selector | str | Sequence[str] | None
    keep: bool
    suffix: str | None


class TransformGroup(Group):
    """Change values: ``sq.transform(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` picks the function and has no
    default. Each shortcut is a method, and builds exactly the step the
    general form builds with it. A transformation of your own is
    ``sq.Step(apply=...)``, not a method here.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.transform.log1p("income")
    sq.transform.log1p(cols='income')
    >>> sq.transform("income", method="log1p")
    sq.transform.log1p(cols='income')
    >>> sq.transform.clip("age", lower=0, upper=120)
    sq.transform.clip(cols='age', lower=0, upper=120)
    """

    def __call__(
        self,
        *names: object,
        method: str,
        lower: float | None = None,
        upper: float | None = None,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Transform:
        """Build the step that changes columns by `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list.
        method : {"log", "log1p", "sqrt", "clip", "lower", "upper"}
            The function; required.
        lower : float, optional
            ``clip``'s lower bound; only with ``clip``.
        upper : float, optional
            ``clip``'s upper bound; only with ``clip``.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the result.
        suffix : str, optional
            Suffix of the result's column when `keep` is True.

        Returns
        -------
        Transform
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, or a dict, or the settings
            do not fit `method` (see `Transform`).
        TypeError
            If `method` is left out.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform("age", method="sqrt", keep=True)
        sq.transform.sqrt(cols='age', keep=True)
        """
        chosen = columns_arg(names, cols, allow_dict=False)
        return Transform(
            cols=cast("str | list[str] | Selector | None", chosen),
            method=method,
            lower=lower,
            upper=upper,
            keep=keep,
            suffix=suffix,
        )

    def log(self, *names: object, **kw: Unpack[_Settings]) -> Transform:
        """Take the natural logarithm (``method="log"``).

        As ``np.log``, but a value at or below 0 is refused when the rows are
        fetched, naming the column: ``clip`` first, or use ``log1p``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.log("price")
        sq.transform.log(cols='price')
        """
        return self(*names, method="log", **kw)

    def log1p(self, *names: object, **kw: Unpack[_Settings]) -> Transform:
        """Take ``log(1 + x)`` (``method="log1p"``).

        As ``np.log1p``, accurate for small ``x``; a value at or below -1 is
        refused when the rows are fetched.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.log1p("income")
        sq.transform.log1p(cols='income')
        """
        return self(*names, method="log1p", **kw)

    def sqrt(self, *names: object, **kw: Unpack[_Settings]) -> Transform:
        """Take the square root (``method="sqrt"``).

        As ``np.sqrt``, but a negative value is refused when the rows are
        fetched, naming the column: ``clip`` it from 0 first.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.sqrt("area")
        sq.transform.sqrt(cols='area')
        """
        return self(*names, method="sqrt", **kw)

    def clip(
        self,
        *names: object,
        lower: float | None = None,
        upper: float | None = None,
        **kw: Unpack[_Settings],
    ) -> Transform:
        """Hold values between a lower and an upper bound (``method="clip"``).

        As ``np.clip``; with one bound only that side is clipped. NULL and
        NaN stay as they are.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        lower : float, optional
            Values below it become it.
        upper : float, optional
            Values above it become it.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Raises
        ------
        SqlearnError
            If neither bound is given, a bound is not a finite number, or
            `lower` is above `upper`.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.clip("age", lower=0)
        sq.transform.clip(cols='age', lower=0)
        """
        return self(*names, method="clip", lower=lower, upper=upper, **kw)

    def lower(self, *names: object, **kw: Unpack[_Settings]) -> Transform:
        """Write text in lower case (``method="lower"``).

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the text ones.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.lower("city")
        sq.transform.lower(cols='city')
        """
        return self(*names, method="lower", **kw)

    def upper(self, *names: object, **kw: Unpack[_Settings]) -> Transform:
        """Write text in upper case (``method="upper"``).

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the text ones.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Transform
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.transform.upper("city")
        sq.transform.upper(cols='city')
        """
        return self(*names, method="upper", **kw)


transform = TransformGroup("transform")
"""The transforming steps: ``sq.transform(...)``, ``sq.transform.log(...)``."""
