"""Scale: centre and divide numeric columns, ``sq.scale`` and its shortcuts.

``sq.scale.normalize`` divides each row by its norm instead (`Normalize`).
"""

import math
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict, Unpack, cast, overload

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, is_missing
from sqlearn._group import Group, call_repr, column_names, columns_arg
from sqlearn._selectors import Schema, Selector, _numeric, to_selector
from sqlearn._step import Learned, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing._missing import (
    infinite,
    refuse_all_missing,
    refuse_infinite,
)

__all__ = ["DEFAULT", "Normalize", "Scale", "ScaleGroup", "scale"]

DEFAULT = "default"
"""The setting that takes the method's own centre, spread or feature range."""

Part = agg.Aggregate | str | None
"""A centre or spread: an aggregate, its name, None, or `DEFAULT`."""

Range = tuple[float, float] | list[float] | str | None
"""A feature range: a pair ``(a, b)``, None, or `DEFAULT`."""

_METHODS: dict[str, tuple[agg.Aggregate | None, agg.Aggregate, object]] = {
    "standard": (agg.mean, agg.std, None),
    "robust": (agg.median, agg.iqr, None),
    "minmax": (agg.min, agg.range, (0, 1)),
    "maxabs": (None, agg.maxabs, None),
}
"""Each method's centre, spread and feature range, as scikit-learn's scalers."""


def _method(method: object) -> str:
    """Return `method` when it is a method's name, else refuse it."""
    if isinstance(method, str) and method in _METHODS:
        return method
    if method == "normalize":
        msg = (
            "Scale got method='normalize'. Why: normalize divides each row by "
            "its norm, a step of its own (Normalize), not a centre and a "
            "spread, so a Scale cannot become it. Fix: build it with "
            "sq.scale.normalize(), or search over whole steps."
        )
        raise SqlearnError(msg)
    names = ", ".join(repr(m) for m in [*_METHODS, "normalize"])
    msg = (
        f"sq.scale got method={method!r}, which is not a method. Why: the "
        f"methods are {names}. Fix: use one of them, or a shortcut such as "
        "sq.scale.robust()."
    )
    raise SqlearnError(msg)


def _part(setting: str, value: object) -> Part:
    """Return the centre or spread `value` stands for, refusing what is none."""
    if value is None or value == DEFAULT:
        return cast("Part", value)
    if isinstance(value, str):
        value = agg.lookup(value) or value
    if isinstance(value, agg.Aggregate) and value.name != "distinct":
        return value
    msg = (
        f"sq.scale got {setting}={value!r}, which is not a {setting}. Why: a "
        f"{setting} is an aggregate learned from the column (such as "
        f"sq.agg.median), its name ('median'), or None. Fix: give one of "
        "those; sq.agg.distinct is a list, not a number."
    )
    raise SqlearnError(msg)


def _feature_range(value: object) -> Range:
    """Return a feature range as a pair of numbers, None or `DEFAULT`."""
    if value is None or value == DEFAULT:
        return cast("Range", value)
    pair = tuple(value) if isinstance(value, list | tuple) else ()
    numbers = len(pair) == 2 and all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
        for v in pair
    )
    if not numbers or not pair[0] < pair[1]:
        msg = (
            f"sq.scale got feature_range={value!r}, which is not a range. Why: "
            "the scaled values are stretched onto (a, b), and a must be below "
            "b. Fix: give two numbers, such as feature_range=(0, 1)."
        )
        raise SqlearnError(msg)
    return cast("tuple[float, float]", pair)


def _quantile_range(value: object) -> tuple[float, float]:
    """Return `value` as RobustScaler's ``quantile_range``, refusing others."""
    pair = tuple(value) if isinstance(value, list | tuple) else ()
    numbers = len(pair) == 2 and all(
        isinstance(v, int | float) and not isinstance(v, bool) for v in pair
    )
    if not numbers or not 0 <= pair[0] <= pair[1] <= 100:
        msg = (
            f"sq.scale.robust got quantile_range={value!r}. Why: it is a low "
            "and a high percentile, each from 0 to 100, the low one first. "
            "Fix: give such a pair, as quantile_range=(25, 75)."
        )
        raise SqlearnError(msg)
    return cast("tuple[float, float]", pair)


