"""The aggregates: what a step learns from a column, each by one name.

An aggregate is a value a step takes (``sq.impute("age", value=sq.agg.median)``)
and, given a column, the expression a step learns
(``{"m": sq.agg.median(x)}``). Missing values (NULL, and NaN in a float
column) are left out of every one. The exact quantiles and the mode are
markers the compositor computes in stages of its own (see `sqlearn._compose`).
"""

from collections.abc import Callable, Mapping
from typing import overload

import duckdb
from duckdb import Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import MODE, QUANTILE, const, is_missing

__all__ = [
    "Aggregate",
    "approx_quantile",
    "count",
    "distinct",
    "iqr",
    "lookup",
    "max",
    "maxabs",
    "mean",
    "median",
    "min",
    "mode",
    "present",
    "quantile",
    "range",
    "std",
    "var",
]

METHODS = ("linear", "averaged_inverted_cdf")
"""The quantile methods built, by numpy's names."""

_REQUIRED = object()
"""The default of a param that has none: it must be given."""


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def present(x: Expression) -> Expression:
    """Return `x` as DOUBLE, or NULL where it is missing (NULL or NaN).

    Aggregates skip NULL, so wrapping a column in this makes an aggregate run
    over the non-missing values only. Every aggregate taking numbers does so.

    Parameters
    ----------
    x : duckdb.Expression
        The column.

    Returns
    -------
    duckdb.Expression
        ``CASE WHEN is_missing(x) THEN NULL ELSE x::DOUBLE END``.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn.agg.aggregates import present
    >>> rel = duckdb.sql("SELECT * FROM (VALUES (1), (NULL)) t(a)")
    >>> rel.select(present(duckdb.ColumnExpression("a"))).fetchall()
    [(1.0,), (None,)]
    """
    return duckdb.CaseExpression(
        is_missing(x),
        duckdb.ConstantExpression(None),
    ).otherwise(x.cast("DOUBLE"))


def _present_value(x: Expression) -> Expression:
    """Return `x` in its own type, or NULL where it is NaN (NULL stays NULL).

    For the aggregates taking any type: only FLOAT and DOUBLE hold NaN, and
    text is never cast.
    """
    floating = _fn("typeof", x).isin(const("FLOAT"), const("DOUBLE"))
    nan = floating & _fn("isnan", x.try_cast("DOUBLE"))
    return duckdb.CaseExpression(nan, const(None)).otherwise(x)


def _check_q(name: str, q: object) -> float:
    if isinstance(q, bool) or not isinstance(q, int | float) or not 0 <= q <= 1:
        msg = (
            f"sq.agg.{name} got q={q!r}, which is not a number between 0 and "
            "1. Why: q is the share of the values at or below the quantile. "
            f"Fix: give q as a number such as sq.agg.{name}(q=0.9)."
        )
        raise SqlearnError(msg)
    return float(q)


def _check_method(name: str, method: object) -> str:
    if method not in METHODS:
        msg = (
            f"sq.agg.{name} got method={method!r}, which is not built. Why: "
            f"the methods built are {METHODS[0]!r} and {METHODS[1]!r}, by "
            "numpy's names. Fix: use one of them."
        )
        raise SqlearnError(msg)
    return str(method)


def _check_pair(name: str, q: object) -> tuple[float, float]:
    pair = tuple(q) if isinstance(q, list | tuple) else ()
    if len(pair) != 2:
        msg = (
            f"sq.agg.{name} got q={q!r}, which is not a pair. Why: the spread "
            "is between a low and a high quantile. Fix: give "
            f"sq.agg.{name}(q=(0.25, 0.75))."
        )
        raise SqlearnError(msg)
    low, high = (_check_q(name, v) for v in pair)
    if low > high:
        msg = (
            f"sq.agg.{name} got q={q!r}, a pair whose low quantile is above "
            "its high one. Why: the spread is the high one less the low one. "
            f"Fix: give the low one first, such as sq.agg.{name}(q=(0.25, 0.75))."
        )
        raise SqlearnError(msg)
    return low, high


_CHECKS: dict[str, Callable[[str, object], object]] = {
    "q": _check_q,
    "method": _check_method,
}


