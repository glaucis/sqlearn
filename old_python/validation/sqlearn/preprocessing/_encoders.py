"""What the OneHot and Ordinal runners share: the datasets and the two sides.

An encoder has no rounding, so it is compared value by value with
scikit-learn and must agree exactly. scikit-learn is given the missing
values as NaN, the way it takes them from pandas: given None, its
``OrdinalEncoder`` would make None a category instead of keeping it missing.
"""

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

import sqlearn as sq
from validation import _cases

UNSEEN_WORD = "paris"


def datasets() -> list[tuple[_cases.Dataset, tuple]]:
    """Return each dataset with the values applied to: itself, or unseen ones.

    The last, "unseen", learns from the medium set and is applied to values
    among which one was never learned, to check how each handles it.
    """
    sets = _cases.labels()
    out = [(d, d.values) for d in sets]
    rng = np.random.default_rng(_cases.SEED)
    medium = next(d for d in sets if d.name == "medium")
    applied = tuple(str(w) for w in rng.choice((*_cases.WORDS, UNSEEN_WORD), 1_000))
    unseen = _cases.Dataset(
        "unseen",
        medium.column,
        medium.values,
        f"learned on medium, applied to 1,000 values holding {UNSEEN_WORD!r}",
    )
    return [*out, (unseen, applied)]


def to_sklearn(values: tuple) -> np.ndarray:
    """Return the values as one object column, missing values as NaN."""
    return np.array([[math.nan if v is None else v] for v in values], dtype=object)


def sqlearn_side(
    make: Callable[[str], sq.Step], data: _cases.Dataset, applied: tuple
) -> tuple[list, pd.DataFrame]:
    """Learn the step on the data and apply it: its categories and its output."""
    learn = _cases.sqlearn_table({data.column: data.values}, "VARCHAR")
    pipe = sq.Pipeline([("encode", make(data.column))]).learn(learn)
    frame = pipe.apply(
        _cases.sqlearn_table({data.column: applied}, "VARCHAR"), out="pandas"
    )
    return list(pipe["encode"].categories_[data.column]), frame


def category_mismatches(ours: list, theirs: list) -> int:
    """Count the positions at which two category lists differ."""
    differ = sum(a != b for a, b in zip(ours, theirs, strict=False))
    return differ + abs(len(ours) - len(theirs))


def cases(
    step: str,
    formulas: tuple[str, str],
    make: Callable[[str], sq.Step],
    compare: Callable[[_cases.Dataset, tuple], list[dict]],
) -> list[dict]:
    """Return the cases of one encoder: two formulas per dataset."""
    out: list[dict] = []
    for data, applied in datasets():
        head = {
            "step": step,
            "dataset": data.name,
            "rows": len(applied),
            "type": "VARCHAR",
        }
        if data.name == "nan":
            for formula in formulas:
                out.append(
                    _cases.skipped(
                        reference="sqlearn",
                        formula=formula,
                        note="text holds no NaN; NaN is a DOUBLE value",
                        bound=0,
                        **head,
                    )
                )
            continue
        if not data.values:
            for formula in formulas:
                try:
                    sqlearn_side(make, data, applied)
                except sq.errors.SqlearnError as exc:
                    result, note = (
                        "pass",
                        f"refused, as specified: {_cases.first_line(exc)}",
                    )
                else:
                    result, note = "fail", "no rows to learn from, yet sqlearn learned"
                note += "; scikit-learn refuses no rows too (ValueError)"
                out.append(
                    _cases.skipped(
                        reference="sqlearn",
                        formula=formula,
                        note=note,
                        bound=0,
                        result=result,
                        **head,
                    )
                )
            continue
        out += compare(data, applied)
    return out
