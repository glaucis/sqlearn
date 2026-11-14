"""Probability metrics: log_loss, roc_auc and average_precision.

They read the model's predict_proba. Each probability column belongs to one
class, in the order of the model's ``classes_`` (spec §7); the metrics take
two classes or more.

As scikit-learn 1.9.1, a probability below 0 or above 1 is refused. Unlike
it, a row whose probabilities do not sum to 1 is neither warned about nor
refused: 1.9.1 warns, and that warning is not copied.

The `pos_label` hint (`_type_hint`) comes from `classification`.
"""

import sys
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace

import duckdb
from duckdb import Expression

from sqlearn._errors import SqlearnError, UndefinedMetricWarning
from sqlearn._expr import const
from sqlearn.metrics.accuracy import Metric
from sqlearn.metrics.classification import _type_hint

__all__ = ["AveragePrecision", "average_precision", "log_loss", "roc_auc"]

_EPS = sys.float_info.epsilon


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _log_loss(
    y: Expression, probabilities: list[Expression], classes: list[object]
) -> Expression:
    # The mean of minus the log of each row's probability of its own class.
    #
    # As scikit-learn 1.9.1's log_loss: each probability is clipped to
    # [eps, 1 - eps] with float64's eps, so a certain wrong answer costs a
    # finite loss; a row's probabilities are not normalised (1.9.1 only warns
    # when they do not sum to 1). The mean is compensated (favg, ADR 0033).
    # A probability below 0 or above 1 is refused, as 1.9.1 refuses it, by
    # Metric.compute before this value is read.
    own = duckdb.CaseExpression(y == const(classes[0]), probabilities[0])
    for label, p in zip(classes[1:], probabilities[1:], strict=True):
        own = own.when(y == const(label), p)
    clipped = _fn(
        "greatest", const(_EPS), _fn("least", own.cast("DOUBLE"), const(1.0 - _EPS))
    )
    return -_fn("favg", _fn("ln", clipped))


def _ranks(probabilities: list[Expression]) -> list[Expression]:
    # Twice each row's rank by a class's probability, ties at their average.
    #
    # The average rank of a tie is rank() + (rows tied - 1) / 2, so twice it
    # is a whole number, and the sums below stay exact in integers. Two
    # classes rank by the second class's probability only, as scikit-learn
    # scores proba[:, 1].
    scored = probabilities[1:] if len(probabilities) == 2 else probabilities
    return [
        const(2) * _fn("rank").over(order_by=[p])
        + _fn("count_star").over(partition_by=[p])
        - const(1)
        for p in scored
    ]


def _auc(y: Expression, twice_rank: Expression, label: object) -> Expression:
    # One class against the rest: the Mann-Whitney statistic over its pairs.
    #
    # With n_c rows of the class among n, and R twice the sum of their
    # average ranks, the area is (R - n_c (n_c + 1)) / (2 n_c (n - n_c)):
    # numerator and denominator are exact integers, divided once. A class
    # with every row or none has no pair: NULL, which compute refuses.
    mine = y == const(label)
    n_c = _fn("count", duckdb.CaseExpression(mine, const(1))).cast("HUGEINT")
    n = _fn("count_star").cast("HUGEINT")
    twice = _fn("sum", duckdb.CaseExpression(mine, twice_rank).otherwise(const(0)))
    numerator = twice.cast("HUGEINT") - n_c * (n_c + const(1))
    denominator = const(2) * n_c * (n - n_c)
    return duckdb.CaseExpression(
        denominator != const(0), numerator.cast("DOUBLE") / denominator.cast("DOUBLE")
    )


def _roc_auc(
    y: Expression, ranks: list[Expression], classes: list[object]
) -> Expression:
    # Two classes: the second class against the first. More: each class
    # against the rest, averaged with equal weight (scikit-learn's
    # multi_class="ovr", average="macro"); one undefined area makes it NULL.
    if len(classes) == 2:
        return _auc(y, ranks[0], classes[1])
    areas = [_auc(y, r, c) for r, c in zip(ranks, classes, strict=True)]
    total = areas[0]
    for area in areas[1:]:
        total = total + area
    return total / const(float(len(areas)))


