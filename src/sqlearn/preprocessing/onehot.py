"""OneHot: one integer column per category of a column."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression
from duckdb.sqltypes import INTEGER

from sqlearn._errors import StepError
from sqlearn._expr import const
from sqlearn._selectors import Selector, _string
from sqlearn._step import Learned, Step

__all__ = ["OneHot"]


def _categories(x: Expression) -> Expression:
    """Return the sorted distinct values of `x`, NULL left out, NaN kept.

    Not `sqlearn.agg.distinct`, which leaves NaN out: to OneHot, as to
    scikit-learn's ``OneHotEncoder``, NaN in a float column is a category.
    """
    keys = duckdb.FunctionExpression(
        "list_sort",
        duckdb.FunctionExpression(
            "map_keys", duckdb.FunctionExpression("histogram", x)
        ),
    )
    return duckdb.CoalesceOperator(keys, duckdb.ConstantExpression([]))


class OneHot(Step):
    """Replace a column by one 0/1 integer column per category.

    Learns the distinct values of each column and creates a column named
    ``<column>_<value>`` for each, holding 1 where the row has that value and
    0 elsewhere. A value not seen when learning gives 0 in every column, as
    scikit-learn's ``OneHotEncoder(handle_unknown="ignore")`` does. NULL is
    its own category, named ``<column>_NULL``, only if NULL was seen when
    learning. Non-text values are named by their string form (``x_1``).

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to encode; defaults to the text columns.
    keep : bool, default False
        Keep the input column beside the new ones.
    suffix : str, optional
        Unused by the new column names, which come from the categories.

    Attributes
    ----------
    categories_ : dict of str to list
        After learning, the sorted distinct non-NULL values of each column.

    Raises
    ------
    StepError
        On learning, if a column holds the text ``'NULL'`` and also NULL, so
        two new columns would share a name.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"city": ["rome", "oslo", "rome"]})
    >>> pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(data)
    >>> pipe["hot"].categories_
    {'city': ['oslo', 'rome']}
    >>> pipe.apply(data, out="pandas").to_dict("list")
    {'city_oslo': [0, 1, 0], 'city_rome': [1, 0, 1]}
    """

    dynamic = True
    creates = INTEGER

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _string(),  # noqa: B008
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        super().__init__(cols=cols, keep=keep, suffix=suffix)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the distinct values and whether NULL occurs.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``categories``: the sorted distinct non-NULL values; and
            ``has_null``: whether any value is NULL.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.OneHot().learn(duckdb.ColumnExpression("a")))
        ['categories', 'has_null']
        """
        return {
            "categories": _categories(x),
            "has_null": duckdb.FunctionExpression("bool_or", x.isnull()),
        }

    def apply(self, x: Expression, learned: Learned) -> Mapping[str, Expression]:
        """Build one 0/1 column per learned category.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``<column>_<value>`` to an INTEGER 0/1 expression, plus
            ``<column>_NULL`` when NULL was seen.

        Raises
        ------
        StepError
            If the text ``'NULL'`` is a category and NULL was also seen.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> learned = Learned.values({"categories": ["a", "b"], "has_null": False})
        >>> list(sq.OneHot().apply(duckdb.ColumnExpression("c"), learned))
        ['c_a', 'c_b']
        """
        column = x.get_name()
        categories = learned.categories
        out: dict[str, Expression] = {}
        for value in categories if isinstance(categories, list) else []:
            hit = duckdb.CaseExpression(x == const(value), const(1))
            out[f"{column}_{value}"] = hit.otherwise(const(0)).cast(INTEGER)
        if learned.raw("has_null") is True:
            name = f"{column}_NULL"
            if name in out:
                msg = (
                    f"cannot encode column {column!r}: it holds both NULL and "
                    f"the text 'NULL', and both would be named {name!r}. Fix: "
                    "replace one of them before this step."
                )
                raise StepError(msg, step="", position=0)
            hit = duckdb.CaseExpression(x.isnull(), const(1))
            out[name] = hit.otherwise(const(0)).cast(INTEGER)
        return out
