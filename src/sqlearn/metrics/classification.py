"""Precision, recall and F1, counted per class in one grouped query.

As scikit-learn 1.9.1's ``precision_score``, ``recall_score`` and
``f1_score`` (spec §1): the same settings, defaults and refusals. Each
class's rows in the target, in the prediction and in both come from DuckDB;
the scores are arithmetic on those few counts (ADR 0042).
"""

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import InternalError, SqlearnError, UndefinedMetricWarning
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


def _nanmean(
    values: Sequence[Fraction | None], weights: Sequence[int] | None = None
) -> float:
    """Average exactly, leaving undefined (NaN) scores out; all NaN is NaN.

    As scikit-learn's ``_nanaverage``, but in fractions of the whole counts,
    rounded to a double once, so the answer is the double nearest the exact
    score (ADR 0016).
    """
    kept = [
        (v, 1 if weights is None else weights[i])
        for i, v in enumerate(values)
        if v is not None
    ]
    total = sum(w for _, w in kept)
    if not kept or total == 0:
        return math.nan
    return float(sum((v * w for v, w in kept), Fraction(0)) / total)


def _valid_zero_division(value: object) -> bool:
    if value == "warn":
        return True
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isnan(value) or value in (0, 1)


_UNDEFINED = {
    "precision": "no predicted samples",
    "recall": "no true samples",
    "f1": "no true nor predicted samples",
}


def _kind(dtype: str) -> str:
    """Name the kind of label a column type holds: text or number."""
    return "text" if dtype.startswith(("VARCHAR", "ENUM")) else "number"


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
        if _kind(types[target]) != _kind(types[prediction]):
            msg = (
                f"{self.name} cannot be computed: column {target!r} "
                f"({types[target]}) holds {_kind(types[target])} labels and "
                f"column {prediction!r} ({types[prediction]}) "
                f"{_kind(types[prediction])} labels, so no label can match. "
                "scikit-learn refuses such a mix too. Fix: cast one so both "
                "hold the same kind of label."
            )
            raise SqlearnError(msg)
        floats = [c for c in columns if types[c] in _FLOATS]
        fractional = [
            c for c in columns if types[c] in _FLOATS or types[c].startswith("DECIMAL")
        ]
        whole = [
            _count(
                duckdb.CaseExpression(
                    ColumnExpression(c) != _fn("floor", ColumnExpression(c)), const(1)
                )
            )
            for c in fractional
        ]
        row = rel.aggregate(
            [
                _count(const(1)),
                *(_count(ColumnExpression(c)) for c in columns),
                *(
                    _count(duckdb.CaseExpression(_isnan(ColumnExpression(c)), const(1)))
                    for c in floats
                ),
                *whole,
            ]
        ).fetchall()[0]
        total, seen = row[0], row[1:3]
        nans, parts = row[3 : 3 + len(floats)], row[3 + len(floats) :]
        _refuse_gaps(self.name, target, columns, floats, total, seen, nans)
        for column, n_part in zip(fractional, parts, strict=True):
            if n_part:
                msg = (
                    f"{self.name} cannot be computed: column {column!r} has "
                    f"{n_part} of {total} rows that are not whole numbers, so "
                    "it holds continuous values, not class labels. "
                    "scikit-learn refuses continuous targets too. Fix: score "
                    "a classifier's predict, or a regression with "
                    "sq.metrics.rmse, mae or r2."
                )
                raise SqlearnError(msg)
        counts = _counts(rel, target, prediction)
        labels = [c[0] for c in counts]
        if self.average == "binary":
            self._check_binary(labels)
            found = [c for c in counts if c[0] == self.pos_label]
            scored = found or [(self.pos_label, 0, 0, 0)]
        elif self.average == "micro":
            tp = sum(c[3] for c in counts)
            scored = [
                ("micro", sum(c[1] for c in counts), sum(c[2] for c in counts), tp)
            ]
        else:
            scored = counts
        scores = [
            self._of(both, pred - both, tgt - both) for _, tgt, pred, both in scored
        ]
        undefined = [
            lab
            for (lab, tgt, pred, both), _ in zip(scored, scores, strict=True)
            if self._denominator(both, pred - both, tgt - both) == 0
        ]
        if undefined and self.zero_division == "warn":
            name = self.score.capitalize() if self.score != "f1" else "F-score"
            warnings.warn(
                f"{name} is ill-defined and being set to 0.0 in labels with "
                f"{_UNDEFINED[self.score]}: {undefined}. Fix: pass "
                "zero_division= to choose the value (0.0, 1.0 or nan).",
                UndefinedMetricWarning,
                stacklevel=2,
            )
        if self.average in ("binary", "micro"):
            return math.nan if scores[0] is None else float(scores[0])
        weights = [c[1] for c in counts] if self.average == "weighted" else None
        return _nanmean(scores, weights)

    def _check_binary(self, labels: list[object]) -> None:
        """Refuse what scikit-learn refuses under ``average="binary"``."""
        if len(labels) > 2:
            msg = (
                f"{self.name} with average='binary' scores one class of two, "
                f"and the target and prediction hold {len(labels)} classes "
                f"({labels}). Fix: pass average= one of 'macro', 'micro' or "
                f"'weighted', as sq.metrics.{self.name}(average='macro')."
            )
            raise SqlearnError(msg)
        if len(labels) == 2 and not any(lab == self.pos_label for lab in labels):
            found = ", ".join(repr(lab) for lab in labels)
            msg = (
                f"{self.name} with average='binary' scores the class "
                f"pos_label={self.pos_label!r}, which is none of the labels "
                f"found ({found}). Fix: pass pos_label= the positive one, as "
                f"sq.metrics.{self.name}(pos_label={labels[-1]!r})."
            )
            raise SqlearnError(msg)

    def _denominator(self, tp: int, fp: int, fn: int) -> int:
        """Return what this score divides by, for one class's counts."""
        if self.score == "precision":
            return tp + fp
        if self.score == "recall":
            return tp + fn
        return 2 * tp + fp + fn

    def _divide(self, numerator: int, denominator: int) -> Fraction | None:
        """Divide exactly; a zero denominator gives zero_division's value.

        None stands for NaN, which the averages leave out.
        """
        if denominator:
            return Fraction(numerator, denominator)
        if self.zero_division == "warn":
            return Fraction(0)
        value = float(self.zero_division)
        return None if math.isnan(value) else Fraction(value)

    def _of(self, tp: int, fp: int, fn: int) -> Fraction | None:
        """Return this score from one class's counts."""
        numerator = 2 * tp if self.score == "f1" else tp
        return self._divide(numerator, self._denominator(tp, fp, fn))


precision = ClassificationMetric(
    "precision", _not_an_expression, True, score="precision"
)
recall = ClassificationMetric("recall", _not_an_expression, True, score="recall")
f1 = ClassificationMetric("f1", _not_an_expression, True, score="f1")
