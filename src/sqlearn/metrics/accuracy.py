"""Metric and accuracy: the share of rows where prediction equals target."""

from collections.abc import Callable
from dataclasses import dataclass

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import avg, const, count

__all__ = ["Metric", "accuracy"]


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
    >>> sq.accuracy.greater_is_better
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
        >>> sq.accuracy.compute(rel, "y")
        0.5
        """
        y = ColumnExpression(target)
        p = ColumnExpression(prediction)
        row = rel.aggregate(
            [count(const(1)), count(y), count(p), self.expression(y, p)],
        ).fetchall()[0]
        total, y_seen, p_seen, score = row
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
        return float(score)


accuracy = Metric(
    "accuracy",
    lambda y, p: avg(
        duckdb.CaseExpression(y == p, const(1.0)).otherwise(const(0.0)),
    ),
    True,
)