class Aggregate:
    """An aggregate: a value a step takes, and the expression it learns.

    Called with a column, it returns the expression; called without one, a
    new aggregate with the params given merged in. Two aggregates with the
    same name and params are equal and print alike, so an aggregate is a
    setting the learning store and a search can key on.

    Parameters
    ----------
    name : str
        The name after ``sq.agg.``.
    build : callable
        Takes the column and every param by keyword; returns the expression.
    defaults : mapping of str to object, optional
        Each param the aggregate takes, with its default; a required param
        has none.
    numeric_only : bool, default True
        Whether the aggregate needs numbers (False: any type, such as text).
    params : mapping of str to object, optional
        The params set so far, defaults left out.
    checks : mapping of str to callable, optional
        Per param, a check returning its normalised value or raising.
    doc : str, optional
        The docstring of this aggregate.

    Attributes
    ----------
    name : str
        The name after ``sq.agg.``.
    params : dict of str to object
        The params set, defaults left out.
    numeric_only : bool
        Whether the aggregate needs numbers.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> sq.agg.quantile(q=0.9)
    sq.agg.quantile(q=0.9)
    >>> sq.agg.quantile(q=0.9) == sq.agg.quantile(q=0.9, method="linear")
    True
    >>> str(sq.agg.mean(duckdb.ColumnExpression("a"))).startswith("favg(")
    True
    """

    def __init__(
        self,
        name: str,
        build: Callable[..., Expression],
        *,
        defaults: Mapping[str, object] | None = None,
        numeric_only: bool = True,
        params: Mapping[str, object] | None = None,
        checks: Mapping[str, Callable[[str, object], object]] | None = None,
        doc: str | None = None,
    ) -> None:
        self.name = name
        self.numeric_only = numeric_only
        self.params: dict[str, object] = dict(params or {})
        self._build = build
        self._defaults = dict(defaults or {})
        self._checks = {**_CHECKS, **(checks or {})}
        if doc is not None:
            self.__doc__ = doc

    def _merge(self, given: Mapping[str, object]) -> dict[str, object]:
        unknown = sorted(set(given) - set(self._defaults))
        if unknown:
            takes = ", ".join(repr(p) for p in sorted(self._defaults)) or "none"
            msg = (
                f"sq.agg.{self.name} got the param {unknown[0]!r}, which it "
                f"does not take. Why: the params it takes are: {takes}. "
                f"Fix: remove {unknown[0]!r}."
            )
            raise SqlearnError(msg)
        merged = dict(self.params)
        for key, value in given.items():
            check = self._checks.get(key)
            normal = check(self.name, value) if check is not None else value
            if normal == self._defaults[key]:
                merged.pop(key, None)
            else:
                merged[key] = normal
        return merged

    @overload
    def __call__(self, x: None = None, **params: object) -> "Aggregate": ...

    @overload
    def __call__(self, x: Expression, **params: object) -> Expression: ...

    def __call__(
        self,
        x: object = None,
        **params: object,
    ) -> "Expression | Aggregate":
        """Return the expression over `x`, or, without `x`, a new aggregate.

        Parameters
        ----------
        x : duckdb.Expression, optional
            The column to aggregate.
        **params : object
            The aggregate's params, by keyword.

        Returns
        -------
        duckdb.Expression or Aggregate
            The expression with `x`; else the aggregate with `params` set.

        Raises
        ------
        SqlearnError
            If a param is unknown or invalid, `x` is not an expression, or a
            required param is missing when `x` is given.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> sq.agg.quantile(q=0.25)
        sq.agg.quantile(q=0.25)
        >>> expr = sq.agg.quantile(duckdb.ColumnExpression("a"), q=0.25)
        >>> str(expr).startswith("__sqlearn_quantile(")
        True
        """
        merged = self._merge(params)
        if x is None:
            return Aggregate(
                self.name,
                self._build,
                defaults=self._defaults,
                numeric_only=self.numeric_only,
                params=merged,
                checks=self._checks,
                doc=self.__doc__,
            )
        if not isinstance(x, Expression):
            msg = (
                f"sq.agg.{self.name} got {x!r} where a column expression goes. "
                "Why: the column comes first and every param by keyword. Fix: "
                f"give params by keyword, such as sq.agg.{self.name}(q=0.9), "
                f"or a column, such as sq.agg.{self.name}(x)."
            )
            raise SqlearnError(msg)
        full = {**self._defaults, **merged}
        for key, value in full.items():
            if value is _REQUIRED:
                msg = (
                    f"sq.agg.{self.name} needs the param {key!r}, which was "
                    f"not given. Why: it has no default. Fix: give it by "
                    f"keyword, such as sq.agg.{self.name}(x, {key}=0.9)."
                )
                raise SqlearnError(msg)
        return self._build(x, **full)

    def __repr__(self) -> str:
        """Return ``sq.agg.<name>``, with the params set, sorted, if any."""
        if not self.params:
            return f"sq.agg.{self.name}"
        inner = ", ".join(f"{k}={v!r}" for k, v in sorted(self.params.items()))
        return f"sq.agg.{self.name}({inner})"

    def __eq__(self, other: object) -> bool:
        """Say whether `other` is an aggregate of the same name and params."""
        if not isinstance(other, Aggregate):
            return NotImplemented
        return (self.name, self.params) == (other.name, other.params)

    def __hash__(self) -> int:
        """Hash the name and params, as equality compares them."""
        return hash((self.name, tuple(sorted(self.params.items()))))


