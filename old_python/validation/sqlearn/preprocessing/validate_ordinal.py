"""Validate Ordinal against scikit-learn's OrdinalEncoder, value by value.

scikit-learn is set as Ordinal's documentation says it matches:
``OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)``.
The learned categories (NULL is not one: it stays missing on both sides)
and every code must be equal: the bound is 0 (ADR 0016), the count of
differing values is recorded as ``ulps``.
"""

import math

from sklearn.preprocessing import OrdinalEncoder

import sqlearn as sq
from validation import _cases
from validation.sqlearn.preprocessing import _encoders

COMPARED_WITH = (
    'scikit-learn OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)'
)


def _same(ours: object, theirs: float) -> bool:
    ours_missing = ours is None or (isinstance(ours, float) and math.isnan(ours))
    if ours_missing or math.isnan(theirs):
        return ours_missing and math.isnan(theirs)
    return float(ours) == theirs  # type: ignore[arg-type]


def _compare(data: _cases.Dataset, applied: tuple) -> list[dict]:
    categories, frame = _encoders.sqlearn_side(sq.encode.ordinal, data, applied)
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    encoder.fit(_encoders.to_sklearn(data.values))
    named = [c for c in encoder.categories_[0] if isinstance(c, str)]
    codes = encoder.transform(_encoders.to_sklearn(applied))[:, 0]
    ours = frame[data.column].astype(object).where(frame[data.column].notna(), None)
    misses = sum(not _same(a, b) for a, b in zip(ours, codes, strict=True))
    head = {
        "step": "ordinal",
        "dataset": data.name,
        "rows": len(applied),
        "type": "VARCHAR",
        "compared_with": COMPARED_WITH,
    }
    return [
        _cases.exact_case(
            formula="categories",
            mismatches=_encoders.category_mismatches(categories, named),
            cells=len(named),
            note="the sorted distinct non-missing values",
            **head,
        ),
        _cases.exact_case(
            formula="codes",
            mismatches=misses,
            cells=len(applied),
            note=f"{data.note}; every code, missing kept missing, unseen -1",
            **head,
        ),
    ]


def cases() -> list[dict]:
    """Return Ordinal's cases: categories and codes per dataset."""
    return _encoders.cases(
        "ordinal",
        ("categories", "codes"),
        lambda c: sq.encode.ordinal(cols=[c]),
        _compare,
    )
