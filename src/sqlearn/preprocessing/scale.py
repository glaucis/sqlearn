"""Scale: centre numeric columns and divide by their standard deviation."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression

from sqlearn._expr import const
from sqlearn._selectors import Selector, _numeric
from sqlearn._step import Learned, Step
from sqlearn.agg.aggregates import mean, std
from sqlearn.preprocessing._missing import (
    refuse_all_missing,
    refuse_infinite,
)

__all__ = ["Scale"]


class Scale(Step):
    """Centre numeric columns and divide by their population standard deviation.

    Learns each column's mean and population standard deviation over its
    non-missing values (as scikit-learn's ``StandardScaler`` does). A
    standard deviation of zero counts as 1, so a constant column scales to
    0. The output is DOUBLE. A column with no non-missing value is refused
    with a `StepError`.

    Parameters
    ----------
    cols : Selector or str or sequence of str, default numeric()
        The columns to scale.
    keep : bool, default False
        Keep the input column and add the scaled one beside it.
    suffix : str, optional
        Suffix of the new column when `keep` is True; defaults to the step's name.

    Attributes
    ----------
    mean_ : dict of str to float
        After learning, the mean of each column.
    scale_ : dict of str to float
        After learning, the divisor of each column (1 where the standard
        deviation is 0).

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    >>> pipe = sq.Pipeline([("scale", sq.Scale())]).learn(data)
    >>> pipe["scale"].mean_
    {'x': 2.0}
    >>> [round(v, 4) for v in pipe.apply(data, out="pandas")["x"]]
    [-1.2247, 0.0, 1.2247]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _numeric(),  # noqa: B008
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        super().__init__(cols=cols, keep=keep, suffix=suffix)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the mean and the divisor over the non-missing values.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``mean``, and ``scale``: the population standard deviation, or 1
            where that is 0.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.Scale().learn(duckdb.ColumnExpression("a")))
        ['mean', 'scale']
        """
        spread = std(x)
        scale = duckdb.CaseExpression(spread == const(0.0), const(1.0)).otherwise(
            spread,
        )
        return {"mean": mean(x), "scale": scale}

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Centre the column and divide it by the learned divisor.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            ``(x - mean) / scale`` as DOUBLE.

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
        >>> learned = Learned.values({"mean": 2.0, "scale": 4.0})
        >>> "2.0" in str(sq.Scale().apply(x, learned))
        True
        """
        refuse_all_missing(x, learned, "mean")
        refuse_infinite(x, learned, "mean")
        refuse_infinite(x, learned, "scale")
        return (x.cast("DOUBLE") - learned.mean) / learned.scale
