"""VarianceThreshold: keep the numeric columns whose variance is above a bound."""

import math
from collections.abc import Mapping
from typing import ClassVar, cast

import duckdb
from duckdb import Expression

from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, is_missing
from sqlearn._group import call_repr
from sqlearn._selectors import Schema, Selector, _numeric
from sqlearn._step import Learned, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing.scale import _numeric_inputs

__all__ = ["VarianceThreshold"]


def _threshold(value: object) -> float:
    """Return `value` when it is a number from 0 up, else refuse it."""
    number = isinstance(value, int | float) and not isinstance(value, bool)
    if not number or math.isnan(cast("float", value)) or cast("float", value) < 0:
        msg = (
            f"sq.select.variance got threshold={value!r}. Why: a variance is "
            "never below 0, so the threshold is a number from 0 up, as "
            "scikit-learn's VarianceThreshold checks. Fix: give such a "
            "number, such as threshold=0.0 to drop constant columns."
        )
        raise SqlearnError(msg)
    return cast("float", value)


def _whole(x: Expression, extreme: str) -> Expression:
    """Return the column's least or greatest value, NULL when one is missing.

    As numpy's ``ptp``, which scikit-learn compares the variance with: a
    missing value (NaN) makes the range NaN, so the variance alone decides.
    """
    found = duckdb.FunctionExpression(extreme, agg.present(x))
    gap = duckdb.FunctionExpression("bool_or", is_missing(x))
    return duckdb.CaseExpression(gap, const(None)).otherwise(found)


def _number(value: object) -> float:
    """Return a learned value as a float, NaN for None (nothing learned).

    A saved file's values are read back from JSON: anything but a number
    there (text, a flag) is refused, so loading reports the file as damaged.
    """
    if value is None:
        return math.nan
    if type(value) is not int and type(value) is not float:
        msg = f"a learned value is {type(value).__name__}, not a number"
        raise TypeError(msg)
    return float(value)


