"""Impute: fill the missing values of columns, ``sq.impute`` and its shortcuts."""

import datetime
import decimal
from collections.abc import Mapping, Sequence
from typing import TypedDict, Unpack, cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import INTEGER, DuckDBPyType

from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, is_missing
from sqlearn._group import Group, Unset, call_repr, column_names, columns_arg
from sqlearn._selectors import (
    Schema,
    Selector,
    _numeric,
    is_text,
    to_selector,
)
from sqlearn._step import Learned, Output, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing._missing import (
    infinite,
    refuse_all_missing,
    refuse_infinite,
)

__all__ = ["Impute", "ImputeGroup", "impute"]

_SHORTCUTS = ("mean", "median", "mode")
"""The aggregates with a shortcut of their own, named after them."""

_KEEPS_TYPE = ("mode", "min", "max")
"""The aggregates taking any type whose result keeps the column's type."""

_CONSTANTS = (
    str,
    int,
    float,
    bool,
    decimal.Decimal,
    datetime.date,
    datetime.datetime,
)
"""The Python types a constant fill value may have."""


class _Text(str):
    """Text that names an aggregate, given as ``sq.fn.const``: a constant.

    Kept apart so that rebuilding the step from its settings (as a search
    does) does not read it as the aggregate, and printed as it was given.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return f"sq.fn.const({str.__repr__(self)})"


_MEDIAN = Unset("median")
"""The default value of `sq.impute`, told apart from ``value="median"`` given."""

_REFUSED = object()
"""Marks an expression that holds no constant."""


def _resolve(value: object) -> object:
    """Return the fill value `value` stands for, refusing what is none."""
    if value is None or isinstance(value, agg.Aggregate | _Text):
        return value
    if isinstance(value, Expression):
        raw = getattr(value, "value", _REFUSED)  # a constant holds its value
        if raw is _REFUSED or isinstance(raw, list | dict):
            msg = (
                f"sq.impute got value={value}, an expression that is not a "
                "constant. Why: a fill value is an aggregate, its name, a "
                "constant or None. Fix: give a constant, such as "
                "sq.fn.const('unknown'), or an aggregate, such as sq.agg.median."
            )
            raise SqlearnError(msg)
        if isinstance(raw, str):
            return _Text(raw) if agg.lookup(raw) else raw
        value = raw
    if isinstance(value, str):
        return agg.lookup(value) or value
    if not isinstance(value, _CONSTANTS):
        msg = (
            f"sq.impute got value={value!r}, which is not a fill value. Why: a "
            "fill value is an aggregate (sq.agg.median), its name ('median'), "
            "a constant (0, 'unknown') or None. Fix: give one of those; for a "
            "value per column, give a dict as the first argument."
        )
        raise SqlearnError(msg)
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, int | float | decimal.Decimal) and not isinstance(
        value, bool
    )


def _missing(x: Expression) -> Expression:
    """Return whether `x` is NULL, or NaN in a FLOAT or DOUBLE column.

    Unlike `sqlearn.fn.is_missing`, it takes a column of any type: text is
    never cast to a number.
    """
    floating = duckdb.FunctionExpression("typeof", x).isin(
        const("FLOAT"), const("DOUBLE")
    )
    nan = floating & duckdb.FunctionExpression("isnan", x.try_cast("DOUBLE"))
    return x.isnull() | nan


def _column_kind(dtype: DuckDBPyType) -> str:
    """Return the kind of a column's type: numeric, text, boolean, date..."""
    if _numeric().resolve([("c", dtype)]):
        return "numeric"
    if is_text(dtype):
        return "text"
    name = str(dtype)
    if name.startswith("TIMESTAMP"):
        return "timestamp"
    return {"BOOLEAN": "boolean", "DATE": "date"}.get(name, name)


def _constant_kind(value: object) -> str:
    """Return the kind of column a constant suits (as `_column_kind` names it)."""
    if isinstance(value, bool):
        return "boolean"
    if _is_number(value):
        return "numeric"
    if isinstance(value, str):
        return "text"
    if isinstance(value, datetime.datetime):
        return "timestamp"
    return "date"  # the last of _CONSTANTS


