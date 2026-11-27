"""Validate log_loss, roc_auc, average_precision and brier against exact arithmetic.

The canonical values are computed in pure Python from the doubles' exact
values (ADR 0016). log_loss: minus the mean of the natural log of each row's
probability of its own class, clipped to [eps, 1 - eps] with float64's eps as
scikit-learn 1.9.1 clips, at 50 digits with mpmath. roc_auc: for each class
against the rest, the share of (class, other) pairs the class's probability
ranks higher, a tie counting half, as a `Fraction`; two classes score the
second class, more average the classes with equal weight (scikit-learn's
``multi_class="ovr"``, ``average="macro"``). average_precision: for each class
against the rest, the sum over the distinct scores, highest first, of
(positives at the score) times (positives at or above it over rows at or above
it), over the positives, as a `Fraction`; two classes score the second class,
more average the classes. brier: the mean over rows of the sum over the
classes of (probability - 1 for the row's class, else 0) squared, halved with
two classes (scikit-learn's ``scale_by_half="auto"``), as a `Fraction`.
Beside sqlearn: DuckDB alone
(and at one thread), numpy (with scipy's average ranks) and scikit-learn.
Probabilities with NULL or NaN, and no rows, have no right answer: sqlearn
must refuse them; so must roc_auc where every target is one class.
"""

import math
import sys
from fractions import Fraction
from itertools import groupby

import duckdb
import mpmath
import numpy as np
from scipy.stats import rankdata
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

import sqlearn as sq
from validation import _cases

EPS = sys.float_info.epsilon
PROBA = "__sqlearn_proba_"

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value. Loosening a bound needs a written reason here, never a
# quiet edit. Measured at 1 double at most for both, on every dataset:
# roc_auc divides two exact integers once per class (then averages the
# classes); log_loss is a compensated mean of logs. average_precision, first
# measured at 1 double at most: each step's precision is one rounded
# quotient, the steps are summed with compensation (fsum, ADR 0033), and the
# sum is divided once per class, so the roundings of the quotients are all
# the error there is. The plain-DuckDB reference answers (DuckDB's own
# sum, up to 14 doubles off) are flagged as anomalies: expected. brier, first
# measured at 1 double at most (2026-11-19): each square of a difference is a
# rounded double before the compensated mean (favg, ADR 0033).
BOUNDS = {"log_loss": 2, "roc_auc": 1, "average_precision": 1, "brier": 1}


def _draw(
    rng: np.random.Generator, classes: int, rows: int, *, ties: bool = False
) -> tuple[tuple, list[tuple]]:
    """Return labels 0..classes-1 and each class's probabilities, rows summing to 1."""
    if rows == 0:
        return (), [() for _ in range(classes)]
    head = np.arange(min(classes, rows))
    y = np.concatenate([head, rng.integers(classes, size=rows - len(head))])
    if ties:
        weights = rng.integers(1, 5, size=(rows, classes)).astype(float)
    else:
        weights = rng.random(size=(rows, classes))
    proba = weights / weights.sum(axis=1, keepdims=True)
    return tuple(int(v) for v in y), [
        tuple(float(v) for v in proba[:, j]) for j in range(classes)
    ]


def _datasets() -> list[tuple[_cases.Dataset, tuple, list[tuple]]]:
    """Return each dataset: its labels and one probability column per class."""
    rng = np.random.default_rng(_cases.SEED)
    out = []
    for name, n in _cases.SIZES.items():
        out.append((name, *_draw(rng, 2, n), f"two classes, {n:,} rows"))
    for name, n in (("medium", 1_000), ("large", 100_000)):
        out.append((f"four classes, {name}", *_draw(rng, 4, n),
                    f"four classes, {n:,} rows"))  # fmt: skip
    out.append(("ties", *_draw(rng, 2, 1_000, ties=True),
                "two classes, few distinct probabilities"))  # fmt: skip
    out.append(("four classes, ties", *_draw(rng, 4, 1_000, ties=True),
                "four classes, few distinct probabilities"))  # fmt: skip
    certain = (0.0, 1.0, 1.0, 0.0, 0.5, 1.0)
    out.append(("certain", (0, 1, 0, 1, 0, 1), [tuple(1 - p for p in certain),
                certain], "probabilities of 0 and 1, right and wrong"))  # fmt: skip
    y, p = _draw(rng, 2, 1_000)
    out.append(("null", y, [p[0], tuple(_cases._gaps(rng, list(p[1]), None))],
                "a tenth of one probability column NULL"))  # fmt: skip
    y, p = _draw(rng, 2, 1_000)
    out.append(("nan", y, [p[0], tuple(_cases._gaps(rng, list(p[1]), math.nan))],
                "a tenth of one probability column NaN"))  # fmt: skip
    out.append(("empty", *_draw(rng, 2, 0), "no rows"))
    y, p = _draw(rng, 2, 100)
    out.append(("one class", (1,) * 100, p, "every target the same class"))
    return [(_cases.Dataset(name, "y", y, note), y, p) for name, y, p, note in out]


