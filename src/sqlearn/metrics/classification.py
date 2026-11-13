"""Precision, recall, F1 and F-beta, counted per class in one grouped query.

As scikit-learn 1.9.1's ``precision_score``, ``recall_score``,
``f1_score`` and ``fbeta_score`` (spec §1, §3): the same settings, defaults
and refusals. Each class's rows in the target, in the prediction and in both
come from DuckDB; the scores are arithmetic on those few counts (ADR 0042).
"""

import math
import numbers
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import (
    InternalError,
    SqlearnError,
    SqlearnWarning,
    UndefinedMetricWarning,
)
from sqlearn._expr import const
from sqlearn.metrics._labels import check_labels
from sqlearn.metrics.accuracy import Metric

__all__ = ["ClassificationMetric", "f1", "fbeta", "precision", "recall"]

Counts = list[tuple[object, int, int, int]]

AVERAGES = ("binary", "macro", "micro", "weighted")
_DEFAULTS = {"average": "binary", "pos_label": 1, "zero_division": "warn"}
_BETA_DEFAULTS = {"beta": None, **_DEFAULTS}


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
    if not kept:
        return math.nan
    total = sum(w for _, w in kept)
    if total == 0:
        # Every class left has no target rows: scikit-learn's _nanaverage
        # falls back to the plain mean of the scores left.
        return float(sum((v for v, _ in kept), Fraction(0)) / len(kept))
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
    "fbeta": "no true nor predicted samples",
}


def _some(labels: list[object], shown: int = 10) -> str:
    """Name the first labels, and how many there are in all when more."""
    head = ", ".join(repr(lab) for lab in labels[:shown])
    return head if len(labels) <= shown else f"{head}, ...; {len(labels)} in all"


def _is_text(value: object) -> bool:
    """Say whether a label is text; every other label is a number (bool too)."""
    return isinstance(value, str)


def _type_hint(pos_label: object, labels: list[object]) -> str:
    """Return a sentence on pos_label's kind when it differs from the labels'.

    Text against numbers names the number the text reads as, and numbers
    against text names the text; "" when the kinds agree. sqlearn never
    converts pos_label: the hint only says what to pass.
    """
    if {_is_text(lab) for lab in labels} != {not _is_text(pos_label)}:
        return ""
    if _is_text(pos_label):
        number = _as_number(str(pos_label))
        named = f" Did you mean pos_label={number!r}?" if number is not None else ""
        return (
            f" The labels are numbers and pos_label={pos_label!r} is text, "
            f"which is a different label.{named}"
        )
    return (
        f" The labels are text and pos_label={pos_label!r} is a number, "
        f"which is a different label. Did you mean pos_label={str(pos_label)!r}?"
    )


def _as_number(text: str) -> int | float | None:
    """Read text as a whole number, else a float, else None."""
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            continue
    return None


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and a == b


