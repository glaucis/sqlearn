"""Balanced accuracy and the Matthews correlation, from each class's counts.

As scikit-learn 1.9.1's ``balanced_accuracy_score`` and
``matthews_corrcoef`` (spec ``library-balanced-scores``): the same numbers
and settings. Each class's rows in the target, in the prediction and in both
come from DuckDB in one grouped query (``classification._counts``); the
scores are exact arithmetic on those few counts, rounded to a double once.
"""

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

import duckdb

from sqlearn._errors import InternalError, SqlearnError, SqlearnWarning
from sqlearn.metrics._labels import check_labels
from sqlearn.metrics.accuracy import Metric
from sqlearn.metrics.classification import Counts, _counts, _not_an_expression, _some

__all__ = ["CountMetric", "balanced_accuracy", "mcc"]


@dataclass(frozen=True)
class CountMetric(Metric):
    """A score from each class's counts: balanced accuracy or the MCC.

    Attributes
    ----------
    score : {"balanced_accuracy", "mcc"}
        Which score.
    adjusted : bool, default False
        For ``"balanced_accuracy"``: rescale it so that chance scores 0 and a
        perfect prediction 1, as scikit-learn's ``adjusted=True``.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0), (0, 0), (0, 0), (1, 0)) t(y, prediction)"
    ... )
    >>> sq.metrics.balanced_accuracy.compute(rel, "y")
    0.5
    >>> sq.metrics.mcc.compute(rel, "y")
    0.0
    """

    score: Literal["balanced_accuracy", "mcc"] = "balanced_accuracy"
    adjusted: bool = False

    def __call__(self, **settings: object) -> "CountMetric":
        """Return a copy with the given settings; the others are kept.

        Parameters
        ----------
        **settings : object
            ``adjusted`` (``balanced_accuracy`` only): True to rescale the
            score so that chance scores 0.

        Returns
        -------
        CountMetric
            The configured copy.

        Raises
        ------
        SqlearnError
            If a setting is not ``adjusted``, `adjusted` is not True or False,
            or the metric takes no settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.balanced_accuracy(adjusted=True)
        balanced_accuracy(adjusted=True)
        """
        if self.score != "balanced_accuracy":
            Metric.__call__(self, **settings)  # refuses: the MCC has no settings
            msg = f"{self.name} accepted settings it does not have"
            raise InternalError(msg)
        unknown = [k for k in settings if k != "adjusted"]
        if unknown:
            msg = (
                f"{self.name} has no setting {unknown[0]}=. Why: its only "
                "setting is adjusted, as scikit-learn's. Fix: use it, or "
                f"sq.metrics.{self.name} as it is."
            )
            raise SqlearnError(msg)
        if "adjusted" in settings and not isinstance(settings["adjusted"], bool):
            msg = (
                f"{self.name} was given adjusted={settings['adjusted']!r}. Why: "
                "adjusted is True or False, as scikit-learn's. Fix: pass one "
                "of them."
            )
            raise SqlearnError(msg)
        return replace(self, **settings)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Return the name, with adjusted when it is set."""
        return f"{self.name}(adjusted=True)" if self.adjusted else self.name

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

        Warns
        -----
        SqlearnWarning
            For balanced accuracy, when the prediction holds a class the
            target does not, or `adjusted` meets a target of one class.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql(
        ...     "SELECT * FROM (VALUES (0, 0), (1, 1), (1, 0)) t(y, prediction)"
        ... )
        >>> sq.metrics.balanced_accuracy.compute(rel, "y")
        0.75
        """
        check_labels(self.name, rel, target, prediction)
        counts = _counts(rel, target, prediction)
        if self.score == "mcc":
            return _mcc(counts)
        return self._balanced(counts)

    def _balanced(self, counts: Counts) -> float:
        """Return the balanced accuracy of each class's counts.

        As scikit-learn: the mean recall over the classes the target holds;
        a class only in the prediction has no recall and is warned about.
        Adjusted, chance is one over those classes, so one class divides by
        zero: minus infinity below a perfect score, NaN at it, as numpy.
        """
        held = [(lab, tgt, both) for lab, tgt, _, both in counts if tgt]
        extra = [lab for lab, tgt, _, _ in counts if not tgt]
        if extra:
            warnings.warn(
                f"{self.name}: the prediction holds {_some(extra)}, which the "
                "target does not hold. Why: a class with no target row has no "
                "recall, so it counts in no class's mean, as in scikit-learn. "
                "Fix: check the prediction column, or score rows that hold "
                "every predicted class.",
                SqlearnWarning,
                stacklevel=3,
            )
        score = sum((Fraction(both, tgt) for _, tgt, both in held), Fraction(0))
        score /= len(held)
        if not self.adjusted:
            return float(score)
        chance = Fraction(1, len(held))
        if chance == 1:
            warnings.warn(
                f"{self.name}(adjusted=True): the target holds one class, so "
                "chance is 1 and the rescaling divides by zero; the score is "
                f"{'NaN' if score == 1 else 'minus infinity'}, as scikit-learn "
                "gives. Fix: score rows that hold two classes or more, or "
                "leave adjusted= out.",
                SqlearnWarning,
                stacklevel=3,
            )
            return math.nan if score == 1 else -math.inf
        return float((score - chance) / (1 - chance))


def _mcc(counts: Counts) -> float:
    """Return the Matthews correlation of each class's counts.

    As scikit-learn's multiclass formula: with ``c`` rows correct of ``s``,
    and ``t_k``, ``p_k`` each class's rows in the target and the prediction,
    ``(c s - sum t_k p_k) / sqrt((s^2 - sum p_k^2) (s^2 - sum t_k^2))``; 0.0
    when the denominator is 0. All in whole numbers, then the square root of
    the exact ``numerator^2 / denominator^2`` rounded once, so the answer is
    within a double of the exact one (ADR 0016).
    """
    s = sum(t for _, t, _, _ in counts)
    c = sum(both for _, _, _, both in counts)
    numerator = c * s - sum(t * p for _, t, p, _ in counts)
    under = (s * s - sum(p * p for _, _, p, _ in counts)) * (
        s * s - sum(t * t for _, t, _, _ in counts)
    )
    if under == 0:
        return 0.0
    return math.copysign(math.sqrt(Fraction(numerator * numerator, under)), numerator)


balanced_accuracy = CountMetric(
    "balanced_accuracy", _not_an_expression, True, score="balanced_accuracy"
)
mcc = CountMetric("mcc", _not_an_expression, True, score="mcc")
