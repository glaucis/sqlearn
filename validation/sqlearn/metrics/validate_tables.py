"""Validate the table metrics against a count in pure Python and scikit-learn.

The report is checked against exact `Fraction`s (scikit-learn averages in
floats, so it can differ by an ULP and is not the reference). The confusion
matrix is counted over the rows in pure Python; normalised
cells are the exact `Fraction` of two whole counts, rounded once to a double
(the one division sqlearn does). sqlearn's matrix must equal both the count
and scikit-learn's ``confusion_matrix``, cell for cell.
"""

import math
import warnings
from fractions import Fraction

import numpy as np
from sklearn.metrics import confusion_matrix as sk_confusion_matrix

import sqlearn as sq
from validation import _cases

# Counts are whole numbers and a cell is one division of two of them, which
# both sides round once: 0 mismatches, measured on every case below.
BOUND = 0

NORMALIZE = (None, "true", "pred", "all")


def exact(labels: list, y: tuple, p: tuple, normalize: str | None) -> list[list[float]]:
    """Count the matrix over the rows; a normalised cell is one exact ratio."""
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    counts = [[0] * n for _ in range(n)]
    for a, b in zip(y, p, strict=True):
        counts[index[a]][index[b]] += 1
    rows = [sum(r) for r in counts]
    columns = [sum(counts[i][j] for i in range(n)) for j in range(n)]
    grand = sum(rows)
    totals = {
        "true": lambda i, j: rows[i],
        "pred": lambda i, j: columns[j],
        "all": lambda i, j: grand,
    }
    if normalize is None:
        return [[float(c) for c in r] for r in counts]
    return [
        [
            float(Fraction(counts[i][j], totals[normalize](i, j)))
            if totals[normalize](i, j)
            else 0.0
            for j in range(n)
        ]
        for i in range(n)
    ]


def _datasets() -> list[tuple[str, tuple, tuple, str, list]]:
    """Return each dataset: its name, target, prediction, type and labels."""
    rng = np.random.default_rng(_cases.SEED)
    words = list(_cases.WORDS[:3])
    out = []
    for size, rows in _cases.SIZES.items():
        for labels, kind, what in (
            ([0, 1], "INTEGER", "2 labels"),
            ([0, 1, 2], "INTEGER", "3 labels"),
            (words, "VARCHAR", "3 text labels"),
        ):
            y = rng.choice(len(labels), rows)
            p = np.where(rng.random(rows) < 0.7, y, rng.choice(len(labels), rows))
            out.append(
                (
                    f"{size}, {what}",
                    tuple(labels[i] for i in y),
                    tuple(labels[i] for i in p),
                    kind,
                    labels,
                )
            )
    # A label predicted but never true, so a "true" row has no rows.
    out.append(("never true", (0, 1, 0, 1), (0, 2, 2, 1), "INTEGER", [0, 1, 2]))
    out.append(
        (
            "mixed case",
            ("a", "B", "a", "B"),
            ("B", "B", "a", "a"),
            "VARCHAR",
            ["a", "B"],
        )
    )
    return out


ZERO_DIVISIONS = ("warn", 0.0, 1.0, float("nan"))


def exact_report(
    labels: list, y: tuple, p: tuple, zero_division: str | float
) -> list[list[float | None]]:
    """Return the report's rows from exact `Fraction`s, rounded once each.

    Per class: tp, fp and fn counted over the rows; an average is the exact
    mean (weighted by support) of the classes' fractions, NaN ones left out.
    """
    fill = Fraction(0) if zero_division == "warn" else None
    if fill is None and not math.isnan(zero_division):
        fill = Fraction(zero_division)
    classes = []
    for label in labels:
        tp = sum(1 for a, b in zip(y, p, strict=True) if a == label == b)
        fp = sum(1 for a, b in zip(y, p, strict=True) if b == label != a)
        fn = sum(1 for a, b in zip(y, p, strict=True) if a == label != b)

        def ratio(top: int, bottom: int) -> Fraction | None:
            return Fraction(top, bottom) if bottom else fill

        classes.append(
            (
                ratio(tp, tp + fp),
                ratio(tp, tp + fn),
                ratio(2 * tp, 2 * tp + fp + fn),
                tp + fn,
            )
        )

    def as_float(value: Fraction | None) -> float:
        return math.nan if value is None else float(value)

    def mean(k: int, weighted: bool) -> float:
        kept = [(c[k], c[3] if weighted else 1) for c in classes if c[k] is not None]
        if not kept:
            return math.nan
        total = sum(w for _, w in kept)
        if total == 0:
            return float(sum(v for v, _ in kept) / len(kept))
        return float(sum(v * w for v, w in kept) / total)

    rows: list[list[float | None]] = [
        [as_float(c[0]), as_float(c[1]), as_float(c[2]), float(c[3])] for c in classes
    ]
    n = len(y)
    hits = sum(1 for a, b in zip(y, p, strict=True) if a == b)
    rows.append([None, None, float(Fraction(hits, n)), float(n)])
    for weighted in (False, True):
        rows.append([mean(0, weighted), mean(1, weighted), mean(2, weighted), float(n)])
    return rows


def agree(a: float | None, b: float | None) -> bool:
    """Say whether two cells are equal: both NULL, both NaN, or the same double."""
    if a is None or b is None:
        return a is None and b is None
    return a == b or (math.isnan(a) and math.isnan(b))


def report_cases() -> list[dict]:
    """Return the classification report's cases: each zero_division and dataset."""
    out = []
    for name, y, p, kind, _ in _datasets():
        labels = sorted(set(y) | set(p))
        for zero_division in ZERO_DIVISIONS:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ours = sq.metrics.classification_report(
                    _cases.sqlearn_table({"y": y, "prediction": p}, kind),
                    "y",
                    zero_division=zero_division,
                ).fetchall()
            want = exact_report(labels, y, p, zero_division)
            cells = [
                (a, b)
                for got, row in zip(ours, want, strict=True)
                for a, b in zip(got[1:], row, strict=True)
            ]
            mismatches = sum(1 for a, b in cells if not agree(a, b))
            out.append(
                _cases.exact_case(
                    step="classification_report",
                    formula=f"classification_report, zero_division={zero_division}",
                    dataset=name,
                    rows=len(y),
                    type=kind,
                    mismatches=mismatches,
                    cells=len(cells),
                    compared_with="pure Python (Fraction)",
                )
            )
    return out


def confusion_cases() -> list[dict]:
    """Return the confusion matrix's cases: each normalisation and dataset."""
    out = []
    for name, y, p, kind, labels in _datasets():
        labels = sorted(set(y) | set(p))
        for normalize in NORMALIZE:
            ours = sq.metrics.confusion_matrix(
                _cases.sqlearn_table({"y": y, "prediction": p}, kind),
                "y",
                normalize=normalize,
                out="numpy",
            )
            got = np.column_stack(list(ours.values())[1:])
            want = np.array(exact(labels, y, p, normalize))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sk = sk_confusion_matrix(list(y), list(p), normalize=normalize)
            for reference, other in (("pure Python", want), ("scikit-learn", sk)):
                out.append(
                    _cases.exact_case(
                        step="confusion_matrix",
                        formula=f"confusion_matrix, normalize={normalize}",
                        dataset=name,
                        rows=len(y),
                        type=kind,
                        mismatches=int((got != other).sum()),
                        cells=got.size,
                        compared_with=reference,
                    )
                )
    return out


def cases() -> list[dict]:
    """Return every table metric's cases."""
    return [*confusion_cases(), *report_cases()]