def _percent(q: float) -> float | None:
    """Return `q` in percent when that percent rebuilds `q` exactly, else None."""
    percent = round(q * 100, 10)
    if percent / 100 != q:
        return None
    return int(percent) if percent.is_integer() else percent


EPS = 2.0**-52
"""The machine epsilon of DOUBLE, by which scikit-learn judges a spread."""


def _constant(x: Expression, spread: agg.Aggregate, raw: Expression) -> Expression:
    """Return whether a column's spread is at the level of rounding: none.

    As scikit-learn's scalers judge it: the standard deviation by the
    variance, against its bound on the rounding of a two-pass variance
    (``var <= n * eps * var + (n * mean * eps) ** 2``, its
    ``_is_constant_feature``); any other spread below ten machine epsilons
    (its ``_handle_zeros_in_scale``). NULL (no value) is not constant.
    """
    if spread != agg.std:
        return raw < const(10 * EPS)
    var, n, mean = agg.var(x), agg.count(x).cast("DOUBLE"), agg.mean(x)
    eps = const(EPS)
    rounding = n * mean * eps
    return var <= n * eps * var + rounding * rounding


def _numeric_inputs(
    cols: Selector | str | tuple[str, ...] | list[str] | None,
    schema: Schema,
    verb: str,
    why: str,
) -> list[str]:
    """Return the chosen columns (the numeric ones by default), refusing text."""
    selector = _numeric() if cols is None else to_selector(cols)
    chosen = selector.resolve(schema)
    types: dict[str, DuckDBPyType] = dict(schema)
    numeric = set(_numeric().resolve(schema))
    for c in chosen:
        if c not in numeric:
            msg = (
                f"cannot {verb} column {c!r}, which is {types[c]}. Why: "
                f"{why}, which takes numbers. Fix: "
                "choose numeric columns with cols=, or encode the column "
                "as numbers before this step."
            )
            raise StepError(msg, step="", position=0)
    return chosen


