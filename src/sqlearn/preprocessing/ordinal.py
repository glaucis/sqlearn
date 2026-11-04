"""Ordinal: replace each category by its position among the sorted ones."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression
from duckdb.sqltypes import INTEGER

from sqlearn._expr import const, distinct_values
from sqlearn._selectors import Selector, string
from sqlearn._step import Learned, Step

__all__ = ["Ordinal"]


class Ordinal(Step):
    """Replace each value by its position among the sorted categories.

    Learns the distinct values of each column; a value becomes its position
    (from 0) in that sorted list. A value not seen when learning becomes -1,
    as with scikit-learn's ``OrdinalEncoder(handle_unknown=
    "use_encoded_value", unknown_value=-1)``. NULL stays NULL (scikit-learn
    keeps missing values missing) and is not a category. The output is
    INTEGER and replaces the column in place.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to encode; defaults to the text columns.
    keep : bool, default False
        Keep the input column and add the code beside it.
    suffix : str, optional
        Suffix of the new column when `keep` is True; defaults to the step's name.

    Attributes
    ----------
    categories_ : dict of str to list
        After learning, the sorted distinct non-NULL values of each column.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"size": ["m", "s", "l", "m"]})
    >>> pipe = sq.Pipeline([("code", sq.Ordinal())]).learn(data)
    >>> pipe.apply(data, out="pandas")["size"].tolist()
    [1, 2, 0, 1]
    """

    dynamic = True
    creates = INTEGER

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = string(),  # noqa: B008
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        super().__init__(cols=cols, keep=keep, suffix=suffix)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the sorted distinct values.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``categories``: the sorted distinct non-NULL values.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.Ordinal().learn(duckdb.ColumnExpression("a")))
        ['categories']
        """
        return {"categories": distinct_values(x)}

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Replace the value by its position, -1 if unseen, NULL if NULL.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            The position as INTEGER.

        Raises
        ------
        TypeError
            If the categories are not yet learned (a placeholder), which is
            how an undeclared copy of the step is found to be dynamic.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> learned = Learned.values({"categories": ["a", "b"]})
        >>> expr = sq.Ordinal().apply(duckdb.ColumnExpression("c"), learned)
        >>> "list_position" in str(expr)
        True
        """
        categories = learned.categories
        if not isinstance(categories, list):
            msg = "Ordinal needs the learned categories to write its SQL"
            raise TypeError(msg)
        values = categories
        position = duckdb.FunctionExpression(
            "list_position",
            const(values),
            x,
        )
        code = duckdb.CoalesceOperator(position - const(1), const(-1))
        keep_null = duckdb.CaseExpression(x.isnull(), const(None))
        return keep_null.otherwise(code).cast(INTEGER)