def _quantile(x: Expression, q: float, method: str) -> Expression:
    return _fn(QUANTILE, present(x), const(float(q)), const(method))


def _iqr(x: Expression, q: tuple[float, float]) -> Expression:
    return _quantile(x, q[1], "linear") - _quantile(x, q[0], "linear")


def _distinct(x: Expression) -> Expression:
    keys = _fn("list_sort", _fn("map_keys", _fn("histogram", _present_value(x))))
    return duckdb.CoalesceOperator(keys, duckdb.ConstantExpression([]))


mean = Aggregate(
    "mean",
    lambda x: _fn("favg", present(x)),
    doc="""The mean, summed with compensation (DuckDB's ``favg``, ADR 0033).

    It lands on the double nearest the exact mean where the plain ``avg``
    drifted by 119 ULPs (``validation/``). DOUBLE; NaN, not infinity, when the
    data holds an infinity or the sum overflows.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> sq.agg.mean
    sq.agg.mean
    >>> str(sq.agg.mean(duckdb.ColumnExpression("a"))).startswith("favg(")
    True
    """,
)
median = Aggregate(
    "median",
    lambda x: _quantile(x, 0.5, "linear"),
    doc="""The exact median, by sorting, so it learns larger than memory (ADR 0032).

    ``quantile(q=0.5)``: the middle value, or halfway between the two middle
    ones, as DOUBLE. It may sit anywhere in a learned expression.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> sq.agg.median
    sq.agg.median
    >>> str(sq.agg.median(duckdb.ColumnExpression("a"))).startswith(
    ...     "__sqlearn_quantile("
    ... )
    True
    """,
)
quantile = Aggregate(
    "quantile",
    _quantile,
    defaults={"q": _REQUIRED, "method": "linear"},
    doc="""The exact quantile `q`, by sorting, so it learns larger than memory.

    Params: ``q``, between 0 and 1; ``method``, numpy's name of how a
    quantile between two values is found: ``"linear"`` (numpy's default) or
    ``"averaged_inverted_cdf"`` (scikit-learn's ``KBinsDiscretizer``). Every
    quantile of a learn stage shares one sort. DOUBLE.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> sq.agg.quantile(q=0.9)
    sq.agg.quantile(q=0.9)
    >>> expr = sq.agg.quantile(duckdb.ColumnExpression("a"), q=0.9)
    >>> str(expr).endswith("0.9::DOUBLE, 'linear')")
    True
    """,
)
approx_quantile = Aggregate(
    "approx_quantile",
    lambda x, q: _fn("approx_quantile", present(x), const(float(q)).cast("FLOAT")),
    defaults={"q": _REQUIRED},
    doc="""DuckDB's approximate quantile `q`: never chosen for the user.

    Its error against the exact quantile is measured in ``validation/``; it
    has no bound. ``approx_quantile(q=0.5)`` is the approximate median.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.agg.approx_quantile(duckdb.ColumnExpression("a"), q=0.5)).startswith(
    ...     "approx_quantile("
    ... )
    True
    """,
)
iqr = Aggregate(
    "iqr",
    _iqr,
    defaults={"q": (0.25, 0.75)},
    checks={"q": _check_pair},
    doc="""The spread between two exact quantiles: ``quantile(q[1]) - quantile(q[0])``.

    ``q`` defaults to ``(0.25, 0.75)``, the interquartile range, as
    scikit-learn's ``RobustScaler`` has its ``quantile_range``; both use the
    linear method.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.agg.iqr(q=(0.1, 0.9))
    sq.agg.iqr(q=(0.1, 0.9))
    """,
)
mode = Aggregate(
    "mode",
    lambda x: _fn(MODE, _present_value(x)),
    numeric_only=False,
    doc="""The most frequent value; a tie goes to the smallest, as scikit-learn.

    Counted with a ``GROUP BY``, which spills to disk. Any type; the result
    keeps the column's type.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.agg.mode(duckdb.ColumnExpression("a"))).startswith("__sqlearn_mode(")
    True
    """,
)
min = Aggregate(
    "min",
    lambda x: _fn("min", _present_value(x)),
    numeric_only=False,
    doc="""The smallest value. Any type; the result keeps the column's type.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.agg.min.numeric_only
    False
    """,
)
max = Aggregate(
    "max",
    lambda x: _fn("max", _present_value(x)),
    numeric_only=False,
    doc="""The largest value. Any type; the result keeps the column's type.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.agg.max.numeric_only
    False
    """,
)
range = Aggregate(
    "range",
    lambda x: _fn("max", present(x)) - _fn("min", present(x)),
    doc="""The largest value less the smallest, as DOUBLE (MinMaxScaler's spread).

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.agg.range
    sq.agg.range
    """,
)
maxabs = Aggregate(
    "maxabs",
    lambda x: _fn("max", _fn("abs", present(x))),
    doc="""The largest absolute value, as DOUBLE (MaxAbsScaler's spread).

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.agg.maxabs
    sq.agg.maxabs
    """,
)
std = Aggregate(
    "std",
    lambda x: _fn("stddev_pop", present(x)),
    doc="""The population standard deviation (``ddof=0``), DuckDB's ``stddev_pop``.

    As StandardScaler's. A two-pass compensated variance is issue #28.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.agg.std(duckdb.ColumnExpression("a"))).startswith("stddev_pop(")
    True
    """,
)
var = Aggregate(
    "var",
    lambda x: _fn("var_pop", present(x)),
    doc="""The population variance (``ddof=0``), DuckDB's ``var_pop``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> str(sq.agg.var(duckdb.ColumnExpression("a"))).startswith("var_pop(")
    True
    """,
)
count = Aggregate(
    "count",
    lambda x: _fn("count", _present_value(x)),
    numeric_only=False,
    doc="""The number of present values (neither NULL nor NaN). Any type.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql("SELECT * FROM (VALUES ('a'), (NULL)) t(c)")
    >>> rel.aggregate([sq.agg.count(duckdb.ColumnExpression("c"))]).fetchall()
    [(1,)]
    """,
)
distinct = Aggregate(
    "distinct",
    _distinct,
    numeric_only=False,
    doc="""The sorted distinct values, without NULL and NaN; an empty list for none.

    Counted in a hash table (``histogram``), so the memory grows with the
    number of distinct values, not of rows: the encoders' categories.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql("SELECT * FROM (VALUES ('b'), ('a'), (NULL)) t(c)")
    >>> rel.aggregate([sq.agg.distinct(duckdb.ColumnExpression("c"))]).fetchall()
    [(['a', 'b'],)]
    """,
)

_BY_NAME = {
    a.name: a
    for a in (
        mean,
        median,
        quantile,
        approx_quantile,
        iqr,
        mode,
        min,
        max,
        range,
        maxabs,
        std,
        var,
        count,
        distinct,
    )
}


def lookup(name: str) -> Aggregate | None:
    """Return the aggregate a string names, or None when it names none.

    Parameters
    ----------
    name : str
        A name such as ``"median"``.

    Returns
    -------
    Aggregate or None
        The aggregate (``"median"`` is ``sq.agg.median``); None for any other
        string, which a step reads as a constant.

    Examples
    --------
    >>> from sqlearn.agg.aggregates import lookup
    >>> lookup("median")
    sq.agg.median
    >>> lookup("Median") is None
    True
    """
    return _BY_NAME.get(name)