def _clip(p: float) -> float:
    """Clip a probability to [eps, 1 - eps], as scikit-learn does (exact in doubles)."""
    return min(max(p, EPS), 1.0 - EPS)


def _exact_log_loss(y: tuple, proba: list[tuple]) -> mpmath.mpf:
    with mpmath.workdps(_cases.DIGITS):
        logs = [mpmath.log(mpmath.mpf(_clip(proba[c][i]))) for i, c in enumerate(y)]
        return -mpmath.fsum(logs) / len(y)


def _exact_auc(positive: list[bool], scores: tuple) -> Fraction | None:
    """Return the share of (positive, negative) pairs ranked right, ties half."""
    n_pos = sum(positive)
    n_neg = len(positive) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    pairs = sorted(zip(scores, positive, strict=True))
    wins = Fraction(0)
    below = 0  # negatives with a lower score
    for _, group in groupby(pairs, key=lambda pair: pair[0]):
        flags = [flag for _, flag in group]
        pos = sum(flags)
        neg = len(flags) - pos
        wins += pos * below + Fraction(pos * neg, 2)
        below += neg
    return wins / (n_pos * n_neg)


def _exact_roc_auc(y: tuple, proba: list[tuple]) -> Fraction | None:
    if len(proba) == 2:
        return _exact_auc([c == 1 for c in y], proba[1])
    areas = [_exact_auc([c == j for c in y], p) for j, p in enumerate(proba)]
    if any(a is None for a in areas):
        return None
    return sum(areas, Fraction(0)) / len(areas)


def _exact_ap(positive: list[bool], scores: tuple) -> Fraction | None:
    """Return the step sum of precision over recall, one step per distinct score."""
    n_pos = sum(positive)
    if n_pos == 0:
        return None
    pairs = sorted(zip(scores, positive, strict=True), reverse=True)
    total = Fraction(0)
    tp = seen = 0
    for _, group in groupby(pairs, key=lambda pair: pair[0]):
        flags = [flag for _, flag in group]
        tp += sum(flags)
        seen += len(flags)
        total += sum(flags) * Fraction(tp, seen)
    return total / n_pos


def _exact_average_precision(y: tuple, proba: list[tuple]) -> Fraction | None:
    if len(proba) == 2:
        return _exact_ap([c == 1 for c in y], proba[1])
    areas = [_exact_ap([c == j for c in y], p) for j, p in enumerate(proba)]
    if any(a is None for a in areas):
        return None
    return sum(areas, Fraction(0)) / len(areas)


def _exact_brier(y: tuple, proba: list[tuple]) -> Fraction:
    total = Fraction(0)
    for i, label in enumerate(y):
        for j, column in enumerate(proba):
            total += (Fraction(column[i]) - (1 if label == j else 0)) ** 2
    score = total / len(y)
    return score / 2 if len(proba) == 2 else score


def _exact(metric: str, y: tuple, proba: list[tuple]) -> Fraction | mpmath.mpf | None:
    if metric == "brier":
        return _exact_brier(y, proba)
    if metric == "log_loss":
        return _exact_log_loss(y, proba)
    if metric == "average_precision":
        return _exact_average_precision(y, proba)
    return _exact_roc_auc(y, proba)


def _sql(metric: str, classes: int) -> str:
    """Return the metric as hand-written SQL over table ``data``."""
    cols = [f'"{PROBA}{j}"' for j in range(classes)]
    if metric == "log_loss":
        own = " ".join(f"WHEN {j} THEN {c}" for j, c in enumerate(cols))
        return (
            f"SELECT -favg(ln(greatest({EPS!r}, least(CASE y {own} END, "
            f"1 - {EPS!r})))) FROM data"
        )
    if metric == "brier":
        terms = " + ".join(
            f"pow({c} - CAST(y = {j} AS DOUBLE), 2)" for j, c in enumerate(cols)
        )
        half = " * 0.5" if classes == 2 else ""
        return f"SELECT favg({terms}){half} FROM data"
    scored = [(1, cols[1])] if classes == 2 else list(enumerate(cols))
    if metric == "average_precision":
        areas = [
            f"(SELECT sum(pos * tp / n) / sum(pos) FROM (SELECT pos, "
            f"sum(pos) OVER w AS tp, count(*) OVER w AS n FROM (SELECT "
            f"CAST(y = {j} AS INTEGER) AS pos, {c} AS s FROM data) "
            f"WINDOW w AS (ORDER BY s DESC)))"
            for j, c in scored
        ]
        return f"SELECT ({' + '.join(areas)}) / {len(areas)}"
    ranks = ", ".join(
        f"2 * rank() OVER (ORDER BY {c}) + count(*) OVER (PARTITION BY {c}) - 1 AS r{j}"
        for j, c in scored
    )
    areas = [
        f"((sum(r{j}) FILTER (WHERE y = {j}) - count(*) FILTER (WHERE y = {j}) "
        f"* (count(*) FILTER (WHERE y = {j}) + 1)) / (2 * count(*) FILTER "
        f"(WHERE y = {j}) * (count(*) - count(*) FILTER (WHERE y = {j}))))"
        for j, _ in scored
    ]
    return (
        f"WITH ranked AS (SELECT y, {ranks} FROM data) "
        f"SELECT ({' + '.join(areas)}) / {len(areas)} FROM ranked"
    )


