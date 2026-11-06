"""Features: make new columns from numbers, ``sq.features`` and its shortcuts.

``sq.features.polynomial`` multiplies the chosen columns together
(`Polynomial`, a whole-row step that learns nothing); ``sq.features.spline``
writes each column's B-spline basis (`Spline`, per column, learning the
knots). Both are static: the columns they make follow from their settings.
"""

import itertools
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, TypedDict, Unpack, cast, overload

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE

from sqlearn._errors import SqlearnError
from sqlearn._expr import const, is_missing
from sqlearn._group import Group, call_repr, columns_arg
from sqlearn._selectors import Schema, Selector
from sqlearn._step import Learned, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing._missing import (
    infinite,
    refuse_all_missing,
    refuse_infinite,
)
from sqlearn.preprocessing.scale import _numeric_inputs

__all__ = ["FeaturesGroup", "Polynomial", "Spline", "features"]

METHODS = ("polynomial", "spline")
"""The feature makers of ``sq.features``."""

KNOTS = ("uniform", "quantile")
"""Where `Spline` places its knots, as ``SplineTransformer``'s ``knots``."""

EXTRAPOLATIONS = ("constant",)
"""How `Spline` continues past its knots: only scikit-learn's default here."""


def _whole(setting: str, value: object, least: int, step: str, example: str) -> int:
    """Return `value` when it is a whole number at least `least`, else refuse it."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= least:
        return value
    msg = (
        f"sq.features.{step} got {setting}={value!r}. Why: {setting} is a whole "
        f"number at least {least}, as scikit-learn's. Fix: give one, such as "
        f"{setting}={example}."
    )
    raise SqlearnError(msg)


def _flag(setting: str, value: object) -> bool:
    """Return `value` when it is True or False, else refuse it."""
    if isinstance(value, bool):
        return value
    msg = (
        f"sq.features.polynomial got {setting}={value!r}. Why: it is a "
        f"switch, True or False. Fix: give {setting}=True or {setting}=False."
    )
    raise SqlearnError(msg)


class Polynomial(Step):
    """Multiply the chosen columns into every product up to a degree.

    Build it with `sq.features.polynomial <FeaturesGroup>`. As
    scikit-learn's ``PolynomialFeatures``: for columns ``a`` and ``b`` and
    degree 2 it writes ``a``, ``b``, ``a^2``, ``a*b``, ``b^2``, in
    scikit-learn's ``powers_`` order, named as its
    ``get_feature_names_out`` with the space of a product written ``*``.
    With `interaction_only`, no column is multiplied by itself. Every term is
    DOUBLE; NULL in a factor gives NULL, NaN gives NaN.

    It learns nothing, and its outputs read several columns of the row: it is
    a whole-row step (``rowwise``). The degree-one terms take their input
    columns' places; the rest follow the last input. `include_bias` adds
    scikit-learn's column ``1``, of ones, right after the inputs (in
    scikit-learn it comes first). A created name that a column passing
    through already holds is numbered (ADR 0035).

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to multiply; by default the numeric ones.
    degree : int, default 2
        The largest number of factors in a term.
    interaction_only : bool, default False
        Only products of distinct columns (and the columns themselves).
    include_bias : bool, default False
        Add the column ``1``. False by default, unlike scikit-learn, since
        every model sqlearn feeds fits its own intercept.

    Raises
    ------
    SqlearnError
        If `degree` is not a whole number from 0, or is 0 without
        `include_bias`, or a switch is not True or False.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"a": [2.0], "b": [3.0]})
    >>> pipe = sq.Pipeline([sq.features.polynomial()]).learn(data)
    >>> pipe.columns_out_
    ['a', 'b', 'a^2', 'a*b', 'b^2']
    >>> pipe.apply(data, out="pandas").to_numpy().tolist()
    [[2.0, 3.0, 4.0, 6.0, 9.0]]
    """

    static = True
    rowwise = True
    names_are_labels = False

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        degree: int = 2,
        interaction_only: bool = False,
        include_bias: bool = False,
    ) -> None:
        degree = _whole("degree", degree, 0, "polynomial", "2")
        include_bias = _flag("include_bias", include_bias)
        if degree == 0 and not include_bias:
            msg = (
                "sq.features.polynomial got degree=0 without include_bias. "
                "Why: degree 0 makes only the column 1, so nothing would be "
                "written, which scikit-learn refuses too. Fix: give degree=1 "
                "or more, or include_bias=True."
            )
            raise SqlearnError(msg)
        super().__init__(cols=cols)
        self.degree = degree
        self.interaction_only = _flag("interaction_only", interaction_only)
        self.include_bias = include_bias

    def default_name(self) -> str:
        """Return ``polynomial``.

        Returns
        -------
        str
            ``polynomial``, whatever the settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.features.polynomial(degree=3).default_name()
        'polynomial'
        """
        return "polynomial"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.degree != 2:
            kwargs["degree"] = self.degree
        if self.interaction_only:
            kwargs["interaction_only"] = True
        if self.include_bias:
            kwargs["include_bias"] = True
        return call_repr("sq.features.polynomial", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to multiply, refusing any that is not numeric.

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
        >>> sq.features.polynomial().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "multiply", "a polynomial term multiplies values"
        )

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
        values: Mapping[str, Expression],
    ) -> Mapping[str, Expression]:
        """Write every term, in scikit-learn's ``powers_`` order.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The selected columns, by name.
        learned : mapping of str to Learned
            Unused: the step learns nothing.
        values : mapping of str to duckdb.Expression
            Unused: the step computes nothing once per row.

        Returns
        -------
        mapping of str to duckdb.Expression
            Each term's full name (``a``, ``a^2``, ``a*b``, ``1``) to its
            product, as DOUBLE; nothing when no column is selected.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> xs = {c: duckdb.ColumnExpression(c) for c in "ab"}
        >>> list(sq.features.polynomial().apply_row(xs, {}, {}))
        ['a', 'b', 'a^2', 'a*b', 'b^2']
        """
        names = list(xs)
        out: dict[str, Expression] = {}
        if not names:
            return out
        if self.include_bias and self.degree == 0:
            out["1"] = const(1.0)
        combine = (
            itertools.combinations
            if self.interaction_only
            else itertools.combinations_with_replacement
        )
        double = {name: x.cast(DOUBLE) for name, x in xs.items()}
        for d in range(1, self.degree + 1):
            for term in combine(range(len(names)), d):
                out[_term_name([names[i] for i in term])] = _product(
                    [double[names[i]] for i in term]
                )
            if d == 1 and self.include_bias:
                # After the inputs' own terms, which take the inputs' places.
                out["1"] = const(1.0)
        return out


def _term_name(factors: list[str]) -> str:
    """Name a term as scikit-learn: ``a^2*b``, powers above one written ``^``."""
    counts = {name: factors.count(name) for name in dict.fromkeys(factors)}
    return "*".join(f"{n}^{c}" if c != 1 else n for n, c in counts.items())


def _product(factors: list[Expression]) -> Expression:
    """Multiply the factors as scikit-learn: the later ones first, then the first."""
    out = factors[-1]
    for factor in reversed(factors[:-1]):
        out = out * factor
    return out


def _rank(i: int, n: int) -> float:
    """Return the `i`-th of `n` quantile levels, as scikit-learn asks numpy.

    scikit-learn asks for the percentiles ``100 * np.linspace(0, 1, n)``,
    which numpy divides by 100: ``i * (1 / (n - 1))`` (the last exactly 1),
    times 100, over 100.
    """
    level = 1.0 if i == n - 1 else i * (1.0 / (n - 1))
    return (100.0 * level) / 100.0


def _linspace(start: Expression, stop: Expression, num: int) -> list[Expression]:
    """Return numpy's ``linspace(start, stop, num)``, as expressions.

    As numpy computes it in doubles: the step ``(stop - start) / (num - 1)``,
    then ``i * step + start``, the last exactly `stop`; one value is `start`.
    """
    if num <= 1:
        return [start][:num]
    step = (stop - start) / const(float(num - 1))
    return [const(float(i)) * step + start for i in range(num - 1)] + [stop]


def _extend(base: list[Expression], degree: int) -> list[Expression]:
    """Add `degree` knots on each side, as ``SplineTransformer`` does.

    The steps repeat the distance between the first two knots below them, and
    between the last two above them: ``np.linspace(first - degree * d,
    first - d, degree)`` and its mirror.
    """
    low, high = base[1] - base[0], base[-1] - base[-2]
    k = const(float(degree))
    below = _linspace(base[0] - k * low, base[0] - low, degree)
    above = _linspace(base[-1] + high, base[-1] + k * high, degree)
    return [*below, *base, *above]


# The B-spline basis, by de Boor's algorithm as scipy's BSpline evaluates it
# (``_deBoor_D``). It runs over three kinds of number: doubles (the basis at
# one point), polynomials in the distance from an interval's left knot (the
# basis on that interval, written in Horner form), and DuckDB expressions
# (the basis of a value when the knots are still placeholders in a learn
# stage). None is zero, so a term known to be zero is never written.

Poly = tuple[float, ...]


class _Floats:
    """Doubles at the point `x`; knots are doubles."""

    def __init__(self, x: float) -> None:
        self.x = x
        self.one = 1.0

    def left(self, xa: float) -> float:
        return self.x - xa

    def right(self, xb: float) -> float:
        return xb - self.x

    @staticmethod
    def add(a: float, b: float) -> float:
        return a + b

    @staticmethod
    def mul(a: float, b: float) -> float:
        return a * b

    @staticmethod
    def weight(h: float, xb: float, xa: float) -> float | None:
        return None if xb == xa else h / (xb - xa)


class _Polys:
    """Polynomials in ``s = x - origin``, coefficients from the constant up."""

    def __init__(self, origin: float) -> None:
        self.origin = origin
        self.one: Poly = (1.0,)

    def left(self, xa: float) -> Poly:
        return (self.origin - xa, 1.0)

    def right(self, xb: float) -> Poly:
        return (xb - self.origin, -1.0)

    @staticmethod
    def add(a: Poly, b: Poly) -> Poly:
        size = max(len(a), len(b))
        a, b = a + (0.0,) * (size - len(a)), b + (0.0,) * (size - len(b))
        return tuple(p + q for p, q in zip(a, b, strict=True))

    @staticmethod
    def mul(a: Poly, b: Poly) -> Poly:
        out = [0.0] * (len(a) + len(b) - 1)
        for i, p in enumerate(a):
            for j, q in enumerate(b):
                out[i + j] += p * q
        return tuple(out)

    @staticmethod
    def weight(h: Poly, xb: float, xa: float) -> Poly | None:
        return None if xb == xa else tuple(c / (xb - xa) for c in h)


class _Exprs:
    """DuckDB expressions of the value `x`; knots are expressions."""

    def __init__(self, x: Expression) -> None:
        self.x = x
        self.one = const(1.0)

    def left(self, xa: Expression) -> Expression:
        return self.x - xa

    def right(self, xb: Expression) -> Expression:
        return xb - self.x

    @staticmethod
    def add(a: Expression, b: Expression) -> Expression:
        return a + b

    @staticmethod
    def mul(a: Expression, b: Expression) -> Expression:
        return a * b

    @staticmethod
    def weight(h: Expression, xb: Expression, xa: Expression) -> Expression:
        return duckdb.CaseExpression(xb == xa, const(0.0)).otherwise(h / (xb - xa))


def _de_boor(ar: object, t: Sequence[Any], k: int, ell: int) -> list[Any]:
    """Return the `k` + 1 basis values nonzero on interval `ell`, in `ar`'s kind.

    They are the bases ``ell - k`` to ``ell``; None is zero. As scipy's
    ``_deBoor_D``: a division by two equal knots is skipped, leaving zero.
    """
    a = cast("_Floats", ar)  # any of the three: they share these methods
    h: list[Any] = [a.one] + [None] * k
    for j in range(1, k + 1):
        hh = h[:j]
        h[0] = None
        for n in range(1, j + 1):
            xb, xa = t[ell + n], t[ell + n - j]
            w = None if hh[n - 1] is None else a.weight(hh[n - 1], xb, xa)
            if w is None:
                h[n] = None
                continue
            term = a.mul(w, a.right(xb))
            h[n - 1] = term if h[n - 1] is None else a.add(h[n - 1], term)
            h[n] = a.mul(w, a.left(xa))
    return h


def _interval(t: Sequence[float], k: int, x: float) -> int:
    """Return the interval scipy evaluates `x` on: the last knot at or below it."""
    n = len(t) - k - 1
    return max(ell for ell in range(k, n) if t[ell] <= x)


def _horner(poly: Poly | None, s: Expression) -> Expression:
    """Write the polynomial in `s` in Horner form; zero when None."""
    if poly is None:
        return const(0.0)
    out = const(poly[-1])
    for c in reversed(poly[:-1]):
        out = const(c) + s * out
    return out


def _on_intervals(
    v: Expression,
    t: Sequence[Expression],
    k: int,
    i: int,
    piece: Callable[[int], Expression | None],
) -> Expression:
    """Write basis `i` of a value inside the knots: a ``CASE`` on its interval.

    The interval is the last whose left knot is at or below `v`, as scipy
    finds it; `piece` gives the basis on an interval (None for none written).
    """
    n = len(t) - k - 1
    top, bottom = min(n - 1, i + k), max(k, i)
    whens: list[tuple[Expression, Expression]] = []
    if top < n - 1:
        whens.append((v >= t[top + 1], const(0.0)))
    for ell in range(top, bottom - 1, -1):
        value = piece(ell)
        if value is not None:
            whens.append((v >= t[ell], value))
    # The last interval is always written, so there is at least one branch.
    case = duckdb.CaseExpression(*whens[0])
    for condition, value in whens[1:]:
        case = case.when(condition, value)
    return case.otherwise(const(0.0))


def _refusal(name: str, found: str, fix: str) -> Expression:
    """Return ``error(...)``: a refusal DuckDB raises when the row is fetched."""
    msg = (
        f"sq.features.spline found {found} in column {name!r}. Why: the "
        "B-spline basis is defined for numbers, and scikit-learn's "
        f"SplineTransformer refuses it too. Fix: {fix}"
    )
    return duckdb.FunctionExpression("error", const(msg))


class Spline(Step):
    """Write each column's B-spline basis: ``n_knots + degree - 1`` columns.

    Build it with `sq.features.spline <FeaturesGroup>`. As scikit-learn's
    ``SplineTransformer`` with its defaults: it learns `n_knots` knots over
    the column's present values, evenly from the minimum to the maximum
    (``"uniform"``) or at the quantiles ``0, 1 / (n_knots - 1), ..., 1``
    (``"quantile"``, numpy's ``"linear"``), and adds `degree` more on each
    side, spaced as the first two and the last two. Column ``x`` becomes
    ``x_sp_0`` ... ``x_sp_{n_knots + degree - 2}``, each a B-spline of
    `degree`, DOUBLE.

    The basis is written as SQL: on each interval between knots, one
    polynomial per column, in Horner form, its coefficients computed in
    Python by de Boor's recursion as scipy evaluates it, so equal knots give
    scipy's answer. Outside the first and last of the learned knots, each
    column holds its value at the nearer end, as ``extrapolation="constant"``
    (the first `degree` columns below, the last `degree` above, the others
    0). A constant column gives zeros, as scikit-learn.

    A missing value (NULL or NaN) or infinity is refused when the rows are
    fetched, naming the column, as scikit-learn's ``handle_missing="error"``;
    a column holding infinity, or no present value, is refused at learn.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns; by default the numeric ones.
    n_knots : int, default 5
        The number of knots learned, at least 2.
    degree : int, default 3
        The degree of the polynomials, from 0.
    knots : {"uniform", "quantile"}, default "uniform"
        Where the learned knots go.
    extrapolation : {"constant"}, default "constant"
        What a value outside the knots gets; the only one here.

    Attributes
    ----------
    knots_ : dict of str to list of float
        After learning, each column's knots, the added ones too, as
        scikit-learn's ``bsplines_[i].t``.

    Raises
    ------
    SqlearnError
        If a setting is not one of its values.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
    >>> pipe = sq.Pipeline([sq.features.spline(n_knots=3, degree=1)]).learn(data)
    >>> pipe.columns_out_
    ['x_sp_0', 'x_sp_1', 'x_sp_2']
    >>> pipe.apply(data, out="pandas").to_numpy().tolist()
    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    """

    static = True
    creates = DOUBLE

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        n_knots: int = 5,
        degree: int = 3,
        knots: str = "uniform",
        extrapolation: str = "constant",
    ) -> None:
        if knots not in KNOTS:
            names = ", ".join(repr(k) for k in KNOTS)
            msg = (
                f"sq.features.spline got knots={knots!r}. Why: the knots go "
                f"{names}, as SplineTransformer's. Fix: use one of them."
            )
            raise SqlearnError(msg)
        if extrapolation not in EXTRAPOLATIONS:
            msg = (
                f"sq.features.spline got extrapolation={extrapolation!r}. Why: "
                "only scikit-learn's default, 'constant', is built: a value "
                "outside the knots takes the basis at the nearer end. Fix: "
                "leave extrapolation= out."
            )
            raise SqlearnError(msg)
        super().__init__(cols=cols)
        self.n_knots = _whole("n_knots", n_knots, 2, "spline", "5")
        self.degree = _whole("degree", degree, 0, "spline", "3")
        self.knots = knots
        self.extrapolation = extrapolation

    def default_name(self) -> str:
        """Return ``spline``.

        Returns
        -------
        str
            ``spline``, whatever the settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.features.spline(knots="quantile").default_name()
        'spline'
        """
        return "spline"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.n_knots != 5:
            kwargs["n_knots"] = self.n_knots
        if self.degree != 3:
            kwargs["degree"] = self.degree
        if self.knots != "uniform":
            kwargs["knots"] = self.knots
        return call_repr("sq.features.spline", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns, refusing any that is not numeric.

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
        >>> sq.features.spline().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "write splines of", "a B-spline is a function of numbers"
        )

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the knots and whether the column holds infinity.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``knots``: every knot, the `degree` added on each side too, a
            list of DOUBLE computed from the minimum and maximum (uniform) or
            the quantiles, NULL when the column has no present value; and
            ``infinite`` (infinity where the column holds any, else 0).

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.features.spline().learn(duckdb.ColumnExpression("a")))
        ['knots', 'infinite']
        """
        n = self.n_knots
        if self.knots == "uniform":
            low, high = agg.min(x).cast(DOUBLE), agg.max(x).cast(DOUBLE)
            base = _linspace(low, high, n)
        else:
            base = [agg.quantile(x, q=_rank(i, n), method="linear") for i in range(n)]
        listed = duckdb.FunctionExpression("list_value", *_extend(base, self.degree))
        none = const(None).cast("DOUBLE[]")
        knots = duckdb.CaseExpression(base[0].isnull(), none).otherwise(listed)
        return {"knots": knots, "infinite": infinite(x)}

    def apply(self, x: Expression, learned: Learned) -> list[tuple[str, Expression]]:
        """Write the basis: one column per B-spline, labelled ``sp_0`` on.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        list of (str, duckdb.Expression)
            ``("sp_0", ...)`` to ``("sp_{n_knots + degree - 2}", ...)``, each
            DOUBLE; a missing or infinite value raises when fetched.

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
        >>> learned = Learned.values({"knots": [-1.0, 0.0, 1.0, 2.0], "infinite": 0.0})
        >>> step = sq.features.spline(n_knots=2, degree=1)
        >>> [label for label, _ in step.apply(x, learned)]
        ['sp_0', 'sp_1']
        """
        refuse_all_missing(x, learned, "knots")
        refuse_infinite(x, learned, "infinite")
        k = self.degree
        m = self.n_knots + k - 1
        size = self.n_knots + 2 * k
        listed = learned.knots
        v = x.cast(DOUBLE)
        if isinstance(listed, list):
            t = [float(e) for e in listed]
            inside, low, high = self._concrete(v, t)
            knot = [const(e) for e in t]
        else:
            knot = [
                duckdb.FunctionExpression(
                    "list_extract", cast("Expression", listed), const(e + 1)
                )
                for e in range(size)
            ]
            inside, low, high = self._placeholders(v, knot)
        name = x.get_name()
        first, last = knot[k], knot[size - k - 1]
        out = []
        for i in range(m):
            below = low[i] if i < k else const(0.0)
            above = high[i] if i >= m - k else const(0.0)
            value = (
                duckdb.CaseExpression(
                    is_missing(x),
                    _refusal(
                        name,
                        "a missing value (NULL or NaN)",
                        "impute the column first, such as with sq.impute() "
                        "before this step.",
                    ),
                )
                .when(
                    duckdb.FunctionExpression("isinf", v),
                    _refusal(
                        name,
                        "an infinite value",
                        "replace or drop the infinite values before this step.",
                    ),
                )
                .when(v < first, below)
                .when(v > last, above)
                .otherwise(inside[i])
            )
            out.append((f"sp_{i}", value))
        return out

    def _concrete(
        self, v: Expression, t: list[float]
    ) -> tuple[list[Expression], list[Expression], list[Expression]]:
        """Return the basis inside the knots, and at each end, from known knots."""
        k = self.degree
        n = len(t) - k - 1
        pieces: dict[int, list[Any]] = {}
        for ell in range(k, n):
            # An interval of no width is never chosen, except the last.
            if ell == n - 1 or t[ell] < t[ell + 1]:
                pieces[ell] = _de_boor(_Polys(t[ell]), t, k, ell)
        knot = [const(e) for e in t]

        def piece(i: int) -> Callable[[int], Expression | None]:
            def on(ell: int) -> Expression | None:
                if ell not in pieces:
                    return None
                return _horner(pieces[ell][i - ell + k], v - const(t[ell]))

            return on

        inside = [_on_intervals(v, knot, k, i, piece(i)) for i in range(n)]
        ends = []
        for at in (t[k], t[n]):
            ell = _interval(t, k, at)
            values = [0.0] * n
            for j, value in enumerate(_de_boor(_Floats(at), t, k, ell)):
                values[ell - k + j] = 0.0 if value is None else value
            ends.append([const(value) for value in values])
        return inside, ends[0], ends[1]

    def _placeholders(
        self, v: Expression, t: list[Expression]
    ) -> tuple[list[Expression], list[Expression], list[Expression]]:
        """Return the basis inside the knots, and at each end, from placeholders.

        The knots are references into the learn stage, so the basis is
        written as de Boor's recursion itself, each division by two knots
        guarded against their being equal.
        """
        k = self.degree
        n = len(t) - k - 1

        def basis(at: Expression) -> list[Expression]:
            pieces = {ell: _de_boor(_Exprs(at), t, k, ell) for ell in range(k, n)}

            def piece(i: int) -> Callable[[int], Expression | None]:
                def on(ell: int) -> Expression | None:
                    return cast("Expression | None", pieces[ell][i - ell + k])

                return on

            return [_on_intervals(at, t, k, i, piece(i)) for i in range(n)]

        return basis(v), basis(t[k]), basis(t[n])


class _Columns(TypedDict, total=False):
    """The general form's settings both shortcuts pass on."""

    cols: Selector | str | Sequence[str] | None


class FeaturesGroup(Group):
    """Make features: ``sq.features(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` picks the feature maker and has
    no default; each setting belongs to one method, and one given to the
    other is refused. Each shortcut is a method, and builds exactly the step
    the general form builds with it.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.features.polynomial("a", "b", degree=3)
    sq.features.polynomial(cols=['a', 'b'], degree=3)
    >>> sq.features(["a", "b"], method="polynomial", degree=3)
    sq.features.polynomial(cols=['a', 'b'], degree=3)
    >>> sq.features.spline("age", knots="quantile")
    sq.features.spline(cols='age', knots='quantile')
    """

    @overload
    def __call__(
        self,
        *names: object,
        method: Literal["polynomial"],
        degree: int | None = None,
        interaction_only: bool | None = None,
        include_bias: bool | None = None,
        n_knots: int | None = None,
        knots: str | None = None,
        extrapolation: str | None = None,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> Polynomial: ...

    @overload
    def __call__(
        self,
        *names: object,
        method: Literal["spline"],
        degree: int | None = None,
        interaction_only: bool | None = None,
        include_bias: bool | None = None,
        n_knots: int | None = None,
        knots: str | None = None,
        extrapolation: str | None = None,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> Spline: ...

    @overload
    def __call__(
        self,
        *names: object,
        method: str,
        degree: int | None = None,
        interaction_only: bool | None = None,
        include_bias: bool | None = None,
        n_knots: int | None = None,
        knots: str | None = None,
        extrapolation: str | None = None,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> Polynomial | Spline: ...

    def __call__(
        self,
        *names: object,
        method: str,
        degree: int | None = None,
        interaction_only: bool | None = None,
        include_bias: bool | None = None,
        n_knots: int | None = None,
        knots: str | None = None,
        extrapolation: str | None = None,
        cols: Selector | str | Sequence[str] | None = None,
    ) -> Polynomial | Spline:
        """Build the step that makes features by `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list.
        method : {"polynomial", "spline"}
            The feature maker; required.
        degree : int, optional
            The degree: 2 for ``polynomial``, 3 for ``spline`` by default.
        interaction_only : bool, optional
            ``polynomial`` only: products of distinct columns only.
        include_bias : bool, optional
            ``polynomial`` only: add the column ``1``.
        n_knots : int, optional
            ``spline`` only: the number of knots learned (5).
        knots : {"uniform", "quantile"}, optional
            ``spline`` only: where the knots go (``"uniform"``).
        extrapolation : {"constant"}, optional
            ``spline`` only: what a value outside the knots gets.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.

        Returns
        -------
        Polynomial or Spline
            The step.

        Raises
        ------
        SqlearnError
            If `method` is not one, names and `cols` are both given, a dict
            is given, a setting belongs to the other method, or a setting is
            not one of its values.
        TypeError
            If `method` is left out.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.features("x", method="spline", n_knots=4)
        sq.features.spline(cols='x', n_knots=4)
        """
        if method not in METHODS:
            known = ", ".join(repr(m) for m in METHODS)
            msg = (
                f"sq.features got method={method!r}, which is not a method. "
                f"Why: the feature makers are {known}. Fix: use one of them, "
                "or write your own feature as sq.Step(apply=...)."
            )
            raise SqlearnError(msg)
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        others = (
            {"n_knots": n_knots, "knots": knots, "extrapolation": extrapolation}
            if method == "polynomial"
            else {"interaction_only": interaction_only, "include_bias": include_bias}
        )
        for setting, value in others.items():
            if value is not None:
                msg = (
                    f"sq.features got method={method!r} and {setting}={value!r}. "
                    f"Why: {setting} is a setting of the other method, not of "
                    f"{method}. Fix: leave {setting}= out, or use the other "
                    "method."
                )
                raise SqlearnError(msg)
        if method == "polynomial":
            return Polynomial(
                cols=columns,
                degree=2 if degree is None else degree,
                interaction_only=(
                    False if interaction_only is None else interaction_only
                ),
                include_bias=False if include_bias is None else include_bias,
            )
        return Spline(
            cols=columns,
            n_knots=5 if n_knots is None else n_knots,
            degree=3 if degree is None else degree,
            knots="uniform" if knots is None else knots,
            extrapolation="constant" if extrapolation is None else extrapolation,
        )

    def polynomial(
        self,
        *names: object,
        degree: int = 2,
        interaction_only: bool = False,
        include_bias: bool = False,
        **kw: Unpack[_Columns],
    ) -> Polynomial:
        """Multiply columns into every product up to `degree` (``method="polynomial"``).

        As scikit-learn's ``PolynomialFeatures``, without the column ``1`` by
        default: ``a``, ``b`` and degree 2 make ``a``, ``b``, ``a^2``,
        ``a*b``, ``b^2``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        degree : int, default 2
            The largest number of factors in a term.
        interaction_only : bool, default False
            Only products of distinct columns.
        include_bias : bool, default False
            Add the column ``1``.
        **kw : object
            The general form's ``cols``.

        Returns
        -------
        Polynomial
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.features.polynomial("a", "b", interaction_only=True)
        sq.features.polynomial(cols=['a', 'b'], interaction_only=True)
        """
        return self(
            *names,
            method="polynomial",
            degree=degree,
            interaction_only=interaction_only,
            include_bias=include_bias,
            **kw,
        )

    def spline(
        self,
        *names: object,
        n_knots: int = 5,
        degree: int = 3,
        knots: str = "uniform",
        **kw: Unpack[_Columns],
    ) -> Spline:
        """Write each column's B-spline basis (``method="spline"``).

        As scikit-learn's ``SplineTransformer``: ``x`` becomes ``x_sp_0`` ...
        ``x_sp_{n_knots + degree - 2}``; outside the learned knots, the values
        at the nearer end.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        n_knots : int, default 5
            The number of knots learned, at least 2.
        degree : int, default 3
            The degree of the polynomials.
        knots : {"uniform", "quantile"}, default "uniform"
            Where the learned knots go.
        **kw : object
            The general form's ``cols``.

        Returns
        -------
        Spline
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.features.spline("age", n_knots=4)
        sq.features.spline(cols='age', n_knots=4)
        """
        return self(
            *names, method="spline", n_knots=n_knots, degree=degree, knots=knots, **kw
        )


features = FeaturesGroup("features")
"""The feature makers: ``sq.features(...)``, ``sq.features.polynomial(...)``."""
