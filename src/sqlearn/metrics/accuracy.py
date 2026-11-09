"""Metric and accuracy: the share of rows where prediction equals target."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import const
from sqlearn._feed import PROBA
from sqlearn.agg.aggregates import mean

__all__ = ["Metric", "MissingClassError", "accuracy"]

_FLOATS = frozenset({"FLOAT", "DOUBLE"})
_STAGE = "__sqlearn_stage_"


def _isnan(x: Expression) -> Expression:
    return duckdb.FunctionExpression("isnan", x)


def _count(x: Expression) -> Expression:
    """Count the non-NULL values of `x`, NaN among them (unlike `sq.agg.count`)."""
    return duckdb.FunctionExpression("count", x)


class MissingClassError(SqlearnError):
    """A metric that ranks each class against the rest found a class on one side.

    Raised by `Metric.compute` when every target row is one class, or none
    is, so there is no pair of rows to rank; a search names the fold.

    Parameters
    ----------
    message : str
        The whole message: what went wrong, why, the fix.
    reason : str
        Why alone, for a caller that names its own fix.

    Attributes
    ----------
    reason : str
        Why the score has no value, without a fix.

    Examples
    --------
    >>> from sqlearn.metrics import MissingClassError
    >>> MissingClassError("no score: why. Fix: this.", "why").reason
    'why'
    """

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _plain(value: object) -> object:
    """Return a numpy scalar as the Python value DuckDB takes as a constant."""
    item = getattr(value, "item", None)
    return item() if callable(item) else value


def _noun(column: str, target: str, proba: bool) -> str:
    """Name what a column holds: a label, or a probability."""
    return "probability" if proba and column != target else "label"


def _column_types(
    name: str, rel: duckdb.DuckDBPyRelation, columns: Sequence[str]
) -> dict[str, str]:
    """Return each column's type, refusing a column not in the relation."""
    names = list(rel.columns)
    types = {n: str(t) for n, t in zip(names, rel.types, strict=True)}
    for column in columns:
        if column not in types:
            msg = (
                f"{name} cannot be computed: column {column!r} is "
                f"not in the relation (columns: {names}). Pass the name "
                "of an existing column."
            )
            raise SqlearnError(msg)
    return types


def _refuse_gaps(
    name: str,
    target: str,
    columns: Sequence[str],
    floats: Sequence[str],
    total: int,
    seen: Sequence[int],
    nan_counts: Sequence[int],
    *,
    proba: bool = False,
) -> None:
    """Refuse no rows, and a column holding NULL or NaN, from their counts."""
    if total == 0:
        msg = (
            f"{name} cannot be computed: the relation has no rows. "
            "A score needs at least one row; check the data was not "
            "filtered away."
        )
        raise SqlearnError(msg)
    for column, n_seen in zip(columns, seen, strict=True):
        if n_seen != total:
            msg = (
                f"{name} cannot be computed: column {column!r} has "
                f"{total - n_seen} NULL of {total} rows. A missing "
                f"{_noun(column, target, proba)} has no right answer; "
                "drop or fill those rows first."
            )
            raise SqlearnError(msg)
    for column, n_nan in zip(floats, nan_counts, strict=True):
        if n_nan:
            msg = (
                f"{name} cannot be computed: column {column!r} has "
                f"{n_nan} NaN of {total} rows. A NaN "
                f"{_noun(column, target, proba)} has no right answer; "
                "drop or fill those rows first."
            )
            raise SqlearnError(msg)