@dataclass(frozen=True)
class ClassificationMetric(Metric):
    """A classification score counted per class: precision, recall, F1 or fbeta.

    Attributes
    ----------
    score : {"precision", "recall", "f1", "fbeta"}
        Which score.
    beta : float, optional
        For ``"fbeta"``, the weight of recall against precision, in
        ``[0, inf]``; it has no default, so ``sq.metrics.fbeta`` must be
        called with ``beta=``. ``f1`` is ``beta=1.0``.
    average : str, default "binary"
        How the classes' scores are combined, as scikit-learn's `average`.
    pos_label : object, default 1
        The class scored under ``average="binary"``.
    zero_division : str or float, default "warn"
        The score of a class whose score divides by zero.

    Notes
    -----
    ``pos_label`` is never converted: ``1`` and ``"1"`` are different labels,
    as in SQL. When ``pos_label`` is not among the labels and is text where
    they are numbers (or the reverse), the refusal, or the warning of a score
    set to 0.0, adds a hint naming the value likely meant, such as
    ``Did you mean pos_label=1?``.

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

    score: Literal["precision", "recall", "f1", "fbeta"] = "f1"
    beta: float | None = None
    average: str = "binary"
    pos_label: object = 1
    zero_division: str | float = "warn"

    def __call__(self, **settings: object) -> "ClassificationMetric":
        """Return a copy with the given settings; the others are kept.

        Parameters
        ----------
        **settings : object
            Any of ``beta`` (``fbeta`` only: the weight of recall against
            precision, a number in ``[0, inf]``), ``average``
            ({"binary", "macro", "micro", "weighted"}: how the classes'
            scores are combined), ``pos_label`` (the class
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
            If a setting is not one of the metric's, or `beta`, `average`
            or `zero_division` is not one of its values.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.f1(average="macro")
        f1(average='macro')
        >>> sq.metrics.fbeta(beta=2)
        fbeta(beta=2)
        """
        known = self._settings()
        unknown = [k for k in settings if k not in known]
        if unknown:
            msg = (
                f"{self.name} has no setting {unknown[0]}=. Why: its settings "
                f"are {', '.join(known)}, as scikit-learn's. Fix: use one "
                "of them."
            )
            raise SqlearnError(msg)
        changes = dict(settings)
        if "beta" in changes:
            beta = changes["beta"]
            if not isinstance(beta, numbers.Real) or not (0 <= float(beta) <= math.inf):
                msg = (
                    f"{self.name} was given beta={beta!r}. Why: beta is the "
                    "weight of recall against precision, a number from 0 to "
                    "inf, as scikit-learn's. Fix: pass one, as "
                    "sq.metrics.fbeta(beta=2.0)."
                )
                raise SqlearnError(msg)
        if "average" in changes and changes["average"] not in AVERAGES:
            averages = ", ".join(repr(a) for a in AVERAGES)
            msg = (
                f"{self.name} was given average={changes['average']!r}. Why: "
                f'the averages are {averages} (scikit-learn\'s "samples" is for '
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
        configured = replace(self, **changes)  # type: ignore[arg-type]
        if configured.average != "binary" and not _same(configured.pos_label, 1):
            warnings.warn(
                f"pos_label={configured.pos_label!r} is ignored when "
                f"average={configured.average!r}: only average='binary' scores "
                "one class, as in scikit-learn. Fix: leave pos_label= out, or "
                "use average='binary'.",
                SqlearnWarning,
                stacklevel=2,
            )
        return configured

    def _settings(self) -> dict[str, object]:
        """Return the settings this metric takes, with their defaults."""
        return dict(_BETA_DEFAULTS if self.score == "fbeta" else _DEFAULTS)

    def _ready(self) -> None:
        """Refuse an fbeta without its beta: it has no score to compute."""
        if self.score == "fbeta" and self.beta is None:
            msg = (
                "fbeta needs beta=, the weight of recall against precision. "
                "Why: scikit-learn's fbeta_score has no default for it, and "
                "sqlearn does not choose one for you. Fix: pass it, as "
                "sq.metrics.fbeta(beta=2.0)."
            )
            raise SqlearnError(msg)

    def __repr__(self) -> str:
        """Return the name, with the settings away from the defaults."""
        changed = [
            f"{k}={getattr(self, k)!r}"
            for k, v in self._settings().items()
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
        self._ready()
        check_labels(self.name, rel, target, prediction)
        hint = ""
        counts = _counts(rel, target, prediction)
        labels = [c[0] for c in counts]
        if self.average == "binary":
            self._check_binary(labels)
            found = [c for c in counts if c[0] == self.pos_label]
            scored = found or [(self.pos_label, 0, 0, 0)]
            hint = "" if found else _type_hint(self.pos_label, labels)
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
        self._warn_undefined(undefined, hint, micro=self.average == "micro")
        if self.average in ("binary", "micro"):
            return math.nan if scores[0] is None else float(scores[0])
        weights = [c[1] for c in counts] if self.average == "weighted" else None
        return _nanmean(scores, weights)

    def _warn_undefined(
        self,
        undefined: list[object],
        hint: str = "",
        *,
        micro: bool = False,
        stacklevel: int = 3,
    ) -> None:
        """Warn, in scikit-learn's words, of the classes whose score divides by zero.

        Only under ``zero_division="warn"`` and for a score scikit-learn
        warns about. `stacklevel` counts from this method: 1 is the warning's own line
        here, 2 the method that called this one, 3 that method's caller.
        """
        if not (undefined and self.zero_division == "warn" and self._warns()):
            return
        name = (
            self.score.capitalize()
            if self.score in ("precision", "recall")
            else "F-score"
        )
        where = (
            f"due to {_UNDEFINED[self.score]}"
            if micro
            else f"in labels with {_UNDEFINED[self.score]}: {undefined}"
        )
        warnings.warn(
            f"{name} is ill-defined and being set to 0.0 {where}. Fix: pass "
            "zero_division= to choose the value (0.0, 1.0 or nan)."
            f"{hint}",
            UndefinedMetricWarning,
            stacklevel=stacklevel,
        )

    def _per_class(
        self, counts: Counts, *, stacklevel: int = 3
    ) -> list[Fraction | None]:
        """Return each class's score from its counts, warning as `compute` does.

        The classes' scores of a report: the same arithmetic and the same
        warning as ``average=None`` would give, from counts already fetched.
        """
        scores = [
            self._of(both, pred - both, tgt - both) for _, tgt, pred, both in counts
        ]
        undefined = [
            lab
            for lab, tgt, pred, both in counts
            if self._denominator(both, pred - both, tgt - both) == 0
        ]
        self._warn_undefined(undefined, stacklevel=stacklevel + 1)
        return scores

    def _check_binary(self, labels: list[object]) -> None:
        """Refuse what scikit-learn refuses under ``average="binary"``."""
        if len(labels) > 2:
            msg = (
                f"{self.name} with average='binary' scores one class of two, "
                f"and the target and prediction hold {len(labels)} classes "
                f"({_some(labels)}). Fix: pass average= one of 'macro', 'micro' or "
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
                f"{_type_hint(self.pos_label, labels)}"
            )
            raise SqlearnError(msg)

    def _form(self) -> str:
        """Return the counts this score is: fbeta at 0 is precision, at inf recall."""
        if self.score == "fbeta":
            if self.beta == 0:
                return "precision"
            if self.beta == math.inf:
                return "recall"
        return self.score

    def _warns(self) -> bool:
        """Say whether a zero division warns: scikit-learn warns for F only.

        Its fbeta at 0 and at inf are the precision and the recall, divided
        without a warning.
        """
        return self.score != "fbeta" or self._form() == "fbeta"

    def _b2(self) -> Fraction:
        """Return beta squared, exactly (1 for f1)."""
        if self.score == "f1" or self.beta is None:
            return Fraction(1)
        return Fraction(self.beta) ** 2

    def _denominator(self, tp: int, fp: int, fn: int) -> Fraction:
        """Return what this score divides by, for one class's counts."""
        form = self._form()
        if form == "precision":
            return Fraction(tp + fp)
        if form == "recall":
            return Fraction(tp + fn)
        b2 = self._b2()
        return (1 + b2) * tp + b2 * fn + fp

    def _divide(self, numerator: Fraction, denominator: Fraction) -> Fraction | None:
        """Divide exactly; a zero denominator gives zero_division's value.

        None stands for NaN, which the averages leave out.
        """
        if denominator:
            return numerator / denominator
        if self.zero_division == "warn":
            return Fraction(0)
        value = float(self.zero_division)
        return None if math.isnan(value) else Fraction(value)

    def _of(self, tp: int, fp: int, fn: int) -> Fraction | None:
        """Return this score from one class's counts."""
        form = self._form()
        numerator = (
            Fraction(tp) if form in ("precision", "recall") else (1 + self._b2()) * tp
        )
        return self._divide(numerator, self._denominator(tp, fp, fn))


precision = ClassificationMetric(
    "precision", _not_an_expression, True, score="precision"
)
recall = ClassificationMetric("recall", _not_an_expression, True, score="recall")
f1 = ClassificationMetric("f1", _not_an_expression, True, score="f1", beta=1.0)
fbeta = ClassificationMetric("fbeta", _not_an_expression, True, score="fbeta")