def _fills(value: agg.Aggregate) -> bool:
    """Say whether an aggregate's result can fill a column at all."""
    return value.numeric_only or value.name in _KEEPS_TYPE


def _suits(value: object, dtype: DuckDBPyType) -> bool:
    """Say whether `value` can fill a column of type `dtype`."""
    if value is None:
        return True
    if isinstance(value, agg.Aggregate):
        if value.numeric_only:
            return _column_kind(dtype) == "numeric"
        return value.name in _KEEPS_TYPE
    return _constant_kind(value) == _column_kind(dtype)


class Impute(Step):
    """Fill the missing values (NULL, or NaN in a float column) of columns.

    Build it with `sq.impute <ImputeGroup>` or one of its shortcuts. The fill
    value is learned with an aggregate (the median, mean or mode of the
    present values) or is a constant; a dict gives each column its own.
    Filled by an aggregate of numbers or by a number, the column comes out
    DOUBLE, as scikit-learn returns floats; filled by text or the mode, it
    keeps its type. With `indicator` it also creates ``<column>_missing``
    (1 where the value was missing, else 0) for each column that had a
    missing value at `learn`, as scikit-learn's ``add_indicator=True``.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to fill; by default those the value suits: numbers for
        an aggregate of numbers or a number, columns of its own type for any
        other constant (text, a bool, a date, a timestamp), every column for
        the mode, ``min``, ``max`` or None. With a dict, its keys.
    value : Aggregate, str, constant, None or dict, default "median"
        What to fill with: an aggregate (``sq.agg.median``), a string naming
        one (``"median"``), a constant (any other string, a number, or
        ``sq.fn.const(...)``), or None to leave the values missing. A dict
        maps each column to its own value. Stored resolved: ``"median"`` is
        kept as ``sq.agg.median``.
    indicator : bool, default False
        Also create ``<column>_missing`` (INTEGER 0/1) for each column with a
        missing value at `learn`; the step is then dynamic. Not with a dict,
        which is one static step.
    keep : bool, default False
        Keep the input column and add the filled one beside it.
    suffix : str, optional
        Suffix of the filled column when `keep` is True; defaults to the
        step's name.

    Attributes
    ----------
    value_ : dict of str to object
        After learning, each column's fill value, for an aggregate.
    missing_ : dict of str to bool
        After learning with `indicator`, whether each column had a missing
        value.

    Raises
    ------
    SqlearnError
        If `value` is not a fill value, a dict is given with other `cols`
        than its keys, or a dict with `indicator`.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"age": [10.0, None, 30.0, 40.0]})
    >>> pipe = sq.Pipeline([sq.impute.median()]).learn(data)
    >>> pipe["median"].value_
    {'age': 30.0}
    >>> pipe.apply(data, out="pandas")["age"].tolist()
    [10.0, 30.0, 30.0, 40.0]
    """

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        value: object = "median",
        indicator: bool = False,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        resolved: object
        if isinstance(value, Mapping):
            if indicator:
                msg = (
                    f"sq.impute got the dict {value!r} and indicator=True. "
                    "Why: a dict step is one static step, choosing a value "
                    "per column, and the indicator would make it dynamic. "
                    "Fix: leave indicator out of the dict step and add "
                    "sq.impute.indicator(...) as its own step before it."
                )
                raise SqlearnError(msg)
            resolved = {str(k): _resolve(v) for k, v in value.items()}
            keys = list(resolved)
            if cols is None:
                cols = keys
            elif column_names(cols) != keys:
                msg = (
                    f"sq.impute got the dict {value!r} and cols={cols!r}. Why: "
                    "a dict names the columns itself, by its keys. Fix: leave "
                    "cols= out."
                )
                raise SqlearnError(msg)
        else:
            resolved = _resolve(value)
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.value = resolved
        self.indicator = indicator
        self.static = not indicator
        self.dynamic = indicator
        self.keeps_inputs = indicator  # the filled (or unfilled) input stays
        self.creates = INTEGER if indicator else None
        # With keep and a fill value, the filled copy is made beside the flag.
        self.copies_inputs = indicator and keep and resolved is not None

    def __getstate__(self) -> dict[str, object]:
        """Return the state to pickle: a DuckDB type does not pickle."""
        state: dict[str, object] = dict(self.__dict__)
        state.pop("creates", None)
        return state

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore a pickled step, its created type from `indicator`."""
        self.__dict__.update(state)
        self.creates = INTEGER if self.indicator else None

    def _value_of(self, column: str) -> object:
        if isinstance(self.value, Mapping):
            return self.value[column]
        return self.value

    def default_name(self) -> str:
        """Return the shortcut these settings match, else ``impute``.

        Returns
        -------
        str
            ``mean``, ``median`` or ``mode`` for those aggregates;
            ``constant`` for a constant; ``indicator`` for no value with the
            indicator; ``impute`` for anything else (a dict, another
            aggregate).

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute(value="mean").default_name()
        'mean'
        >>> sq.impute(value=sq.agg.quantile(q=0.9)).default_name()
        'impute'
        """
        value = self.value
        if isinstance(value, Mapping):
            return "impute"
        if isinstance(value, agg.Aggregate):
            named = agg.lookup(value.name)
            return (
                value.name if value.name in _SHORTCUTS and value == named else "impute"
            )
        if value is None:
            return "indicator" if self.indicator else "impute"
        return "constant"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        name = self.default_name()
        args: list[object] = []
        kwargs: dict[str, object] = {}
        if self.cols is not None and not isinstance(self.value, Mapping):
            kwargs["cols"] = self.cols
        if name in _SHORTCUTS or name == "indicator":
            path = f"sq.impute.{name}"
        elif name == "constant":
            path = "sq.impute.constant"
            args.append(self.value)
        elif isinstance(self.value, Mapping):
            path = "sq.impute"
            args.append(self.value)
        else:
            path, kwargs["value"] = "sq.impute", self.value
        if self.indicator and name != "indicator":
            kwargs["indicator"] = True
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr(path, *args, **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to fill, refusing any its value does not suit.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns, in schema order.

        Raises
        ------
        StepError
            If a chosen column's value cannot fill it: an aggregate of
            numbers on a column of another type, an aggregate whose result
            fills no column (``count``, ``distinct``), or a constant of
            another kind (text into numbers, a date into text...).

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE, VARCHAR
        >>> sq.impute().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        if self.cols is not None:
            chosen = to_selector(self.cols).resolve(schema)
        elif isinstance(self.value, agg.Aggregate) and not _fills(self.value):
            chosen = [c for c, _ in schema]  # to be refused, by name
        else:
            chosen = [c for c, t in schema if _suits(self.value, t)]
        types: dict[str, DuckDBPyType] = dict(schema)
        for c in chosen:
            _check_suits(c, types[c], self._value_of(c))
        return chosen

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the fill value, and whether a value is missing, per column.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            For an aggregate, ``value`` (it, over the present values) and,
            when it takes numbers, ``infinite`` (infinity where the column
            holds any, else 0); with `indicator`, ``missing`` (whether any
            value is missing). A constant learns nothing.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.impute.mean().learn(duckdb.ColumnExpression("a")))
        ['value', 'infinite']
        >>> list(sq.impute.constant(0).learn(duckdb.ColumnExpression("a")))
        []
        """
        value = self._value_of(x.get_name())
        out: dict[str, Expression] = {}
        if isinstance(value, agg.Aggregate):
            out["value"] = value(x)
            if value.numeric_only:
                out["infinite"] = infinite(x)
        if self.indicator:
            out["missing"] = duckdb.FunctionExpression("bool_or", _missing(x))
        return out

    def apply(self, x: Expression, learned: Learned) -> Output:
        """Replace the missing values; with `indicator`, flag where they were.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression or list of (str, duckdb.Expression)
            The filled column. With `indicator`, pairs instead: the filled
            column (label ``""``) and, when the column had a missing value
            at `learn`, the label ``missing``: INTEGER 1 where it is missing.

        Raises
        ------
        StepError
            If an aggregate's column had no present value, or one of numbers
            met infinity.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> x = duckdb.ColumnExpression("a")
        >>> learned = Learned.values({"value": 2.5, "infinite": 0.0})
        >>> "2.5" in str(sq.impute().apply(x, learned))
        True
        """
        value = self._value_of(x.get_name())
        filled = _fill(x, value, learned)
        if not self.indicator:
            return filled
        out: list[tuple[str, Expression]] = []
        if not (self.keep and value is None):  # with keep, x is there already
            out.append(("", filled))
        if learned.raw("missing") is True:
            flag = duckdb.CaseExpression(_missing(x), const(1)).otherwise(const(0))
            out.append(("missing", flag.cast(INTEGER)))
        return out


