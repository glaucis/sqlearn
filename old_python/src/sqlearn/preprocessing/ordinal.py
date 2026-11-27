"""Ordinal: replace each category by its position among the sorted ones."""

from collections.abc import Mapping

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE, INTEGER

from sqlearn._expr import const
from sqlearn._group import call_repr
from sqlearn._selectors import Schema, Selector, _string
from sqlearn._step import Learned, Step
from sqlearn.agg.aggregates import distinct
from sqlearn.preprocessing._lookup import check_lookup, check_text, position, warn_many

__all__ = ["Ordinal"]


def _is_nan(x: Expression) -> Expression:
    """Return whether `x` is NaN; false for any type that holds no NaN.

    Only FLOAT and DOUBLE hold NaN; the text ``'nan'`` is a value.
    """
    floating = duckdb.FunctionExpression("typeof", x).isin(
        const("FLOAT"), const("DOUBLE")
    )
    return floating & duckdb.FunctionExpression("isnan", x.try_cast(DOUBLE))


class Ordinal(Step):
    """Replace each value by its position among the sorted categories.

    Build it with `sq.encode.ordinal <EncodeGroup>`.

    Learns the distinct values of each column; a value becomes its position
    (from 0) in that sorted list. A value not seen when learning becomes -1,
    as with scikit-learn's ``OrdinalEncoder(handle_unknown=
    "use_encoded_value", unknown_value=-1)``. NULL stays NULL (scikit-learn
    keeps missing values missing) and is not a category; so does NaN in a
    float column, which scikit-learn treats as missing too. The output is
    INTEGER and replaces the column in place.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to encode; defaults to the text columns.
    keep : bool, default False
        Keep the input column and add the code beside it.
    lookup : {"list", "hash"}, optional
        How a value is found among the learned categories; both give the
        same codes. Left out, ``"list"``. ``"list"`` compares the value
        with the categories one by one (``list_position``), honouring a
        column's collation; it is the faster up to tens of thousands of
        categories. ``"hash"`` finds it by an MD5 perfect hash, whose cost
        per row barely grows with the count, but whose SQL holds about 3.5
        constants per category, a fixed cost per query. On 1,000,000 rows
        from Parquet the hash applied faster from 20,000 categories (1.9 s
        against 2.4 s) and slower at 15,000 (1.5 s against 0.6 s; see
        ``docs/benchmarks/category-lookup.md``). The hash takes text columns
        alone (VARCHAR, ENUM) and compares the bytes exactly: DuckDB does not
        report a collation to a step, so a collated column is matched by its
        bytes. Left out with more than 20,000 categories in a column, a
        `SqlearnWarning` says so, once per process; passing either value is
        a choice and silences it.

    Attributes
    ----------
    categories_ : dict of str to list
        After learning, the sorted distinct values of each column, without
        NULL and NaN.

    Raises
    ------
    SqlearnError
        If `lookup` is neither ``"list"`` nor ``"hash"``.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"size": ["m", "s", "l", "m"]})
    >>> pipe = sq.Pipeline([("code", sq.encode.ordinal())]).learn(data)
    >>> pipe.apply(data, out="pandas")["size"].tolist()
    [1, 2, 0, 1]
    """

    dynamic = True
    creates = INTEGER

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _string(),  # noqa: B008
        keep: bool = False,
        lookup: str | None = None,
    ) -> None:
        check_lookup("sq.encode.ordinal", lookup)
        super().__init__(cols=cols, keep=keep)
        self.lookup = lookup

    def default_name(self) -> str:
        """Return ``ordinal``.

        Returns
        -------
        str
            The name of the method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.ordinal().default_name()
        'ordinal'
        """
        return "ordinal"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols != _string():
            kwargs["cols"] = self.cols
        if self.keep:
            kwargs["keep"] = True
        if self.lookup is not None:
            kwargs["lookup"] = self.lookup
        return call_repr("sq.encode.ordinal", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to encode, refusing ``lookup="hash"`` on non-text.

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
            If the lookup is ``"hash"`` and a chosen column is not text.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import INTEGER, VARCHAR
        >>> sq.encode.ordinal().inputs([("a", INTEGER), ("c", VARCHAR)])
        ['c']
        """
        chosen = super().inputs(schema)
        check_text("sq.encode.ordinal", self.lookup, chosen, dict(schema))
        return chosen

    def learned(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Warn once at more than WARN_ABOVE (20,000) categories, lookup left out.

        Parameters
        ----------
        values : mapping of str to mapping of str to object
            Column, then learned name, to the value learned.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.ordinal().learned({"c": {"categories": ["a"]}}) is None
        True
        """
        warn_many(self, self.lookup, values)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the sorted distinct values, without NULL and NaN.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``categories``: the sorted distinct values, NULL and NaN left out.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.encode.ordinal().learn(duckdb.ColumnExpression("a")))
        ['categories']
        """
        return {"categories": distinct(x)}

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Replace the value by its position, -1 if unseen, NULL if missing.

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
        >>> expr = sq.encode.ordinal().apply(duckdb.ColumnExpression("c"), learned)
        >>> "list_position" in str(expr)
        True
        """
        categories = learned.categories
        if not isinstance(categories, list):
            msg = "Ordinal needs the learned categories to write its SQL"
            raise TypeError(msg)
        at = position(x, categories, self.lookup or "list")
        code = duckdb.CoalesceOperator(at - const(1), const(-1))
        keep_null = duckdb.CaseExpression(x.isnull() | _is_nan(x), const(None))
        return keep_null.otherwise(code).cast(INTEGER)