log_loss = Metric("log_loss", _log_loss, False, needs="predict_proba")
roc_auc = Metric("roc_auc", _roc_auc, True, needs="predict_proba", windows=_ranks)


def _unused(*_: Expression) -> Expression:
    raise AssertionError("AveragePrecision sets its own expression")  # pragma: no cover


@dataclass(frozen=True)
class AveragePrecision(Metric):
    """The average precision of a class, as scikit-learn's ``average_precision_score``.

    Two classes score the class ``pos_label`` from its probability column;
    more classes score each against the rest and average them with equal
    weight (scikit-learn's ``average="macro"``).

    Attributes
    ----------
    pos_label : object, default 1
        The class scored when there are two. It is never converted: ``1`` and
        ``"1"`` are different labels, but ``1`` and ``1.0`` are the same. With
        more than two classes it must stay 1, as in scikit-learn.

    Notes
    -----
    The area is the step sum of the precision-recall curve (one threshold
    per distinct score), ``sum(delta_tp_k * tp_k / n_k) / P``. Each term is
    a double, summed with compensation (ADR 0033). With two classes and no
    row of ``pos_label`` the score is 0.0 with a warning; with only rows of
    it, 1.0. With more classes a class missing from the target refuses.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0.9, 0.1), (1, 0.4, 0.6), (0, 0.3, 0.7), "
    ...     "(1, 0.2, 0.8)) t(y, __sqlearn_proba_0, __sqlearn_proba_1)"
    ... )
    >>> round(sq.metrics.average_precision.compute(rel, "y", classes=[0, 1]), 4)
    0.8333
    """

    pos_label: object = 1

    def __post_init__(self) -> None:
        """Set the aggregate, which reads this metric's settings."""
        object.__setattr__(self, "expression", self._expression)

    def __call__(self, **settings: object) -> "AveragePrecision":
        """Return a copy with the given settings; the others are kept.

        Parameters
        ----------
        **settings : object
            ``pos_label``: the class scored when there are two.

        Returns
        -------
        AveragePrecision
            The configured copy.

        Raises
        ------
        SqlearnError
            If a setting is not ``pos_label``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.average_precision(pos_label="churned")
        average_precision(pos_label='churned')
        """
        unknown = [k for k in settings if k != "pos_label"]
        if unknown:
            msg = (
                f"{self.name} has no setting {unknown[0]}=. Why: its only "
                "setting is pos_label, as scikit-learn's. Fix: use it, or "
                f"sq.metrics.{self.name} as it is."
            )
            raise SqlearnError(msg)
        return replace(self, **settings)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Return the name, with pos_label when it is not 1."""
        same = type(self.pos_label) is int and self.pos_label == 1
        return self.name if same else f"{self.name}(pos_label={self.pos_label!r})"

    def _scored(self, labels: Sequence[object]) -> list[int]:
        """Return the index of each class scored, refusing what scikit-learn does."""
        if len(labels) > 2:
            if self.pos_label != 1:
                msg = (
                    f"{self.name} was given pos_label={self.pos_label!r} with "
                    f"{len(labels)} classes. Why: with more than two classes "
                    "each is scored against the rest, and scikit-learn fixes "
                    "pos_label to 1 there. Fix: leave pos_label= out."
                )
                raise SqlearnError(msg)
            return list(range(len(labels)))
        for i, label in enumerate(labels):
            if label == self.pos_label:
                return [i]
        known = list(labels)
        msg = (
            f"{self.name} scores the class pos_label={self.pos_label!r}, which "
            f"is none of the classes {known}.{_type_hint(self.pos_label, known)}"
            f" Fix: pass pos_label= the positive one, as "
            f"sq.metrics.{self.name}(pos_label={labels[-1]!r})."
        )
        raise SqlearnError(msg)

    def _stage(
        self, y: Expression, values: list[Expression], labels: list[object]
    ) -> list[Expression]:
        # Per row of a scored class: the precision at the row's score (the
        # positives and rows at or above it) if the row is a positive, else 0.
        # A group of rows tied on a score then adds delta_tp * precision, the
        # step's area, over its positives. The default frame of an ordered
        # window ends at the last row tied with this one.
        staged = []
        for i in self._scored(labels):
            mine = y == const(labels[i])
            order = [values[i].desc()]
            tp = _fn(
                "sum", duckdb.CaseExpression(mine, const(1)).otherwise(const(0))
            ).over(order_by=order)
            n = _fn("count_star").over(order_by=order)
            staged.append(
                duckdb.CaseExpression(
                    mine, tp.cast("DOUBLE") / n.cast("DOUBLE")
                ).otherwise(const(0.0))
            )
        return staged

    def _expression(
        self, y: Expression, staged: list[Expression], labels: list[object]
    ) -> Expression:
        # Each scored class: the compensated sum of the staged terms over its
        # positives. No positives: 0.0 with two classes (compute warns), NULL
        # with more, which compute refuses; the macro mean is NULL if any is.
        areas = []
        for i, term in zip(self._scored(labels), staged, strict=True):
            positives = _fn(
                "count", duckdb.CaseExpression(y == const(labels[i]), const(1))
            )
            none = const(0.0) if len(labels) == 2 else const(None)
            areas.append(
                duckdb.CaseExpression(positives == const(0), none).otherwise(
                    _fn("fsum", term) / positives.cast("DOUBLE")
                )
            )
        total = areas[0]
        for area in areas[1:]:
            total = total + area
        return total / const(float(len(areas))) if len(areas) > 1 else total

    def compute(
        self,
        rel: duckdb.DuckDBPyRelation,
        target: str,
        prediction: str = "prediction",
        classes: Sequence[object] | None = None,
    ) -> float:
        """Compute the average precision over a relation.

        Parameters
        ----------
        rel : duckdb.DuckDBPyRelation
            The rows, with a target column and a column
            ``__sqlearn_proba_<i>`` for each class.
        target : str
            The name of the target column.
        prediction : str, default "prediction"
            Unused: this metric reads probabilities.
        classes : sequence
            The model's ``classes_``: the label of each probability column.

        Returns
        -------
        float
            The score.

        Raises
        ------
        SqlearnError
            As `Metric.compute`, and if ``pos_label`` is not one of two
            classes, or is not 1 with more.
        MissingClassError
            If, with more than two classes, one has no row in the target.

        Warns
        -----
        UndefinedMetricWarning
            With two classes and no row of ``pos_label``; the score is 0.0.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> rel = duckdb.sql(
        ...     "SELECT * FROM (VALUES (1, 0.2, 0.8), (0, 0.7, 0.3)) "
        ...     "t(y, __sqlearn_proba_0, __sqlearn_proba_1)"
        ... )
        >>> sq.metrics.average_precision.compute(rel, "y", classes=[0, 1])
        1.0
        """
        value = super().compute(rel, target, prediction, classes)
        # An average precision above 0 needs a positive row, so 0.0 is the
        # no-positive case; only two classes score it instead of refusing.
        if value == 0.0:
            warnings.warn(
                f"No positive class found in the target: the average precision "
                f"of pos_label={self.pos_label!r} is set to 0.0, as "
                "scikit-learn does (its recall is one at every threshold). "
                "Fix: score rows that hold the class, or check pos_label=.",
                UndefinedMetricWarning,
                stacklevel=2,
            )
        return value


average_precision = AveragePrecision(
    "average_precision", _unused, True, needs="predict_proba"
)