@dataclass(frozen=True)
class Metric:
    """A score computed by one aggregate query.

    A metric reads the model's ``predict`` (one prediction column) or its
    ``predict_proba`` (one column per class, ``__sqlearn_proba_0``,
    ``__sqlearn_proba_1``, ..., in the order of the model's ``classes_``).

    Attributes
    ----------
    name : str
        The metric's name.
    expression : callable
        Returns the aggregate. For a ``"predict"`` metric it takes the
        target and prediction expressions; for a ``"predict_proba"`` metric,
        the target expression, the list of probability expressions (one per
        class) and the list of classes.
    greater_is_better : bool
        Whether a higher score is better.
    needs : str, default "predict"
        The model's method the metric reads: ``"predict"`` or
        ``"predict_proba"``.
    windows : callable, optional
        For a ``"predict_proba"`` metric that ranks rows: takes the
        probability expressions and returns window expressions, computed
        for every row before the aggregate, which then receives them in
        place of the probabilities.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.accuracy.greater_is_better
    True
    >>> sq.metrics.log_loss.needs
    'predict_proba'
    """

    name: str
    expression: Callable[..., Expression]
    greater_is_better: bool
    needs: str = "predict"
    windows: Callable[[list[Expression]], list[Expression]] | None = None

    def __call__(self, **settings: object) -> "Metric":
        """Refuse settings: this metric takes none (ADR 0042).

        Parameters
        ----------
        **settings : object
            Any setting.

        Raises
        ------
        SqlearnError
            Always: only precision, recall and f1 take settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.accuracy(average="macro")
        Traceback (most recent call last):
        ...
        sqlearn.errors.SqlearnError: accuracy takes no settings, ...
        """
        given = ", ".join(f"{k}=" for k in settings) or "a call"
        msg = (
            f"{self.name} takes no settings, and was given {given}. Why: "
            "only the classification metrics precision, recall and f1 have "
            f"settings. Fix: use sq.metrics.{self.name} as it is."
        )
        raise SqlearnError(msg)

    def compute(
        self,
        rel: duckdb.DuckDBPyRelation,
        target: str,
        prediction: str = "prediction",
        classes: Sequence[object] | None = None,
    ) -> float:
        """Compute the metric over a relation.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows, with a target column and a prediction column, or for
            a ``"predict_proba"`` metric a column ``__sqlearn_proba_<i>``
            for each class.
        target : str
            The name of the target column.
        prediction : str, default "prediction"
            The name of the prediction column (unused by a
            ``"predict_proba"`` metric).
        classes : sequence, optional
            For a ``"predict_proba"`` metric, the model's ``classes_``: the
            label of each probability column, in order.

        Returns
        -------
        float
            The score.

        Raises
        ------
        SqlearnError
            If the relation is empty, a column is missing or holds NULL or
            NaN, or, for a ``"predict_proba"`` metric, the classes are not
            given, a probability is below 0 or above 1, or a target is none
            of them.
        MissingClassError
            If the metric ranks each class against the rest and a class has
            every row or none.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql("SELECT * FROM (VALUES (1, 1), (1, 2)) t(y, prediction)")
        >>> sq.metrics.accuracy.compute(rel, "y")
        0.5
        """
        proba = self.needs == "predict_proba"
        if proba:
            if classes is None:
                msg = (
                    f"{self.name} reads one probability column per class, so "
                    "it needs the classes they belong to, and none were "
                    "given. Fix: pass classes=, the model's classes_ in "
                    "order."
                )
                raise SqlearnError(msg)
            labels = [_plain(c) for c in classes]
            columns = [target, *(f"{PROBA}{j}" for j in range(len(labels)))]
        else:
            labels = []
            columns = [target, prediction]
        types = _column_types(self.name, rel, columns)
        y = ColumnExpression(target)
        values = [ColumnExpression(c) for c in columns[1:]]
        if proba and self.windows is not None:
            # Each row's window values first, then the one aggregate.
            ranks = self.windows(values)
            staged = [f"{_STAGE}{i}" for i in range(len(ranks))]
            rel = rel.project(
                *(ColumnExpression(c) for c in columns),
                *(r.alias(n) for r, n in zip(ranks, staged, strict=True)),
            )
            given = [ColumnExpression(n) for n in staged]
        else:
            given = values
        if proba:
            consts = [const(c) for c in labels]
            score = self.expression(y, given, labels)
            known = [_count(duckdb.CaseExpression(y.isin(*consts), const(1)))]
            per_class = [
                _count(duckdb.CaseExpression(y == c, const(1))) for c in consts
            ]
            outside = [
                _count(duckdb.CaseExpression((v < const(0)) | (v > const(1)), const(1)))
                for v in values
            ]
        else:
            score = self.expression(y, *given)
            known, per_class, outside = [], [], []
        floats = [c for c in columns if types[c] in _FLOATS]
        nans = [
            _count(duckdb.CaseExpression(_isnan(ColumnExpression(c)), const(1)))
            for c in floats
        ]
        try:
            row = rel.aggregate(
                [
                    _count(const(1)),
                    *(_count(ColumnExpression(c)) for c in columns),
                    score,
                    *nans,
                    *known,
                    *per_class,
                    *outside,
                ],
            ).fetchall()[0]
        except duckdb.Error as exc:
            other = (
                f"the classes {labels}"
                if proba
                else f"column {prediction!r} ({types[prediction]})"
            )
            msg = (
                f"{self.name} cannot be computed: DuckDB cannot compare "
                f"column {target!r} ({types[target]}) with {other}: {exc} "
                "Cast one so both hold the same kind of label."
            )
            raise SqlearnError(msg) from exc
        total = row[0]
        seen = row[1 : 1 + len(columns)]
        value = row[1 + len(columns)]
        rest = row[2 + len(columns) :]
        nan_counts = rest[: len(floats)]
        _refuse_gaps(
            self.name, target, columns, floats, total, seen, nan_counts, proba=proba
        )
        if proba:
            n_known, *after = rest[len(floats) :]
            counts, beyond = after[: len(labels)], after[len(labels) :]
            for column, n_out in zip(columns[1:], beyond, strict=True):
                if n_out:
                    msg = (
                        f"{self.name} cannot be computed: column {column!r} "
                        f"has {n_out} of {total} rows with a probability "
                        "below 0 or above 1. A probability lies between 0 "
                        "and 1, and scikit-learn refuses such values too. "
                        "Fix: check the model's predict_proba, or score "
                        "with a model whose probabilities lie in [0, 1]."
                    )
                    raise SqlearnError(msg)
            if n_known != total:
                msg = (
                    f"{self.name} cannot be computed: column {target!r} has "
                    f"{total - n_known} of {total} rows whose label is none "
                    f"of the classes {labels}, so no probability belongs to "
                    "it. Fix: score with a model trained on every label, or "
                    "drop those rows."
                )
                raise SqlearnError(msg)
            sides = [
                f"class {c!r} has {'every' if n == total else 'no'} row"
                for c, n in zip(labels, counts, strict=True)
                if n in (0, total)
            ]
            if value is None and sides:
                reason = (
                    f"{', '.join(sides)} of the {total}, so there is no pair "
                    "of rows, one of the class and one not, to rank"
                )
                msg = (
                    f"{self.name} cannot be computed: {reason}. Fix: score "
                    "rows that hold every class."
                )
                raise MissingClassError(msg, reason)
        return float(value)


accuracy = Metric(
    "accuracy",
    lambda y, p: mean(
        duckdb.CaseExpression(y == p, const(1.0)).otherwise(const(0.0)),
    ),
    True,
)