def _duckdb(
    metric: str, y: tuple, proba: list[tuple], threads: int | None
) -> float | None:
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    columns = {"y": y, **{f"{PROBA}{j}": p for j, p in enumerate(proba)}}
    kinds = {"y": "BIGINT", **{f"{PROBA}{j}": "DOUBLE" for j in range(len(proba))}}
    _cases.table(con, "data", columns, kinds)
    return con.sql(_sql(metric, len(proba))).fetchall()[0][0]


def _numpy(metric: str, y: np.ndarray, proba: np.ndarray) -> float:
    if metric == "log_loss":
        own = proba[np.arange(len(y)), y]
        return float(-np.mean(np.log(np.clip(own, EPS, 1 - EPS))))
    if metric == "brier":
        onehot = np.eye(proba.shape[1])[y]
        score = float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))
        return score / 2 if proba.shape[1] == 2 else score
    scored = [1] if proba.shape[1] == 2 else range(proba.shape[1])
    areas = []
    for j in scored:
        positive = y == j
        if metric == "average_precision":
            order = np.argsort(-proba[:, j], kind="stable")
            sorted_s, flags = proba[order, j], positive[order]
            last = np.append(np.nonzero(np.diff(sorted_s))[0], len(y) - 1)
            tp = np.cumsum(flags)[last]
            steps = np.diff(tp, prepend=0)
            areas.append(float(np.sum(steps * tp / (last + 1)) / positive.sum()))
            continue
        n_pos, n_neg = positive.sum(), (~positive).sum()
        ranks = rankdata(proba[:, j])
        areas.append(
            (ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        )
    return float(np.mean(areas))


def _sklearn(metric: str, y: np.ndarray, proba: np.ndarray) -> float:
    labels = list(range(proba.shape[1]))
    if metric == "log_loss":
        return log_loss(y, proba, labels=labels)
    if metric == "brier":
        return brier_score_loss(y, proba, labels=labels)
    score = proba[:, 1] if proba.shape[1] == 2 else proba
    if metric == "average_precision":
        return average_precision_score(y, score)
    return roc_auc_score(y, score, multi_class="ovr", average="macro", labels=labels)


def cases() -> list[dict]:
    """Return the cases of the four metrics: each dataset and reference."""
    out = []
    for data, y, proba in _datasets():
        values = [v for p in proba for v in p]
        answerable = bool(y) and not any(_cases.is_missing(v) for v in values)
        for metric, bound in BOUNDS.items():
            exact = _exact(metric, y, proba) if answerable else None
            classes = list(range(len(proba)))

            def ours(metric=metric, y=y, proba=proba, classes=classes) -> float:
                columns = {"y": y, **{f"{PROBA}{j}": p for j, p in enumerate(proba)}}
                kinds = {"y": "BIGINT", **dict.fromkeys(list(columns)[1:], "DOUBLE")}
                rel = _cases.sqlearn_table(columns, kinds)
                return getattr(sq.metrics, metric).compute(rel, "y", classes=classes)

            def arrays(y=y, proba=proba) -> tuple[np.ndarray, np.ndarray]:
                matrix = np.column_stack([_cases.as_nan(p) for p in proba])
                return np.array(y, dtype=int), matrix.reshape(len(y), len(proba))

            answers = {
                "sqlearn": ours,
                "duckdb": lambda m=metric, y=y, p=proba: _duckdb(m, y, p, None),
                "duckdb, 1 thread": lambda m=metric, y=y, p=proba: _duckdb(m, y, p, 1),
                "numpy": lambda m=metric, a=arrays: _numpy(m, *a()),
                "scikit-learn": lambda m=metric, a=arrays: _sklearn(m, *a()),
            }
            out += _cases.measure_all(
                step=metric,
                formula=metric,
                data=data,
                type="DOUBLE",
                exact=exact,
                bound=bound,
                answers=answers,
            )
    return out