def _fill(x: Expression, value: object, learned: Learned) -> Expression:
    """Return `x` with its missing values replaced by `value`."""
    if value is None:
        return x
    if isinstance(value, agg.Aggregate):
        refuse_all_missing(x, learned, "value")
        if not value.numeric_only:
            return duckdb.CaseExpression(_missing(x), learned.value).otherwise(x)
        refuse_infinite(x, learned, "infinite")
        filled = duckdb.CaseExpression(is_missing(x), learned.value)
        return filled.otherwise(x.cast("DOUBLE"))
    if _is_number(value):
        filled = duckdb.CaseExpression(is_missing(x), const(value).cast("DOUBLE"))
        return filled.otherwise(x.cast("DOUBLE"))
    if isinstance(value, str):
        return duckdb.CaseExpression(x.isnull(), const(str(value))).otherwise(x)
    return duckdb.CaseExpression(_missing(x), const(value)).otherwise(x)


def _check_suits(column: str, dtype: DuckDBPyType, value: object) -> None:
    """Refuse a fill value whose type does not suit the column."""
    if _suits(value, dtype):
        return
    if isinstance(value, agg.Aggregate) and not _fills(value):
        msg = (
            f"cannot impute column {column!r}, which is {dtype}, with "
            f"{value!r}. Why: its result is not a value of the column (a "
            "count, or a list of values), so it cannot fill one. Fix: use an "
            "aggregate whose result is a value, such as sq.agg.median, "
            "sq.agg.mode, sq.agg.min or sq.agg.max."
        )
    elif isinstance(value, agg.Aggregate):
        msg = (
            f"cannot impute column {column!r}, which is {dtype} (text or "
            f"another non-numeric type), with {value!r}, which takes numbers. "
            "Fix: choose numeric columns with cols=, fill it with "
            "sq.impute.mode or a constant, or drop it before this step."
        )
    else:
        kind = _constant_kind(value)
        msg = (
            f"cannot fill column {column!r}, which is {dtype}, with the "
            f"{kind} {value!r}. Why: a column holds one type, and a {kind} "
            f"is not {dtype}. Fix: give a constant of the column's type, or "
            f"choose {kind} columns with cols=."
        )
    raise StepError(msg, step="", position=0)


