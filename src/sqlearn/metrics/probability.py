"""Probability metrics: log_loss and roc_auc, read from the model's predict_proba.

Each probability column belongs to one class, in the order of the model's
``classes_`` (spec §7); both metrics take two classes or more.

As scikit-learn 1.9.1, a probability below 0 or above 1 is refused. Unlike
it, a row whose probabilities do not sum to 1 is neither warned about nor
refused: 1.9.1 warns, and that warning is not copied.
"""

import sys

import duckdb
from duckdb import Expression

from sqlearn._expr import const
from sqlearn.metrics.accuracy import Metric

__all__ = ["log_loss", "roc_auc"]

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
