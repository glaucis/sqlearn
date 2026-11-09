"""Precision, recall and F1, counted per class in one grouped query.

As scikit-learn 1.9.1's ``precision_score``, ``recall_score`` and
``f1_score`` (spec §1): the same settings, defaults and refusals. Each
class's rows in the target, in the prediction and in both come from DuckDB;
the scores are arithmetic on those few counts (ADR 0042).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import InternalError, SqlearnError
from sqlearn._expr import const
from sqlearn.metrics.accuracy import (
    _FLOATS,
    Metric,
    _column_types,
    _count,
    _isnan,
    _refuse_gaps,
)

__all__ = ["ClassificationMetric", "f1", "precision", "recall"]

Counts = list[tuple[object, int, int, int]]

AVERAGES = ("binary", "macro", "micro", "weighted")
_DEFAULTS = {"average": "binary", "pos_label": 1, "zero_division": "warn"}


def _not_an_expression(*_: Expression) -> Expression:
    msg = (
        "a classification metric has no single aggregate; its compute "
        "counts per class instead"
    )
    raise InternalError(msg)


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _counts(rel: duckdb.DuckDBPyRelation, target: str, prediction: str) -> Counts:
    """Return each class's rows in the target, in the prediction, and in both.

    One grouped query over the two label columns, stacked: a target row
    counts for its label in the target (and in both when the prediction
    agrees), a prediction row for its label in the prediction. DuckDB gives
    the stacked column one type, so an INTEGER 1 and a DOUBLE 1.0 are one
    class. Sorted by label.
    """
    t, p = ColumnExpression("t"), ColumnExpression("p")
    pairs = rel.project(
        ColumnExpression(target).alias("t"), ColumnExpression(prediction).alias("p")
    )
    hit = duckdb.CaseExpression(t == p, const(1)).otherwise(const(0))
    stacked = pairs.project(
        t.alias("label"),
        const(1).alias("n_target"),
        const(0).alias("n_prediction"),
        hit.alias("n_both"),
    ).union(
        pairs.project(
            p.alias("label"),
            const(0).alias("n_target"),
            const(1).alias("n_prediction"),
            const(0).alias("n_both"),
        )
    )
    label = ColumnExpression("label")
    grouped = stacked.aggregate(
        [
            label,
            *(
                _fn("sum", ColumnExpression(c))
                for c in ("n_target", "n_prediction", "n_both")
            ),
        ],
        "label",
    ).sort(label)
    return [(lab, int(a), int(b), int(c)) for lab, a, b, c in grouped.fetchall()]


def _nanmean(values: Sequence[float], weights: Sequence[int] | None = None) -> float:
    """Average leaving NaN out, as scikit-learn's ``_nanaverage``; all NaN is NaN."""
    kept = [
        (v, 1 if weights is None else weights[i])
        for i, v in enumerate(values)
        if not math.isnan(v)
    ]
    total = sum(w for _, w in kept)
    if not kept or total == 0:
        return math.nan
    return sum(v * w for v, w in kept) / total


def _valid_zero_division(value: object) -> bool:
    if value == "warn":
        return True
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isnan(value) or value in (0, 1)


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and a == b