class Scale(Step):
    """Centre numeric columns and divide them by their spread.

    Build it with `sq.scale <ScaleGroup>` or one of its shortcuts. Each column
    becomes ``(x - center) / spread`` and then, with `feature_range`
    ``(a, b)``, ``* (b - a) + a``, as DOUBLE. The centre and spread are
    aggregates learned over the column's present values (neither NULL nor
    NaN); `method` gives their defaults, as scikit-learn's scalers:

    ========  ======  ======  =============  ==============
    method    center  spread  feature_range  scikit-learn
    ========  ======  ======  =============  ==============
    standard  mean    std     None           StandardScaler
    robust    median  iqr     None           RobustScaler
    minmax    min     range   (0, 1)         MinMaxScaler
    maxabs    None    maxabs  None           MaxAbsScaler
    ========  ======  ======  =============  ==============

    A spread at the level of rounding counts as 1, as scikit-learn judges
    it (the standard deviation by its variance's rounding bound, any other
    spread below ten machine epsilons), so a constant column scales to 0
    (or to ``a``). A dict gives each column its own method.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to scale; by default the numeric ones. With a dict, its
        keys.
    method : str or dict, default "standard"
        ``"standard"``, ``"robust"``, ``"minmax"`` or ``"maxabs"``; a dict
        maps each column to one of them.
    center : Aggregate, str or None, default "default"
        What to subtract: an aggregate (``sq.agg.mean``), its name, or None
        for 0. ``"default"`` takes the method's. A given one replaces it and
        the method stays: ``robust`` with ``center=sq.agg.mean`` is robust.
        A value equal to the method's own is stored as ``"default"``, so a
        search over `method` takes each method's own; the values learned
        are read from `center_` and `scale_`.
    spread : Aggregate, str or None, default "default"
        What to divide by, as `center`; None for 1. Stored as ``"default"``
        when it is the method's own, as `center` is.
    feature_range : tuple of (float, float) or None, default "default"
        The range ``(a, b)`` to stretch the result onto, or None for none;
        ``"default"`` takes the method's, and a range equal to the method's
        own is stored as ``"default"``.
    keep : bool, default False
        Keep the input column and add the scaled one beside it.
    suffix : str, optional
        Suffix of the scaled column when `keep` is True; defaults to the
        step's name.

    Attributes
    ----------
    center_ : dict of str to float
        After learning, each column's centre, where there is one.
    scale_ : dict of str to float
        After learning, each column's divisor (1 where the spread is at the
        level of rounding), where there is a spread.

    Raises
    ------
    SqlearnError
        If `method`, `center`, `spread` or `feature_range` is not one, or a
        dict is given with other `cols` than its keys, or with `center`,
        `spread` or `feature_range`.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [1.0, 2.0, 3.0, 10.0]})
    >>> pipe = sq.Pipeline([sq.scale.robust()]).learn(data)
    >>> pipe["robust"].center_, pipe["robust"].scale_
    ({'x': 2.5}, {'x': 3.0})
    >>> pipe.apply(data, out="pandas")["x"].tolist()
    [-0.5, -0.16666666666666666, 0.16666666666666666, 2.5]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        method: str | Mapping[str, str] = "standard",
        center: Part = DEFAULT,
        spread: Part = DEFAULT,
        feature_range: Range = DEFAULT,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        resolved: object
        given = {"center": center, "spread": spread, "feature_range": feature_range}
        if isinstance(method, Mapping):
            for setting, value in given.items():
                if value != DEFAULT:
                    msg = (
                        f"sq.scale got the dict {dict(method)!r} and "
                        f"{setting}={value!r}. Why: the dict gives each column "
                        "a method, which brings its own centre and spread. "
                        f"Fix: leave {setting}= out, or scale those columns in "
                        "a step of their own."
                    )
                    raise SqlearnError(msg)
            resolved = {str(k): self._dict_method(method, v) for k, v in method.items()}
            keys = list(resolved)
            if cols is None:
                cols = keys
            elif column_names(cols) != keys:
                msg = (
                    f"sq.scale got the dict {dict(method)!r} and cols={cols!r}. "
                    "Why: a dict names the columns itself, by its keys. Fix: "
                    "leave cols= out."
                )
                raise SqlearnError(msg)
        else:
            resolved = _method(method)
            defaults = _METHODS[resolved]
            center, spread = _part("center", center), _part("spread", spread)
            feature_range = _feature_range(feature_range)
            # A value equal to the method's own is stored as the default, so
            # equal steps have equal settings and a new method takes its own.
            center = DEFAULT if center == defaults[0] else center
            spread = DEFAULT if spread == defaults[1] else spread
            if feature_range == defaults[2]:
                feature_range = DEFAULT
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.method = resolved
        self.center = center
        self.spread = spread
        self.feature_range = feature_range

    @staticmethod
    def _dict_method(method: Mapping[str, object], value: object) -> str:
        if isinstance(value, str) and value in _METHODS:
            return value
        if value == "normalize":
            msg = (
                f"sq.scale got the dict {dict(method)!r}, which maps a column to "
                "'normalize'. Why: normalize divides by the norm of the whole "
                "row, not of one column. Fix: normalize those columns in a step "
                "of their own, sq.scale.normalize(cols=[...])."
            )
            raise SqlearnError(msg)
        names = ", ".join(repr(m) for m in _METHODS)
        msg = (
            f"sq.scale got the dict {dict(method)!r}, which maps a column to "
            f"{value!r}. Why: a dict maps each column to a method's name: "
            f"{names}. Fix: give one of those, or a step of its own for a "
            "centre or spread of your own."
        )
        raise SqlearnError(msg)

    def _parts(self, column: str) -> tuple[agg.Aggregate | None, ...]:
        """Return a column's centre, spread and feature range, defaults resolved."""
        if isinstance(self.method, Mapping):
            return cast(
                "tuple[agg.Aggregate | None, ...]", _METHODS[self.method[column]]
            )
        defaults = _METHODS[str(self.method)]
        given = (self.center, self.spread, self.feature_range)
        return cast(
            "tuple[agg.Aggregate | None, ...]",
            tuple(
                d if g == DEFAULT else g for g, d in zip(given, defaults, strict=True)
            ),
        )

    def default_name(self) -> str:
        """Return the method, or ``scale`` for a dict.

        Returns
        -------
        str
            ``standard``, ``robust``, ``minmax`` or ``maxabs``, whatever centre
            or spread is given; ``scale`` for a dict of methods.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale(method="robust", center=sq.agg.mean).default_name()
        'robust'
        """
        return "scale" if isinstance(self.method, Mapping) else str(self.method)

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        args: list[object] = []
        kwargs: dict[str, object] = {}
        if isinstance(self.method, Mapping):
            path = "sq.scale"
            args.append(self.method)
        else:
            path = f"sq.scale.{self.method}"
            if self.cols is not None:
                kwargs["cols"] = self.cols
            if self.center != DEFAULT:
                kwargs["center"] = self.center
            if self.spread != DEFAULT:
                percents = self._quantile_range()
                if percents is None:
                    kwargs["spread"] = self.spread
                else:
                    kwargs["quantile_range"] = percents
            if self.feature_range != DEFAULT:
                kwargs["feature_range"] = self.feature_range
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr(path, *args, **kwargs)

    def _quantile_range(self) -> tuple[float, float] | None:
        """Return robust's spread as ``quantile_range``, when it is one."""
        spread = self.spread
        if self.method != "robust" or not isinstance(spread, agg.Aggregate):
            return None
        if spread.name != "iqr":
            return None
        low, high = cast("tuple[float, float]", spread.params["q"])
        percents = (_percent(low), _percent(high))
        if percents[0] is None or percents[1] is None:
            return None
        return cast("tuple[float, float]", percents)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to scale, refusing any that is not numeric.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns (by default the numeric ones), in schema order.

        Raises
        ------
        StepError
            If a chosen column is not numeric.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE, VARCHAR
        >>> sq.scale().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "scale", "scaling subtracts and divides"
        )

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the centre, the divisor and whether the column holds infinity.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``center`` (when there is one), ``scale`` (the spread, when
            there is one, 1 where it is at the level of rounding, as
            scikit-learn judges it), both DOUBLE, and ``infinite``
            (infinity where the column holds any, else 0).

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.scale.robust().learn(duckdb.ColumnExpression("a")))
        ['center', 'scale', 'infinite']
        >>> list(sq.scale.maxabs().learn(duckdb.ColumnExpression("a")))
        ['scale', 'infinite']
        """
        center, spread, _ = self._parts(x.get_name())
        out: dict[str, Expression] = {}
        if center is not None:
            out["center"] = center(x).cast("DOUBLE")
        if spread is not None:
            raw = spread(x).cast("DOUBLE")
            constant = _constant(x, spread, raw)
            out["scale"] = duckdb.CaseExpression(constant, const(1.0)).otherwise(raw)
        out["infinite"] = infinite(x)
        return out

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Centre the column, divide it, then stretch it onto the feature range.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            ``(x - center) / scale``, then ``* (b - a) + a``, as DOUBLE.

        Raises
        ------
        StepError
            If every value of the column was missing, or any is infinite.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> x = duckdb.ColumnExpression("a")
        >>> learned = Learned.values({"center": 2.0, "scale": 4.0, "infinite": 0.0})
        >>> "4.0" in str(sq.scale().apply(x, learned))
        True
        """
        center, spread, feature_range = self._parts(x.get_name())
        if spread is not None:
            refuse_all_missing(x, learned, "scale")
        elif center is not None:
            refuse_all_missing(x, learned, "center")
        refuse_infinite(x, learned, "infinite")
        out = x.cast("DOUBLE")
        if center is not None:
            out = out - learned.center
        if spread is not None:
            out = out / learned.scale
        if feature_range is not None:
            a, b = cast("tuple[float, float]", feature_range)
            out = out * const(float(b - a)) + const(float(a))
        return out


