"""OneHot: one integer column per category of a column."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression
from duckdb.sqltypes import INTEGER

from sqlearn._expr import const
from sqlearn._group import call_repr
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

    Build it with `sq.encode.onehot <EncodeGroup>`.

    Learns the distinct values of each column and creates a column named
    ``<column>_<value>`` for each, holding 1 where the row has that value and
    0 elsewhere. A value not seen when learning gives 0 in every column, as
    scikit-learn's ``OneHotEncoder(handle_unknown="ignore")`` does. NULL is
    its own category, named ``<column>_NULL``, only if NULL was seen when
    learning. Non-text values are named by their string form (``x_1``).
    Names that clash, compared without regard to case, are numbered in sorted
    order of their values, never refused: ``Oslo`` and ``oslo`` give
    ``city_Oslo`` and ``city_oslo_2``; the text ``'NULL'`` beside a real NULL
    gives ``city_NULL`` and ``city_NULL_2`` (ADR 0035).

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to encode; defaults to the text columns.
    keep : bool, default False
        Keep the input column beside the new ones.

    Attributes
    ----------
    categories_ : dict of str to list
        After learning, the sorted distinct non-NULL values of each column.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"city": ["rome", "oslo", "rome"]})
    >>> pipe = sq.Pipeline([("hot", sq.encode.onehot())]).learn(data)
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
    ) -> None:
        super().__init__(cols=cols, keep=keep)

    def default_name(self) -> str:
        """Return ``onehot``.

        Returns
        -------
        str
            The name of the method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.onehot().default_name()
        'onehot'
        """
        return "onehot"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols != _string():
            kwargs["cols"] = self.cols
        if self.keep:
            kwargs["keep"] = True
        return call_repr("sq.encode.onehot", **kwargs)

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
        >>> list(sq.encode.onehot().learn(duckdb.ColumnExpression("a")))
        ['categories', 'has_null']
        """
        return {
            "categories": _categories(x),
            "has_null": duckdb.FunctionExpression("bool_or", x.isnull()),
        }

    def apply(self, x: Expression, learned: Learned) -> list[tuple[str, Expression]]:
        """Build one 0/1 column per learned category.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        list of (str, duckdb.Expression)
            Each value's label (its string form) and an INTEGER 0/1
            expression, then the label ``NULL`` when NULL was seen; the
            pipeline names them ``<column>_<label>``. A list of pairs, not a
            mapping: the text ``'NULL'`` and a real NULL share a label.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> learned = Learned.values({"categories": ["a", "b"], "has_null": False})
        >>> out = sq.encode.onehot().apply(duckdb.ColumnExpression("c"), learned)
        >>> [label for label, _ in out]
        ['a', 'b']
        """
        categories = learned.categories
        out: list[tuple[str, Expression]] = []
        for value in categories if isinstance(categories, list) else []:
            hit = duckdb.CaseExpression(x == const(value), const(1))
            out.append((str(value), hit.otherwise(const(0)).cast(INTEGER)))
        if learned.raw("has_null") is True:
            hit = duckdb.CaseExpression(x.isnull(), const(1))
            out.append(("NULL", hit.otherwise(const(0)).cast(INTEGER)))
        return out
