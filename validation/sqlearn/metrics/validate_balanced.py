"""Validate balanced accuracy and the MCC against exact arithmetic and scikit-learn.

The canonical value is computed in pure Python as a `Fraction` (ADR 0016):
each class's recall a ratio of whole numbers over the classes the target
holds, their exact mean, and, adjusted, ``(mean - 1/k) / (1 - 1/k)`` for the
``k`` classes. Beside sqlearn: scikit-learn's ``balanced_accuracy_score``,
which averages and rescales in doubles. A target of one class adjusted has no
finite answer (minus infinity in both) and is left out. The MCC's canonical
value is its whole-number numerator over the square root of its whole-number
denominator, in `mpmath` at `_cases.DIGITS`; 0 when the denominator is 0. Beside it:
scikit-learn's ``matthews_corrcoef``. Labels with NULL, and no rows, have no
right answer: sqlearn must refuse them.

The datasets are those of the classification runner.
"""

from fractions import Fraction

import mpmath
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef

import sqlearn as sq
from validation import _cases
from validation.sqlearn.metrics.validate_classification import _datasets

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value: 0, as sqlearn rounds the exact score once. scikit-learn
# averages in doubles and rescales the rounded mean, so it can be off by more.
# Loosening it needs a written reason here, never a quiet edit.
BOUND = 0
# The MCC: 1, as sqlearn rounds the exact numerator^2 / denominator once and
# takes one correctly rounded square root, so two roundings.
MCC_BOUND = 1


def exact_balanced(y: tuple, p: tuple, adjusted: bool) -> Fraction:
    """Return the balanced accuracy of `p` against `y`, exactly."""
    classes = sorted(set(y), key=repr)
    recalls = [
        Fraction(
            sum(1 for a, b in zip(y, p, strict=True) if a == c == b),
            sum(1 for a in y if a == c),
        )
        for c in classes
    ]
    score = sum(recalls, Fraction(0)) / len(recalls)
    if not adjusted:
        return score
    chance = Fraction(1, len(classes))
    return (score - chance) / (1 - chance)


def exact_mcc(y: tuple, p: tuple) -> mpmath.mpf:
    """Return the Matthews correlation of `p` against `y`, at `_cases.DIGITS`."""
    classes = set(y) | set(p)
    s = len(y)
    c = sum(1 for a, b in zip(y, p, strict=True) if a == b)
    t = {k: sum(1 for a in y if a == k) for k in classes}
    q = {k: sum(1 for b in p if b == k) for k in classes}
    numerator = c * s - sum(t[k] * q[k] for k in classes)
    under = (s * s - sum(v * v for v in q.values())) * (
        s * s - sum(v * v for v in t.values())
    )
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.mpf(0) if under == 0 else numerator / mpmath.sqrt(under)


def _mcc_cases() -> list[dict]:
    out = []
    for data, y_col, y, p_col, p, kind, _ in _datasets():
        answerable = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))

        def ours(y=y, p=p, kind=kind, y_col=y_col, p_col=p_col) -> float:
            rel = _cases.sqlearn_table({y_col: y, p_col: p}, kind)
            return sq.metrics.mcc.compute(rel, y_col, p_col)

        def theirs(y=y, p=p) -> float:
            return matthews_corrcoef(list(y), list(p))

        out += _cases.measure_all(
            step="mcc",
            formula="mcc",
            data=data,
            type=kind,
            exact=exact_mcc(y, p) if answerable else None,
            bound=MCC_BOUND,
            answers={"sqlearn": ours, "scikit-learn": theirs},
        )
    return out


def cases() -> list[dict]:
    """Return the cases of balanced accuracy, adjusted or not, and of the MCC."""
    out = _mcc_cases()
    for data, y_col, y, p_col, p, kind, _ in _datasets():
        answerable = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))
        for adjusted in (False, True):
            if adjusted and answerable and len(set(y)) == 1:
                continue

            def ours(
                adjusted=adjusted, y=y, p=p, kind=kind, y_col=y_col, p_col=p_col
            ) -> float:
                rel = _cases.sqlearn_table({y_col: y, p_col: p}, kind)
                metric = sq.metrics.balanced_accuracy(adjusted=adjusted)
                return metric.compute(rel, y_col, p_col)

            def theirs(adjusted=adjusted, y=y, p=p) -> float:
                return balanced_accuracy_score(list(y), list(p), adjusted=adjusted)

            out += _cases.measure_all(
                step="balanced_accuracy",
                formula=f"balanced_accuracy, adjusted={adjusted}",
                data=data,
                type=kind,
                exact=exact_balanced(y, p, adjusted) if answerable else None,
                bound=BOUND,
                answers={"sqlearn": ours, "scikit-learn": theirs},
            )
    return out