class VarianceThreshold(Step):
    """Keep the numeric columns whose variance is above `threshold`.

    Build it with `sq.select.variance <SelectGroup>`. As scikit-learn's
    ``VarianceThreshold``: it learns each column's population variance over
    its present values (neither NULL nor NaN, as numpy's ``nanvar``) and
    keeps a column whose variance is above `threshold`; the others are gone.
    A column kept passes through unchanged: its name, type and values. At
    ``threshold=0`` the variance compared is the smaller of the variance and
    the column's range (largest less least value), so a constant column is
    dropped whatever the rounding of its variance; a column with a missing
    value has no range (numpy's ``ptp`` is NaN), and its variance alone
    decides, as in scikit-learn. It does not read the target.

    Parameters
    ----------
    threshold : float, default 0.0
        The variance a column must be above to be kept; from 0 up. It
        chooses only which columns are output, so a search over it learns
        each fold once (``output_settings``).
    cols : Selector or str or sequence of str, optional
        The columns to choose among; by default the numeric ones. Columns
        not chosen pass through.

    Attributes
    ----------
    variances_ : dict of str to float
        After learning, each column's variance as scikit-learn's
        ``variances_``: at ``threshold=0`` the smaller of the variance and
        the range; NaN for a column with no present value.
    variance_ : dict of str to float
        After learning, each column's population variance (None when it had
        no present value).
    low_, high_ : dict of str to float
        After learning, each column's least and greatest value, None when
        a value is missing.

    Raises
    ------
    SqlearnError
        If `threshold` is negative or not a number.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": [1.0, 2.0, 3.0]})
    >>> pipe = sq.Pipeline([sq.select.variance()]).learn(data)
    >>> pipe.columns_out_
    ['b']
    >>> pipe["variance"].variances_
    {'a': 0.0, 'b': 0.6666666666666666}
    """

    dynamic = True
    rowwise = True
    keeps_inputs = True
    output_settings: ClassVar[frozenset[str]] = frozenset({"threshold"})

    def __init__(
        self,
        threshold: float = 0.0,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _numeric(),  # noqa: B008
    ) -> None:
        super().__init__(cols=cols)
        self.threshold = _threshold(threshold)

    def default_name(self) -> str:
        """Return ``variance``.

        Returns
        -------
        str
            ``variance``, whatever the threshold.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select.variance(threshold=0.5).default_name()
        'variance'
        """
        return "variance"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.threshold != 0:
            kwargs["threshold"] = self.threshold
        if self.cols != _numeric():
            kwargs["cols"] = self.cols
        return call_repr("sq.select.variance", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to choose among, refusing any that is not numeric.

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
        >>> sq.select.variance().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "select by variance", "a variance is of numbers"
        )

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the column's variance, and its least and greatest values.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``variance``: the population variance of the present values
            (`sqlearn.agg.var`); ``low`` and ``high``: the least and the
            greatest value, as DOUBLE, NULL when a value is missing.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.select.variance().learn(duckdb.ColumnExpression("a")))
        ['variance', 'low', 'high']
        """
        return {
            "variance": agg.var(x),
            "low": _whole(x, "min"),
            "high": _whole(x, "max"),
        }

    def _compared(self, learned: Mapping[str, object]) -> float:
        """Return the variance compared with the threshold, as scikit-learn's."""
        variance = _number(learned["variance"])
        if self.threshold != 0:
            return variance
        spread = _number(learned["high"]) - _number(learned["low"])
        # As numpy's nanmin over the two: NaN only when both are NaN.
        return float(
            min((v for v in (variance, spread) if not math.isnan(v)), default=math.nan)
        )

    @property
    def variances_(self) -> dict[str, float]:
        """Each column's variance as scikit-learn's ``variances_``.

        Returns
        -------
        dict of str to float
            Column to its variance; at ``threshold=0`` the smaller of the
            variance and the range (largest less least value); NaN for a
            column with no present value.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [0.0, 10.0]})
        >>> sq.Pipeline([sq.select.variance()]).learn(data)["variance"].variances_
        {'a': 10.0}
        """
        learned = cast(
            "dict[str, dict[str, object]] | None", self.__dict__.get("_learned")
        )
        if learned is None:
            return cast("dict[str, float]", self.variance_)  # raises: not learned
        return {c: self._compared(values) for c, values in learned.items()}

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
        values: Mapping[str, Expression],
    ) -> Mapping[str, Expression]:
        """Keep each column whose variance is above the threshold, unchanged.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The chosen columns, by name.
        learned : mapping of str to Learned
            The values learned for each column.
        values : mapping of str to duckdb.Expression
            Unused: the step computes nothing per row.

        Returns
        -------
        mapping of str to duckdb.Expression
            The columns kept, each as it came, under its own name.

        Raises
        ------
        StepError
            If no column's variance is above the threshold, as
            scikit-learn's ``VarianceThreshold`` raises.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> xs = {"a": duckdb.ColumnExpression("a"), "b": duckdb.ColumnExpression("b")}
        >>> learned = {
        ...     "a": Learned.values({"variance": 0.0, "low": 1.0, "high": 1.0}),
        ...     "b": Learned.values({"variance": 2.0, "low": 0.0, "high": 4.0}),
        ... }
        >>> list(sq.select.variance().apply_row(xs, learned, {}))
        ['b']
        """
        compared = {
            c: self._compared(
                {k: learned[c].raw(k) for k in ("variance", "low", "high")}
            )
            for c in xs
        }
        kept = {c: x for c, x in xs.items() if compared[c] > self.threshold}
        if xs and not kept:
            raise StepError(self._none_passes(compared), step="", position=0)
        return kept

    def _none_passes(self, compared: Mapping[str, float]) -> str:
        """Say that no column passes, naming the threshold and the largest variance."""
        finite = {c: v for c, v in compared.items() if math.isfinite(v)}
        if finite:
            column = max(finite, key=lambda c: finite[c])
            largest = (
                f"the largest variance learned is {finite[column]:.6g}, of "
                f"column {column!r}"
            )
        else:
            largest = "no column has a variance (each had no present value)"
        return (
            "keeps no column: none has a variance above the threshold "
            f"{self.threshold!r}, and {largest}. Why: a column is kept only "
            "when its variance is above the threshold, and scikit-learn's "
            "VarianceThreshold refuses to keep none. Fix: lower the "
            "threshold below the largest variance, or choose columns that "
            "vary with cols=."
        )
