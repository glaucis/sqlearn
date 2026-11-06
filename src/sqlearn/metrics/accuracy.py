"""Metric and accuracy: the share of rows where prediction equals target."""

from collections.abc import Callable
from dataclasses import dataclass

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import const
from sqlearn.agg.aggregates import mean

__all__ = ["Metric", "accuracy"]

_FLOATS = frozenset({"FLOAT", "DOUBLE"})


def _isnan(x: Expression) -> Expression:
    return duckdb.FunctionExpression("isnan", x)


def _count(x: Expression) -> Expression:
    """Count the non-NULL values of `x`, NaN among them (unlike `sq.agg.count`)."""
    return duckdb.FunctionExpression("count", x)


@dataclass(frozen=True)
class Metric:
    """A score computed by one aggregate query.

    Attributes
    ----------
    name : str
        The metric's name.
    expression : callable
        Takes the target and prediction expressions, returns the aggregate.
    greater_is_better : bool
        Whether a higher score is better.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.accuracy.greater_is_better
    True
    """

    name: str
    expression: Callable[[Expression, Expression], Expression]
    greater_is_better: bool

    def compute(
        self,
        rel: duckdb.DuckDBPyRelation,
        target: str,
        prediction: str = "prediction",
    ) -> float:
        """Compute the metric over a relation.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows, with a target column and a prediction column.
        target : str
            The name of the target column.
        prediction : str, default "prediction"
            The name of the prediction column.

        Returns
        -------
        float
            The score.

        Raises
        ------
        SqlearnError
            If the relation is empty or either column holds NULL.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT * FROM (VALUES (1, 1), (1, 2)) t(y, prediction)")
        >>> sq.metrics.accuracy.compute(rel, "y")
        0.5
        """
        names = list(rel.columns)
        types = {n: str(t) for n, t in zip(names, rel.types, strict=True)}
        for column in (target, prediction):
            if column not in types:
                msg = (
                    f"{self.name} cannot be computed: column {column!r} is "
                    f"not in the relation (columns: {names}). Pass the name "
                    "of an existing column."
                )
                raise SqlearnError(msg)
        y = ColumnExpression(target)
        p = ColumnExpression(prediction)
        floats = [c for c in (target, prediction) if types[c] in _FLOATS]
        nans = [
            _count(duckdb.CaseExpression(_isnan(ColumnExpression(c)), const(1)))
            for c in floats
        ]
        try:
            row = rel.aggregate(
                [
                    _count(const(1)),
                    _count(y),
                    _count(p),
                    self.expression(y, p),
                    *nans,
                ],
            ).fetchall()[0]
        except duckdb.Error as exc:
            msg = (
                f"{self.name} cannot be computed: DuckDB cannot compare "
                f"column {target!r} ({types[target]}) with column "
                f"{prediction!r} ({types[prediction]}): {exc} Cast one "
                "column so both hold the same kind of label."
            )
            raise SqlearnError(msg) from exc
        total, y_seen, p_seen, score, *nan_counts = row
        if total == 0:
            msg = (
                f"{self.name} cannot be computed: the relation has no rows. "
                "A score needs at least one row; check the data was not "
                "filtered away."
            )
            raise SqlearnError(msg)
        for column, seen in ((target, y_seen), (prediction, p_seen)):
            if seen != total:
                msg = (
                    f"{self.name} cannot be computed: column {column!r} has "
                    f"{total - seen} NULL of {total} rows. A missing label "
                    "has no right answer; drop or fill those rows first."
                )
                raise SqlearnError(msg)
        for column, n_nan in zip(floats, nan_counts, strict=True):
            if n_nan:
                msg = (
                    f"{self.name} cannot be computed: column {column!r} has "
                    f"{n_nan} NaN of {total} rows. A NaN label has no right "
                    "answer; drop or fill those rows first."
                )
                raise SqlearnError(msg)
        return float(score)


accuracy = Metric(
    "accuracy",
    lambda y, p: mean(
        duckdb.CaseExpression(y == p, const(1.0)).otherwise(const(0.0)),
    ),
    True,
)
