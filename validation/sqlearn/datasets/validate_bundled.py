"""Validate the bundled datasets: each equal to scikit-learn's frame, value for value.

The canonical value is scikit-learn's ``as_frame=True`` frame (the files are
copies of its own data, ADR 0045). Every feature is compared in ULPs and every
target for equality, over every row in order; the bound is 0, as the files
hold the same decimal text and DuckDB reads it as the same double. The case
records the number of values that differ (as ``abs_error``) and the worst
distance in ULPs over all features.
"""

from sklearn import datasets as sk

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016); 0, as the values are the same text.
# Loosening it needs a written reason here, never a quiet edit.
BOUND = 0

DATASETS = (
    ("iris", sq.datasets.iris, sk.load_iris),
    ("wine", sq.datasets.wine, sk.load_wine),
    ("breast_cancer", sq.datasets.breast_cancer, sk.load_breast_cancer),
)


def _compare(make, load) -> tuple[int, int, float, int]:
    """Return rows, cells, mismatched cells and the worst ULP distance."""
    expected = load(as_frame=True).frame
    got = make().fetchall()
    names = list(expected.columns)
    rows = expected.shape[0]
    cells = rows * len(names)
    if len(got) != rows or make().columns != names:
        return rows, cells, float("inf"), cells
    worst: int | float = 0
    mismatches = 0
    for j, name in enumerate(names):
        column = expected[name].tolist()
        for i in range(rows):
            if name == "target":
                distance = 0 if got[i][j] == int(column[i]) else float("inf")
            else:
                distance = _cases.ulps(got[i][j], float(column[i]))
            worst = max(worst, distance)
            mismatches += distance > BOUND
    return rows, cells, worst, mismatches


def cases() -> list[dict]:
    """Return one case per bundled dataset: sqlearn against scikit-learn's frame."""
    out = []
    for name, make, load in DATASETS:
        rows, cells, worst, mismatches = _compare(make, load)
        out.append(
            _cases.exact_case(
                step=f"datasets.{name}",
                formula="bundled dataset",
                dataset=name,
                rows=rows,
                type="DOUBLE, BIGINT",
                mismatches=mismatches,
                cells=cells,
                compared_with="scikit-learn",
                note=f"{cells:,} values; worst distance {worst} ULPs",
            )
        )
    return out
