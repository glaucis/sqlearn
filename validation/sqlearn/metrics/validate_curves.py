"""Validate the ROC and precision-recall curves against pure Python and sklearn.

Thresholds and counts are whole numbers; a rate is the exact `Fraction` of two
counts, rounded once to a double, which is the one division sqlearn does and
the one scikit-learn does. sqlearn's curve must equal both the exact answer
and scikit-learn's ``roc_curve`` and ``precision_recall_curve``, value for
value (BOUND 0, measured on every case below), with the points
``drop_intermediate`` keeps the same ones.
"""

import warnings
from fractions import Fraction

import numpy as np
from sklearn.metrics import precision_recall_curve as sk_pr_curve
from sklearn.metrics import roc_curve as sk_roc_curve

import sqlearn as sq
from validation import _cases

# Whole counts and one division rounded once on both sides: 0 mismatches.
BOUND = 0


def exact(
    y: tuple, s: tuple, positive: object, drop: bool
) -> tuple[list[float], list[float], list[float]]:
    """Return fpr, tpr and threshold, counted in pure Python."""
    thresholds = sorted(set(s), reverse=True)
    tps = [
        sum(1 for a, b in zip(y, s, strict=True) if b >= t and a == positive)
        for t in thresholds
    ]
    fps = [
        sum(1 for b in s if b >= t) - p for t, p in zip(thresholds, tps, strict=True)
    ]
    if drop and len(thresholds) > 2:
        keep = (
            [0]
            + [
                i
                for i in range(1, len(thresholds) - 1)
                if fps[i - 1] - 2 * fps[i] + fps[i + 1]
                or tps[i - 1] - 2 * tps[i] + tps[i + 1]
            ]
            + [len(thresholds) - 1]
        )
        thresholds, tps, fps = ([v[i] for i in keep] for v in (thresholds, tps, fps))
    negatives = sum(1 for a in y if a != positive)
    positives = len(y) - negatives

    def rate(count: int, total: int) -> float:
        return float(Fraction(count, total)) if total else float("nan")

    return (
        [rate(c, negatives) for c in (0, *fps)],
        [rate(c, positives) for c in (0, *tps)],
        [float("inf"), *map(float, thresholds)],
    )


def _datasets() -> list[tuple[str, tuple, tuple, str, object]]:
    """Return each dataset: its name, target, score, target type and positive."""
    rng = np.random.default_rng(_cases.SEED)
    out: list[tuple[str, tuple, tuple, str, object]] = []
    for size, rows in _cases.SIZES.items():
        y = rng.integers(0, 2, rows)
        # Scores rounded to two places: many ties, and a signal in them.
        s = np.round(np.clip(0.3 * y + rng.random(rows) * 0.7, 0, 1), 2)
        out.append(
            (
                f"{size}, ties",
                tuple(int(v) for v in y),
                tuple(float(v) for v in s),
                "INTEGER",
                1,
            )
        )
        words = np.array(["no", "yes"])[y]
        out.append(
            (
                f"{size}, text labels",
                tuple(words.tolist()),
                tuple(float(v) for v in s),
                "VARCHAR",
                "yes",
            )
        )
    out.append(("every score tied", (0, 1, 1, 0), (0.5,) * 4, "INTEGER", 1))
    out.append(("integer scores", (0, 1, 1, 0, 1), (-3, 2, -1, -3, 7), "INTEGER", 1))
    out.append(
        (
            "equal steps",
            (1, 1, 1, 1, 0, 0),
            (0.9, 0.8, 0.8, 0.7, 0.2, 0.1),
            "INTEGER",
            1,
        )
    )
    return out