NORMS = ("l1", "l2", "max")
"""The norms `Normalize` divides by, as scikit-learn's ``Normalizer``."""


def _refusal(name: str, found: str, fix: str) -> Expression:
    """Return ``error(...)``: a refusal DuckDB raises when the row is fetched."""
    msg = (
        f"sq.scale.normalize found {found} in column {name!r}. Why: a row's "
        "norm needs every value of the row to be a number, and "
        f"scikit-learn's Normalizer refuses it too. Fix: {fix}"
    )
    return duckdb.FunctionExpression("error", const(msg))


_MISSING = (
    "a missing value (NULL or NaN)",
    "impute the column first, such as with sq.impute() before this step.",
)
_INFINITE = (
    "an infinite value",
    "replace or drop the infinite values before this step.",
)


class Normalize(Step):
    """Divide each row's selected values by that row's norm.

    Build it with ``sq.scale.normalize`` or ``sq.scale(method="normalize")``.
    As scikit-learn's ``Normalizer``: the norm of a row is the sum of its
    absolute values (``"l1"``), the square root of the sum of their squares
    (``"l2"``) or the largest absolute value (``"max"``), over the selected
    columns; each becomes ``x / norm``, as DOUBLE. A norm below ten machine
    epsilons counts as 1, so a row of zeros stays zeros. It learns nothing,
    and every output reads every selected column: it is a whole-row step
    (``rowwise``).

    A missing value (NULL or NaN) or an infinity in a selected column is
    refused when the rows are fetched, naming the column: impute first.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns of the row; by default the numeric ones.
    norm : {"l1", "l2", "max"}, default "l2"
        The norm to divide by.
    keep : bool, default False
        Keep the input columns and add the divided ones beside them.
    suffix : str, optional
        Suffix of the divided columns when `keep` is True; defaults to the
        step's name.

    Raises
    ------
    SqlearnError
        If `norm` is not one of the norms.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"a": [3.0, 0.0], "b": [4.0, 0.0]})
    >>> pipe = sq.Pipeline([sq.scale.normalize()]).learn(data)
    >>> pipe.apply(data, out="pandas").to_numpy().tolist()
    [[0.6, 0.8], [0.0, 0.0]]
    """

    static = True
    rowwise = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        norm: str = "l2",
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        if norm not in NORMS:
            names = ", ".join(repr(n) for n in NORMS)
            msg = (
                f"sq.scale.normalize got norm={norm!r}, which is not a norm. "
                f"Why: the norms are {names}, as scikit-learn's Normalizer. "
                "Fix: use one of them."
            )
            raise SqlearnError(msg)
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.norm = norm

    def default_name(self) -> str:
        """Return ``normalize``.

        Returns
        -------
        str
            ``normalize``, whatever the norm.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.normalize(norm="l1").default_name()
        'normalize'
        """
        return "normalize"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.norm != "l2":
            kwargs["norm"] = self.norm
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr("sq.scale.normalize", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns of the row, refusing any that is not numeric.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns (by default the numeric ones), in schema order.

        Raises
        ------
        StepError
            If a chosen column is not numeric.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE, VARCHAR
        >>> sq.scale.normalize().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "normalize", "normalizing divides by the row's norm"
        )

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
    ) -> Mapping[str, Expression]:
        """Divide each selected value by the row's norm.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The selected columns, by name.
        learned : mapping of str to Learned
            Unused: the step learns nothing.

        Returns
        -------
        mapping of str to duckdb.Expression
            Each column, ``x / norm`` as DOUBLE, under its own name; a value
            missing or infinite raises when fetched.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> xs = {"a": duckdb.ColumnExpression("a")}
        >>> list(sq.scale.normalize().apply_row(xs, {}))
        ['a']
        """
        checked: dict[str, Expression] = {}
        for name, x in xs.items():
            v = x.cast("DOUBLE")
            isinf = duckdb.FunctionExpression("isinf", v)
            checked[name] = (
                duckdb.CaseExpression(is_missing(x), _refusal(name, *_MISSING))
                .when(isinf, _refusal(name, *_INFINITE))
                .otherwise(v)
            )
        if not checked:
            return checked
        sizes = [duckdb.FunctionExpression("abs", v) for v in checked.values()]
        if self.norm == "max":
            norm = duckdb.FunctionExpression("greatest", *sizes)
        else:
            parts = sizes if self.norm == "l1" else [v * v for v in checked.values()]
            norm = parts[0]
            for part in parts[1:]:
                norm = norm + part
            if self.norm == "l2":
                norm = duckdb.FunctionExpression("sqrt", norm)
        # As scikit-learn's _handle_zeros_in_scale: a norm at the level of
        # rounding counts as 1, so the row is left as it is.
        divisor = duckdb.CaseExpression(norm < const(10 * EPS), const(1.0)).otherwise(
            norm
        )
        return {name: v / divisor for name, v in checked.items()}