class _Columns(TypedDict, total=False):
    """The general form's settings every shortcut passes on."""

    cols: Selector | str | Sequence[str] | None
    keep: bool
    suffix: str | None


class _Settings(_Columns, total=False):
    """The settings a filling shortcut passes on: the indicator too."""

    indicator: bool


class ImputeGroup(Group):
    """Fill missing values: ``sq.impute(cols, value=...)`` and its shortcuts.

    Called, it is the general form: ``value`` is an aggregate, its name, a
    constant or None, and a dict as the first argument gives each column its
    own. Each shortcut is a preset of ``value``, and builds exactly the step
    the general form builds with it.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.impute.median("age")
    sq.impute.median(cols='age')
    >>> sq.impute("age", value="median")
    sq.impute.median(cols='age')
    >>> sq.impute({"age": "median", "city": "unknown"})
    sq.impute({'age': sq.agg.median, 'city': 'unknown'})
    """

    def __call__(
        self,
        *names: object,
        value: object = _MEDIAN,
        indicator: bool = False,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Impute:
        """Build the step that fills missing values with `value`.

        Parameters
        ----------
        *names : str, list of str or dict
            The columns: names, one list, or one dict of column to value.
        value : Aggregate, str, constant or None, default "median"
            The fill value (see `Impute`); not given with a dict.
        indicator : bool, default False
            Also create ``<column>_missing`` where a value was missing.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the filled one.
        suffix : str, optional
            Suffix of the filled column when `keep` is True.

        Returns
        -------
        Impute
            The step.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, or a dict and `value`.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute("age", value=sq.agg.quantile(q=0.9))
        sq.impute(cols='age', value=sq.agg.quantile(q=0.9))
        """
        chosen = columns_arg(names, cols, allow_dict=True)
        if isinstance(chosen, dict):
            if value is not _MEDIAN:
                msg = (
                    f"sq.impute got the dict {chosen!r} and value={value!r}. "
                    "Why: the dict gives each column its value. Fix: leave "
                    "value= out, or put the value in the dict."
                )
                raise SqlearnError(msg)
            value = chosen
            chosen = None
        elif value is _MEDIAN:
            value = "median"  # as if given
        return Impute(
            cols=cast("str | list[str] | Selector | None", chosen),
            value=value,
            indicator=indicator,
            keep=keep,
            suffix=suffix,
        )

    def mean(self, *names: object, **kw: Unpack[_Settings]) -> Impute:
        """Fill with the mean of the present values (``value=sq.agg.mean``).

        As scikit-learn's ``SimpleImputer(strategy="mean")``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's other settings (``indicator``, ``cols``,
            ``keep``, ``suffix``).

        Returns
        -------
        Impute
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute.mean("age")
        sq.impute.mean(cols='age')
        """
        return self(*names, value=agg.mean, **kw)

    def median(self, *names: object, **kw: Unpack[_Settings]) -> Impute:
        """Fill with the exact median of the present values (``sq.agg.median``).

        As scikit-learn's ``SimpleImputer(strategy="median")``.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        **kw : object
            The general form's other settings (``indicator``, ``cols``,
            ``keep``, ``suffix``).

        Returns
        -------
        Impute
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute.median(indicator=True)
        sq.impute.median(indicator=True)
        """
        return self(*names, value=agg.median, **kw)

    def mode(self, *names: object, **kw: Unpack[_Settings]) -> Impute:
        """Fill with the most frequent value, text too (``sq.agg.mode``).

        As scikit-learn's ``SimpleImputer(strategy="most_frequent")``: a tie
        goes to the smallest value.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default every column.
        **kw : object
            The general form's other settings (``indicator``, ``cols``,
            ``keep``, ``suffix``).

        Returns
        -------
        Impute
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute.mode("city")
        sq.impute.mode(cols='city')
        """
        return self(*names, value=agg.mode, **kw)

    def constant(self, v: object, *names: object, **kw: Unpack[_Settings]) -> Impute:
        """Fill with the constant `v`.

        As scikit-learn's ``SimpleImputer(strategy="constant", fill_value=v)``.
        A string here is always text, even one naming an aggregate.

        Parameters
        ----------
        v : str, number or other constant
            The fill value.
        *names : str or list of str
            The columns; by default those of `v`'s kind (numbers or text).
        **kw : object
            The general form's other settings (``indicator``, ``cols``,
            ``keep``, ``suffix``).

        Returns
        -------
        Impute
            The step.

        Raises
        ------
        SqlearnError
            If `v` is an aggregate.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute.constant("unknown", "city")
        sq.impute.constant('unknown', cols='city')
        """
        if isinstance(v, agg.Aggregate):
            msg = (
                f"sq.impute.constant got {v!r}, an aggregate. Why: a constant "
                "is a value given, not learned. Fix: give the aggregate as "
                f"value=, such as sq.impute(value={v!r})."
            )
            raise SqlearnError(msg)
        if isinstance(v, str) and agg.lookup(v):
            v = _Text(v)
        return self(*names, value=v, **kw)

    def indicator(self, *names: object, **kw: Unpack[_Columns]) -> Impute:
        """Flag missing values without filling (``value=None, indicator=True``).

        As scikit-learn's ``MissingIndicator``: ``<column>_missing`` is
        created only for the columns with a missing value at `learn`; the
        input columns stay as they are.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default every column.
        **kw : object
            The general form's other settings (``cols``, ``keep``,
            ``suffix``).

        Returns
        -------
        Impute
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.impute.indicator("age")
        sq.impute.indicator(cols='age')
        """
        return self(*names, value=None, indicator=True, **kw)


impute = ImputeGroup("impute")
"""The imputing steps: ``sq.impute(...)``, ``sq.impute.median(...)`` and so on."""