def roc_cases() -> list[dict]:
    """Return the ROC curve's cases: each dataset, kept or dropped points."""
    out = []
    for name, y, s, kind, positive in _datasets():
        for drop in (True, False):
            table = _cases.sqlearn_table(
                {"y": y, "s": s},
                {
                    "y": kind,
                    "s": "DOUBLE"
                    if any(isinstance(v, float) for v in s)
                    else "INTEGER",
                },
            )
            ours = sq.metrics.roc_curve(
                table, "y", "s", pos_label=positive, drop_intermediate=drop, out="numpy"
            )
            got = np.column_stack([ours["fpr"], ours["tpr"], ours["threshold"]])
            want = np.column_stack(exact(y, s, positive, drop))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sk = np.column_stack(
                    sk_roc_curve(
                        list(y), list(s), pos_label=positive, drop_intermediate=drop
                    )
                )[:, [0, 1, 2]]
            for reference, other in (
                ("pure Python (Fraction)", want),
                ("scikit-learn", sk),
            ):
                same = (got.shape == other.shape) and np.array_equal(
                    got, other, equal_nan=True
                )
                out.append(
                    _cases.exact_case(
                        step="roc_curve",
                        formula=f"roc_curve, drop_intermediate={drop}",
                        dataset=name,
                        rows=len(y),
                        type=kind,
                        mismatches=0
                        if same
                        else int(
                            (got != other).sum()
                            if got.shape == other.shape
                            else got.size
                        ),
                        cells=got.size,
                        compared_with=reference,
                    )
                )
    return out


def exact_pr(
    y: tuple, s: tuple, positive: object, drop: bool
) -> tuple[list[float], list[float], list[float]]:
    """Return precision, recall and threshold, counted in pure Python."""
    thresholds = sorted(set(s))
    tps = [
        sum(1 for a, b in zip(y, s, strict=True) if b >= t and a == positive)
        for t in thresholds
    ]
    totals = [sum(1 for b in s if b >= t) for t in thresholds]
    if drop and len(thresholds) > 2:
        # Ascending thresholds: tps falls; 1.9.1 keeps a point whose tps
        # differs from a neighbour's, and the ends.
        keep = (
            [0]
            + [
                i
                for i in range(1, len(thresholds) - 1)
                if tps[i] != tps[i - 1] or tps[i] != tps[i + 1]
            ]
            + [len(thresholds) - 1]
        )
        thresholds, tps, totals = (
            [v[i] for i in keep] for v in (thresholds, tps, totals)
        )
    positives = sum(1 for a in y if a == positive)
    return (
        [*(float(Fraction(t, n)) for t, n in zip(tps, totals, strict=True)), 1.0],
        [
            *(float(Fraction(t, positives)) if positives else 1.0 for t in tps),
            0.0,
        ],
        [*map(float, thresholds), float("nan")],
    )


def pr_cases() -> list[dict]:
    """Return the precision-recall curve's cases: kept or dropped points."""
    out = []
    for name, y, s, kind, positive in _datasets():
        for drop in (False, True):
            table = _cases.sqlearn_table(
                {"y": y, "s": s},
                {
                    "y": kind,
                    "s": "DOUBLE"
                    if any(isinstance(v, float) for v in s)
                    else "INTEGER",
                },
            )
            ours = sq.metrics.precision_recall_curve(
                table, "y", "s", pos_label=positive, drop_intermediate=drop, out="numpy"
            )
            got = np.column_stack(
                [
                    np.ma.filled(np.ma.asarray(ours[c], float), np.nan)
                    for c in ("precision", "recall", "threshold")
                ]
            )
            want = np.column_stack(exact_pr(y, s, positive, drop))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                p, r, t = sk_pr_curve(
                    list(y), list(s), pos_label=positive, drop_intermediate=drop
                )
            sk = np.column_stack([p, r, np.append(t, np.nan)])
            for reference, other in (
                ("pure Python (Fraction)", want),
                ("scikit-learn", sk),
            ):
                same = (got.shape == other.shape) and np.array_equal(
                    got, other, equal_nan=True
                )
                out.append(
                    _cases.exact_case(
                        step="precision_recall_curve",
                        formula=f"precision_recall_curve, drop_intermediate={drop}",
                        dataset=name,
                        rows=len(y),
                        type=kind,
                        mismatches=0
                        if same
                        else int(
                            (got != other).sum()
                            if got.shape == other.shape
                            else got.size
                        ),
                        cells=got.size,
                        compared_with=reference,
                    )
                )
    return out


def cases() -> list[dict]:
    """Return every curve's cases."""
    return roc_cases() + pr_cases()