class _Columns(TypedDict, total=False):
    """The general form's settings every shortcut passes on."""

    cols: Selector | str | Sequence[str] | None
    keep: bool
    suffix: str | None


class _Parts(_Columns, total=False):
    """The settings a shortcut passes on, the centre and spread among them."""

    center: Part
    spread: Part


class _Settings(_Parts, total=False):
    """The settings a shortcut without a feature range of its own passes on."""

    feature_range: Range


class ScaleGroup(Group):
    """Scale numeric columns: ``sq.scale(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` gives the centre, spread and
    feature range their defaults, and a given one replaces the method's; a
    dict as the first argument gives each column its own method. Each
    shortcut is a method, and builds exactly the step the general form
    builds with it.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.scale.robust("age")
    sq.scale.robust(cols='age')
    >>> sq.scale("age", method="robust")
    sq.scale.robust(cols='age')
    >>> sq.scale({"age": "robust", "income": "standard"})
    sq.scale({'age': 'robust', 'income': 'standard'})
    >>> sq.scale(method="normalize", norm="l1")
    sq.scale.normalize(norm='l1')
    """

    # "normalize" is also a str, so the two overlap; the first is chosen.
    @overload
    def __call__(  # type: ignore[overload-overlap]
        self,
        *names: object,
        method: Literal["normalize"],
        norm: str = DEFAULT,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Normalize: ...

    @overload
    def __call__(
        self,
        *names: object,
        method: str = "standard",
        center: Part = DEFAULT,
        spread: Part = DEFAULT,
        feature_range: Range = DEFAULT,
        norm: str = DEFAULT,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Scale: ...

    def __call__(
        self,
        *names: object,
        method: str = "standard",
        center: Part = DEFAULT,
        spread: Part = DEFAULT,
        feature_range: Range = DEFAULT,
        norm: str = DEFAULT,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Scale | Normalize:
        """Build the step that scales columns by `method`.

        Parameters
        ----------
        *names : str, list of str or dict
            The columns: names, one list, or one dict of column to method.
        method : str, default "standard"
            ``"standard"``, ``"robust"``, ``"minmax"``, ``"maxabs"`` or
            ``"normalize"`` (a `Normalize`); not given with a dict.
        center : Aggregate, str or None, default "default"
            What to subtract (see `Scale`); the method's by default.
        spread : Aggregate, str or None, default "default"
            What to divide by; the method's by default.
        feature_range : tuple of (float, float) or None, default "default"
            The range to stretch the result onto; the method's by default.
        norm : {"l1", "l2", "max"}, default "default"
            The norm of ``normalize`` (``"l2"`` by default); only with it.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the scaled one.
        suffix : str, optional
            Suffix of the scaled column when `keep` is True.

        Returns
        -------
        Scale or Normalize
            The step: a `Normalize` for ``method="normalize"``.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, or a dict and `method`, or
            ``normalize`` with `center`, `spread` or `feature_range`, or
            `norm` with another method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale("age", method="minmax", feature_range=(-1, 1))
        sq.scale.minmax(cols='age', feature_range=(-1, 1))
        """
        chosen = columns_arg(names, cols, allow_dict=True)
        given: str | Mapping[str, str] = method
        if isinstance(chosen, dict):
            if method != "standard":
                msg = (
                    f"sq.scale got the dict {chosen!r} and method={method!r}. "
                    "Why: the dict gives each column its method. Fix: leave "
                    "method= out, or put the method in the dict."
                )
                raise SqlearnError(msg)
            given = chosen
            chosen = None
        columns = cast("str | list[str] | Selector | None", chosen)
        if method == "normalize" and not isinstance(given, Mapping):
            parts = {"center": center, "spread": spread, "feature_range": feature_range}
            for setting, value in parts.items():
                if value != DEFAULT:
                    msg = (
                        f"sq.scale got method='normalize' and {setting}={value!r}. "
                        "Why: normalize divides each row by its norm, so it has "
                        f"no {setting}. Fix: leave {setting}= out, or use "
                        "another method."
                    )
                    raise SqlearnError(msg)
            return Normalize(
                cols=columns,
                norm="l2" if norm == DEFAULT else norm,
                keep=keep,
                suffix=suffix,
            )
        if norm != DEFAULT:
            what = "a dict of methods" if isinstance(given, Mapping) else f"{method=}"
            msg = (
                f"sq.scale got norm={norm!r} with {what}. Why: only normalize "
                "divides by a row's norm. Fix: leave norm= out, or use "
                "method='normalize'."
            )
            raise SqlearnError(msg)
        return Scale(
            cols=columns,
            method=given,
            center=center,
            spread=spread,
            feature_range=feature_range,
            keep=keep,
            suffix=suffix,
        )

    def standard(self, *names: object, **kw: Unpack[_Settings]) -> Scale:
        """Subtract the mean, divide by the standard deviation (``method="standard"``).

        As scikit-learn's ``StandardScaler``: the population standard
        deviation; a column whose variance is within rounding of 0 is
        constant and divided by 1, as scikit-learn's.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's other settings (``center``, ``spread``,
            ``feature_range``, ``cols``, ``keep``, ``suffix``).

        Returns
        -------
        Scale
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.standard("age")
        sq.scale.standard(cols='age')
        """
        return self(*names, method="standard", **kw)

    def robust(
        self,
        *names: object,
        quantile_range: tuple[float, float] = (25.0, 75.0),
        **kw: Unpack[_Settings],
    ) -> Scale:
        """Subtract the median, divide by the interquartile range (``"robust"``).

        As scikit-learn's ``RobustScaler``: the quantiles are exact, by
        sorting. ``quantile_range=(a, b)`` sets the spread to
        ``sq.agg.iqr(q=(a / 100, b / 100))``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        quantile_range : tuple of (float, float), default (25.0, 75.0)
            The low and high percentiles the spread lies between.
        **kw : object
            The general form's other settings (``center``, ``spread``,
            ``feature_range``, ``cols``, ``keep``, ``suffix``).

        Returns
        -------
        Scale
            The step.

        Raises
        ------
        SqlearnError
            If `quantile_range` is not two percentiles, low first, or is
            given with ``spread``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.robust(quantile_range=(10, 90))
        sq.scale.robust(quantile_range=(10, 90))
        """
        low, high = _quantile_range(quantile_range)
        if (low, high) != (25, 75):
            if "spread" in kw:
                msg = (
                    f"sq.scale.robust got quantile_range={quantile_range!r} and "
                    f"spread={kw['spread']!r}. Why: the quantile range sets the "
                    "spread. Fix: give one of them."
                )
                raise SqlearnError(msg)
            kw["spread"] = agg.iqr(q=(low / 100, high / 100))
        return self(*names, method="robust", **kw)

    def minmax(
        self,
        *names: object,
        feature_range: Range = (0, 1),
        **kw: Unpack[_Parts],
    ) -> Scale:
        """Subtract the minimum, divide by the range, stretch onto (a, b).

        As scikit-learn's ``MinMaxScaler`` (``method="minmax"``): the result
        lies in `feature_range`, ``(0, 1)`` by default.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        feature_range : tuple of (float, float) or None, default (0, 1)
            The range ``(a, b)`` the learned values are stretched onto.
        **kw : object
            The general form's other settings (``center``, ``spread``,
            ``cols``, ``keep``, ``suffix``).

        Returns
        -------
        Scale
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.minmax(feature_range=(-1, 1))
        sq.scale.minmax(feature_range=(-1, 1))
        """
        return self(*names, method="minmax", feature_range=feature_range, **kw)

    def maxabs(self, *names: object, **kw: Unpack[_Settings]) -> Scale:
        """Divide by the largest absolute value (``method="maxabs"``).

        As scikit-learn's ``MaxAbsScaler``: nothing is subtracted, so zeros
        stay zeros; the result lies in ``[-1, 1]``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's other settings (``center``, ``spread``,
            ``feature_range``, ``cols``, ``keep``, ``suffix``).

        Returns
        -------
        Scale
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.maxabs("income")
        sq.scale.maxabs(cols='income')
        """
        return self(*names, method="maxabs", **kw)

    def normalize(
        self,
        *names: object,
        norm: str = "l2",
        **kw: Unpack[_Columns],
    ) -> Normalize:
        """Divide each row by its norm (``method="normalize"``).

        As scikit-learn's ``Normalizer``: over the selected columns of each
        row, the norm is ``"l1"`` (sum of absolute values), ``"l2"`` (square
        root of the sum of squares) or ``"max"`` (largest absolute value). A
        row of zeros stays zeros. It learns nothing; a missing or infinite
        value is refused when the rows are fetched, so impute first.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        norm : {"l1", "l2", "max"}, default "l2"
            The norm to divide by.
        **kw : object
            The general form's ``cols``, ``keep`` and ``suffix``.

        Returns
        -------
        Normalize
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.scale.normalize("a", "b", norm="l1")
        sq.scale.normalize(cols=['a', 'b'], norm='l1')
        """
        return self(*names, method="normalize", norm=norm, **kw)


scale = ScaleGroup("scale")
"""The scaling steps: ``sq.scale(...)``, ``sq.scale.robust(...)`` and so on."""
