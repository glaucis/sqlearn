"""Validate the table metrics against a count in pure Python and scikit-learn.

The confusion matrix is counted over the rows in pure Python; normalised
cells are the exact `Fraction` of two whole counts, rounded once to a double
(the one division sqlearn does). sqlearn's matrix must equal both the count
and scikit-learn's ``confusion_matrix``, cell for cell.
"""

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


def cases() -> list[dict]:
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
