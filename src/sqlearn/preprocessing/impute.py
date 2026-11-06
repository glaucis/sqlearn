"""Impute: fill the missing values of numeric columns."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, is_missing
from sqlearn._selectors import Schema, Selector, _numeric
from sqlearn._step import Learned, Step
from sqlearn.agg.aggregates import mean, median
from sqlearn.preprocessing._missing import (
    refuse_all_missing,
    refuse_infinite,
)

__all__ = ["Impute"]

_STRATEGIES = ("median", "mean")


class Impute(Step):
    """Fill the missing values (NULL or NaN) of numeric columns.

    Learns the median or mean of each column's non-missing values and
    replaces the missing ones with it. The output is DOUBLE, as
    scikit-learn returns floats. A column with no non-missing value, or a
    text column, is refused with a `StepError`.

    Parameters
    ----------
    cols : Selector or str or sequence of str, default numeric()
        The columns to fill.
    strategy : {"median", "mean"}, default "median"
        What to fill with.
    keep : bool, default False
        Keep the input column and add the filled one beside it.
    suffix : str, optional
        Suffix of the new column when `keep` is True; defaults to the step's name.

    Attributes
    ----------
    value_ : dict of str to float
        After learning, the fill value of each column.

    Raises
    ------
    SqlearnError
        If `strategy` is not ``"median"`` or ``"mean"``.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"age": [10.0, None, 30.0, 40.0]})
    >>> pipe = sq.Pipeline([("fill", sq.Impute())]).learn(data)
    >>> pipe["fill"].value_
    {'age': 30.0}
    >>> pipe.apply(data, out="pandas")["age"].tolist()
    [10.0, 30.0, 30.0, 40.0]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _numeric(),  # noqa: B008
        strategy: str = "median",
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        if strategy not in _STRATEGIES:
            msg = (
                f"Impute got strategy={strategy!r}, which is not supported. "
                "Fix: use strategy='median' or strategy='mean'."
            )
            raise SqlearnError(msg)
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.strategy = strategy

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to fill, refusing any that is not numeric.

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
            If a chosen column is not numeric.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE
        >>> sq.Impute().inputs([("a", DOUBLE)])
        ['a']
        """
        chosen = super().inputs(schema)
        types: dict[str, DuckDBPyType] = dict(schema)
        for c in chosen:
            if not _numeric().resolve([(c, types[c])]):
                msg = (
                    f"cannot impute column {c!r}, which is {types[c]} (text or "
                    "another non-numeric type); Impute fills numeric columns "
                    "only. Fix: choose numeric columns with cols=, or drop "
                    f"{c!r} before this step."
                )
                raise StepError(msg, step="", position=0)
        return chosen

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the fill value over the non-missing values.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``value``: the median or mean of the non-missing values; and
            ``infinite``: infinity where the column holds any, else 0.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> learned = sq.Impute(strategy="mean").learn(duckdb.ColumnExpression("a"))
        >>> list(learned)
        ['value', 'infinite']
        """
        aggregate = median if self.strategy == "median" else mean
        infinite = duckdb.CaseExpression(
            duckdb.FunctionExpression("isinf", x.cast("DOUBLE")),
            const(float("inf")),
        ).otherwise(const(0.0))
        return {
            "value": aggregate(x),
            "infinite": duckdb.FunctionExpression("max", infinite),
        }

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Replace the missing values with the learned one.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            ``CASE WHEN is_missing(x) THEN value ELSE x END`` as DOUBLE.

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
        >>> expr = sq.Impute().apply(x, Learned.values({"value": 2.5, "infinite": 0.0}))
        >>> "2.5" in str(expr)
        True
        """
        refuse_all_missing(x, learned, "value")
        refuse_infinite(x, learned, "infinite")
        value = duckdb.CaseExpression(is_missing(x), learned.value)
        return value.otherwise(x.cast("DOUBLE"))