@dataclass(frozen=True)
class ClassificationMetric(Metric):
    """A classification score counted per class: precision, recall or F1.

    Attributes
    ----------
    score : {"precision", "recall", "f1"}
        Which score.
    average : str, default "binary"
        How the classes' scores are combined, as scikit-learn's `average`.
    pos_label : object, default 1
        The class scored under ``average="binary"``.
    zero_division : str or float, default "warn"
        The score of a class whose score divides by zero.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (1, 1), (1, 0), (0, 0)) t(y, prediction)"
    ... )
    >>> sq.metrics.recall.compute(rel, "y")
    0.5
    """

    score: Literal["precision", "recall", "f1"] = "f1"
    average: str = "binary"
    pos_label: object = 1
    zero_division: str | float = "warn"

    def __call__(self, **settings: object) -> "ClassificationMetric":
        """Return a copy with the given settings; the others are kept.

        Parameters
        ----------
        **settings : object
            Any of ``average`` ({"binary", "macro", "micro", "weighted"}:
            how the classes' scores are combined), ``pos_label`` (the class
            scored under ``average="binary"``) and ``zero_division``
            ({"warn", 0.0, 1.0, nan}: the score of a class whose score
            divides by zero).

        Returns
        -------
        ClassificationMetric
            The configured copy.

        Raises
        ------
        SqlearnError
            If a setting is not one of the three, or `average` or
            `zero_division` is not one of its values.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.f1(average="macro")
        f1(average='macro')
        """
        unknown = [k for k in settings if k not in _DEFAULTS]
        if unknown:
            msg = (
                f"{self.name} has no setting {unknown[0]}=. Why: its settings "
                f"are {', '.join(_DEFAULTS)}, as scikit-learn's. Fix: use one "
                "of them."
            )
            raise SqlearnError(msg)
        changes = dict(settings)
        if "average" in changes and changes["average"] not in AVERAGES:
            known = ", ".join(repr(a) for a in AVERAGES)
            msg = (
                f"{self.name} was given average={changes['average']!r}. Why: "
                f'the averages are {known} (scikit-learn\'s "samples" is for '
                "multilabel data, which sqlearn does not have). Fix: use one "
                "of them."
            )
            raise SqlearnError(msg)
        if "zero_division" in changes and not _valid_zero_division(
            changes["zero_division"]
        ):
            msg = (
                f"{self.name} was given zero_division="
                f'{changes["zero_division"]!r}. Why: it takes "warn", 0.0, '
                "1.0 or nan, as scikit-learn. Fix: use one of them."
            )
            raise SqlearnError(msg)
        return replace(self, **changes)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Return the name, with the settings away from the defaults."""
        changed = [
            f"{k}={getattr(self, k)!r}"
            for k, v in _DEFAULTS.items()
            if not _same(getattr(self, k), v)
        ]
        return f"{self.name}({', '.join(changed)})" if changed else self.name

    def compute(
        self,
        rel: duckdb.DuckDBPyRelation,
        target: str,
        prediction: str = "prediction",
        classes: Sequence[object] | None = None,
    ) -> float:
        """Compute the score over a relation.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows, with a target column and a prediction column.
        target : str
            The name of the target column.
        prediction : str, default "prediction"
            The name of the prediction column.
        classes : sequence, optional
            Unused: the classes are those in the target or the prediction.

        Returns
        -------
        float
            The score.

        Raises
        ------
        SqlearnError
            If the relation is empty, or a column is missing or holds NULL
            or NaN.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql(
        ...     "SELECT * FROM (VALUES (1, 1), (0, 1), (0, 0)) t(y, prediction)"
        ... )
        >>> sq.metrics.precision.compute(rel, "y")
        0.5
        """
        columns = [target, prediction]
        types = _column_types(self.name, rel, columns)
        floats = [c for c in columns if types[c] in _FLOATS]
        row = rel.aggregate(
            [
                _count(const(1)),
                *(_count(ColumnExpression(c)) for c in columns),
                *(
                    _count(duckdb.CaseExpression(_isnan(ColumnExpression(c)), const(1)))
                    for c in floats
                ),
            ]
        ).fetchall()[0]
        total, seen, nans = row[0], row[1:3], row[3:]
        _refuse_gaps(self.name, target, columns, floats, total, seen, nans)
        counts = _counts(rel, target, prediction)
        if self.average == "binary":
            found = [c for c in counts if c[0] == self.pos_label]
            _, n_target, n_prediction, tp = found[0] if found else (None, 0, 0, 0)
            return self._of(tp, n_prediction - tp, n_target - tp)
        if self.average == "micro":
            tp = sum(c[3] for c in counts)
            return self._of(
                tp, sum(c[2] for c in counts) - tp, sum(c[1] for c in counts) - tp
            )
        scores = [
            self._of(both, pred - both, tgt - both) for _, tgt, pred, both in counts
        ]
        weights = [c[1] for c in counts] if self.average == "weighted" else None
        return _nanmean(scores, weights)

    def _divide(self, numerator: int, denominator: int) -> float:
        """Divide; a zero denominator gives zero_division's value."""
        if denominator:
            return numerator / denominator
        return 0.0 if self.zero_division == "warn" else float(self.zero_division)

    def _of(self, tp: int, fp: int, fn: int) -> float:
        """Return this score from one class's counts."""
        if self.score == "precision":
            return self._divide(tp, tp + fp)
        if self.score == "recall":
            return self._divide(tp, tp + fn)
        return self._divide(2 * tp, 2 * tp + fp + fn)


precision = ClassificationMetric(
    "precision", _not_an_expression, True, score="precision"
)
recall = ClassificationMetric("recall", _not_an_expression, True, score="recall")
f1 = ClassificationMetric("f1", _not_an_expression, True, score="f1")
