"""Validate precision, recall, f1 and fbeta against exact arithmetic and scikit-learn.

The canonical value is computed in pure Python as a `Fraction` (ADR 0016):
each class's true positives, false positives and false negatives counted
over the rows, each class's score a ratio of whole numbers, and the macro and
weighted averages exact means of those ratios. A class whose score divides by
zero counts as 0, as under the default ``zero_division="warn"``. Beside
sqlearn: scikit-learn's ``precision_score``, ``recall_score``,
``f1_score`` and ``fbeta_score`` with the same ``average`` and ``pos_label``;
their macro and weighted means are sums of doubles, 1 double from the exact
value at worst.
Labels with NULL, and no rows, have no right answer: sqlearn must refuse
them.
"""

from collections.abc import Callable
from fractions import Fraction

import numpy as np
from sklearn.metrics import f1_score, fbeta_score, precision_score, recall_score

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value: 0, as sqlearn averages the whole counts as fractions and
# rounds once. The first build averaged in doubles and measured 1 double on 10
# of 105 cases, as scikit-learn's np.average still does (its anomalies here).
# Loosening it needs a written reason here, never a quiet edit.
BOUND = 0

SCORES: dict[str, Callable[..., float]] = {
    "precision": precision_score,
    "recall": recall_score,
    "f1": f1_score,
    "fbeta": fbeta_score,
}
BETAS = (0.5, 2.0)
RUNS: list[tuple[str, float | None]] = [
    ("precision", None),
    ("recall", None),
    ("f1", None),
    *(("fbeta", b) for b in BETAS),
]
AVERAGES = ("binary", "macro", "micro", "weighted")


def _ratio(numerator: int, denominator: int) -> Fraction:
    return Fraction(numerator, denominator) if denominator else Fraction(0)


def _score(name: str, tp: int, fp: int, fn: int, beta: float | None = None) -> Fraction:
    if name == "fbeta":
        b2 = Fraction(beta) ** 2  # type: ignore[arg-type]
        return _ratio((1 + b2) * tp, (1 + b2) * tp + b2 * fn + fp)
    if name == "precision":
        return _ratio(tp, tp + fp)
    if name == "recall":
        return _ratio(tp, tp + fn)
    return _ratio(2 * tp, 2 * tp + fp + fn)


def exact(
    name: str,
    average: str,
    y: tuple,
    p: tuple,
    pos_label: object,
    beta: float | None = None,
) -> Fraction:
    """Return the score as an exact fraction, from counts over the rows."""
    labels = sorted(set(y) | set(p))
    counts = {
        c: (
            sum(a == c and b == c for a, b in zip(y, p, strict=True)),
            sum(a != c and b == c for a, b in zip(y, p, strict=True)),
            sum(a == c and b != c for a, b in zip(y, p, strict=True)),
        )
        for c in labels
    }
    if average == "binary":
        return _score(name, *counts.get(pos_label, (0, 0, 0)), beta)
    if average == "micro":
        return _score(
            name, *(sum(c[i] for c in counts.values()) for i in range(3)), beta
        )
    scores = [_score(name, *counts[c], beta) for c in labels]
    if average == "macro":
        return sum(scores, Fraction(0)) / len(scores)
    support = [counts[c][0] + counts[c][2] for c in labels]
    return sum(
        (s * w for s, w in zip(scores, support, strict=True)), Fraction(0)
    ) / sum(support)


def _datasets() -> list[tuple[_cases.Dataset, str, tuple, str, tuple, str, list]]:
    """Return each dataset, its columns and type, and the labels it draws from."""
    rng = np.random.default_rng(_cases.SEED)

    def draw(n: int, labels: list) -> tuple[tuple, tuple]:
        y = rng.choice(len(labels), n)
        p = np.where(rng.random(n) < 0.7, y, rng.choice(len(labels), n))
        return tuple(labels[i] for i in y), tuple(labels[i] for i in p)

    words = list(_cases.WORDS[:3])
    out = []
    for size, n in _cases.SIZES.items():
        for labels, kind, what in (
            ([0, 1], "INTEGER", "2 labels"),
            ([0, 1, 2], "INTEGER", "3 labels"),
            (words[:2], "VARCHAR", "2 text labels"),
            (words, "VARCHAR", "3 text labels"),
        ):
            y, p = draw(n, labels)
            name = f"{size}, {what}"
            out.append(
                (name, "y", y, "prediction", p, kind, f"{n:,} rows, {what}", labels)
            )
    y, p = draw(1_000, [0, 1, 2])
    p = tuple(_cases._gaps(rng, list(p), None))
    out.append(("null", "y", y, "prediction", p, "INTEGER",
                "a tenth of the predictions NULL", [0, 1, 2]))  # fmt: skip
    out.append(("empty", "y", (), "prediction", (), "INTEGER", "no rows", [0, 1]))
    y, p = draw(1_000, [0, 1, 2])
    out.append(("reserved", "select", y, "from", p, "INTEGER",
                'columns named "select" and "from"', [0, 1, 2]))  # fmt: skip
    return [
        (_cases.Dataset(name, y_col, y, note), y_col, y, p_col, p, kind, labels)
        for name, y_col, y, p_col, p, kind, note, labels in out
    ]


def cases() -> list[dict]:
    """Return the cases of precision, recall, f1 and fbeta: each average, dataset."""
    out = []
    for data, y_col, y, p_col, p, kind, labels in _datasets():
        answerable = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))
        two = len(labels) == 2
        pos_label = labels[-1]
        for name, beta in RUNS:
            for average in AVERAGES:
                if average == "binary" and not two and answerable:
                    continue
                settings = {"average": average}
                if beta is not None:
                    settings["beta"] = beta
                if average == "binary":
                    settings["pos_label"] = pos_label

                def ours(
                    name=name, settings=settings, y=y, p=p, kind=kind,
                    y_col=y_col, p_col=p_col,
                ) -> float:  # fmt: skip
                    rel = _cases.sqlearn_table({y_col: y, p_col: p}, kind)
                    metric = getattr(sq.metrics, name)(**settings)
                    return metric.compute(rel, y_col, p_col)

                def theirs(name=name, settings=settings, y=y, p=p) -> float:
                    return SCORES[name](list(y), list(p), **settings)

                out += _cases.measure_all(
                    step=name,
                    formula=f"{name}, average={average}"
                    + ("" if beta is None else f", beta={beta}"),
                    data=data,
                    type=kind,
                    exact=exact(name, average, y, p, pos_label, beta)
                    if answerable
                    else None,
                    bound=BOUND,
                    answers={"sqlearn": ours, "scikit-learn": theirs},
                )
    return out
