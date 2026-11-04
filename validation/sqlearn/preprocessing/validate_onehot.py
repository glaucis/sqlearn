"""Validate OneHot against scikit-learn's OneHotEncoder, value by value.

scikit-learn is set as OneHot's documentation says it matches:
``OneHotEncoder(handle_unknown="ignore", sparse_output=False)``. The learned
categories, NULL included as its own when seen, and every 0/1 indicator must
be equal: the bound is 0 (ADR 0016), the count of differing values is
recorded as ``ulps``.
"""

import math

from sklearn.preprocessing import OneHotEncoder

import sqlearn as sq
from validation import _cases
from validation.sqlearn.preprocessing import _encoders

COMPARED_WITH = 'scikit-learn OneHotEncoder(handle_unknown="ignore")'


def _compare(data: _cases.Dataset, applied: tuple) -> list[dict]:
    categories, frame = _encoders.sqlearn_side(sq.OneHot, data, applied)
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    encoder.fit(_encoders.to_sklearn(data.values))
    theirs = list(encoder.categories_[0])
    has_null = any(isinstance(c, float) and math.isnan(c) for c in theirs)
    named = [c for c in theirs if isinstance(c, str)]
    ours_null = f"{data.column}_NULL" in frame.columns
    category_misses = _encoders.category_mismatches(categories, named) + int(
        ours_null != has_null
    )
    matrix = encoder.transform(_encoders.to_sklearn(applied))
    names = [f"{data.column}_{'NULL' if isinstance(c, float) else c}" for c in theirs]
    misses = 0
    for j, name in enumerate(names):
        if name in frame.columns:
            misses += int((frame[name].to_numpy() != matrix[:, j]).sum())
        else:
            misses += len(applied)
    misses += len(applied) * len(set(frame.columns) - set(names))
    head = {
        "step": "onehot",
        "dataset": data.name,
        "rows": len(applied),
        "type": "VARCHAR",
        "compared_with": COMPARED_WITH,
    }
    return [
        _cases.exact_case(
            formula="categories",
            mismatches=category_misses,
            cells=len(theirs),
            note="the sorted distinct values, and NULL as a category when seen",
            **head,
        ),
        _cases.exact_case(
            formula="indicators",
            mismatches=misses,
            cells=len(applied) * len(theirs),
            note=f"{data.note}; every 0/1 value of every new column",
            **head,
        ),
    ]


def cases() -> list[dict]:
    """Return OneHot's cases: categories and indicators per dataset."""
    return _encoders.cases(
        "onehot", ("categories", "indicators"), lambda c: sq.OneHot(cols=[c]), _compare
    )
