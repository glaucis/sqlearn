"""Validate the regression metrics against exact arithmetic.

The canonical values are computed in pure Python from the doubles' exact
values (ADR 0016), each by its own method:

- As a `Fraction` over the doubles: mae, mse, max_error,
  median_absolute_error (the exact middle of the exact absolute errors),
  mape (each absolute error over the larger of the target's size and
  float64's eps, as scikit-learn divides), r2 and explained_variance (one
  minus the exact error's or residual's sum of squares over the target's),
  pinball_loss, tweedie_deviance at power 0 and d2_tweedie at power 0.
- The deviances (tweedie_deviance at powers -1, 0, 1, 1.5, 2 and 3,
  poisson_deviance, gamma_deviance) and d2_tweedie at those powers:
  scikit-learn's per-row deviance, exact, about the prediction and (for
  D2) about the target's exact mean. At powers -1, 0 and 3 every power
  in it is whole, so it is a `Fraction`; at 1, 1.5 and 2 it has a log or
  a square root, computed with mpmath at `_cases.DIGITS` digits.
- With mpmath at `_cases.DIGITS` digits: rmse and rmsle (a square root),
  and msle (mpmath's ``log1p``, the semantics sqlearn computes with Kahan's
  log1p in SQL).
- d2_pinball (alpha 0.1, 0.5 and 0.9, and alphas whose ``n * alpha`` is
  nearly whole: 0.3 and 0.7 on ten rows, 1/3 on three) and
  d2_absolute_error: the baseline is the target's alpha-quantile as
  scikit-learn's ``_weighted_percentile(..., average=True)`` takes it
  (numpy's ``averaged_inverted_cdf``). The rows it averages are picked as
  scikit-learn picks them, in doubles (``k = alpha * 100 / 100 * n``, one
  row unless the row's place passes ``k`` by no more than eps), and the
  losses are then summed as `Fraction` s. Any value between the two rows
  averaged gives the same baseline loss, so the exact mean of the two is
  the exact baseline.

A constant target has no spread to explain. r2 then scores 1 for an exact
prediction and 0 otherwise, as scikit-learn's ``r2_score`` has it;
explained_variance 1 when the error's variance is 0 (every prediction off
by the same amount) and 0 otherwise; d2_pinball and d2_absolute_error 1
when the model loses nothing and 0 otherwise, whenever the baseline loses
nothing (scikit-learn's ``force_finite``). d2_tweedie follows ADR 0054's
rule, not scikit-learn (which raises ``ZeroDivisionError``): 1 when every
prediction equals the target, else 0.

Beside sqlearn: DuckDB alone (hand-written SQL with ``favg`` and ``fsum``,
and at one thread), numpy, and scikit-learn 1.9.1. Targets or predictions
with NULL or NaN, and no rows, have no right answer: sqlearn must refuse
them. So must it refuse a row outside a metric's range (scikit-learn
refuses them too): a target or prediction at or below -1 for msle and
rmsle, and for the deviances the rows scikit-learn's
``mean_tweedie_deviance`` refuses at each power. The ``offset`` dataset
puts the target's mean far above its spread, where a sum of squares minus a
squared sum would lose every digit; ``tiny`` holds values near 1e-9, where
``ln(1 + x)`` loses the digits ``log1p`` keeps (DuckDB alone, which has no
log1p, is an anomaly there, expected); ``negative mean`` gives d2_tweedie
below power 0 a baseline at or below 0, which scikit-learn scores.
On ``offset`` a log or a power of values near 1e6 (msle, the deviances
other than power 0) is a difference of terms a million times its size in
every library alike: their bounds there are wide, each at its measurement
(`WIDE`).

Anomalies expected of the references, by design rather than defect:

- DuckDB alone is the plain ratio, with no rule for a constant target:
  NaN or an infinity on the constant datasets for r2, explained_variance and
  the D2 scores.
- d2_tweedie below power 0 on a constant target: an exact prediction's
  deviance there is a few roundings off 0 (see the comment above `BOUNDS`),
  and so is the baseline's, so scikit-learn and numpy score the ratio of two
  roundings (about 1e15) where ADR 0054's rule gives 0 or 1.
- d2_tweedie at power 1.5 on ``constant zero``: scikit-learn's baseline,
  the mean 0, is outside the range and its deviance is NaN.
- tweedie_deviance at power -1 on ``offset``: numpy and scikit-learn take
  ``pow`` of values near 1e6 and land about 40 times further from the exact
  value than sqlearn, whose bound there is its own measurement.

And one that is scikit-learn's own rounding, not sqlearn's (an open
question when the validation was written, settled by probing):

- ``constant, inexact offset`` (1,000 rows of target 0.3, prediction 0.1):
  every error is the same double, so the error's variance is exactly 0 and
  explained_variance is 1, which sqlearn gives (DuckDB's ``var_pop`` of
  equal values is exactly 0). scikit-learn subtracts numpy's mean of the
  errors and of the target, which over 1,000 copies of a value that is not
  a short binary fraction comes back one rounding off; both variances are
  then tiny but not 0, and it scores their ratio: 0.75 here (0 on 100 rows,
  1 on 10). Probed 2026-11-19, scikit-learn 1.9.1; not a sqlearn defect.
  The same off-by-one-rounding mean gives r2 (and d2_tweedie at power 0,
  in numpy) a tiny total sum of squares there: about -3e30, where the
  target is constant and the answer is 0.
"""

import functools
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import duckdb
import mpmath
import numpy as np
from sklearn import metrics as skm

import sqlearn as sq
from validation import _cases

EPS = sys.float_info.epsilon

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value. Loosening a bound needs a written reason here, never a
# quiet edit. r2's total sum of squares is DuckDB's ``var_pop`` (a running
# update about the mean that is not compensated): measured at 11 doubles on
# 100,000 rows, and at 114,466 doubles (1.7e-11 relative) where the target's
# mean is a million times its spread. A metric's expression sees only the two
# columns, so it cannot shift by the mean first; the wide bound is that
# limit, recorded and named, not a tolerance. rmse and mae are compensated.
#
# The metrics of #63, first measured 2026-11-19 (in brackets, the most
# measured over every dataset but those in WIDE):
# - mse [1], mape [1], pinball_loss [1]: a compensated mean (favg, ADR 0033)
#   of rows each rounded a few times.
# - max_error and median_absolute_error [0]: one rounded subtraction per
#   row, then an exact pick (the median of an even count averages two).
# - msle [6] and rmsle [2]: Kahan's log1p (a few doubles per log, against
#   numpy's correctly rounded log1p) before the compensated mean; the 6 is
#   ``constant, inexact offset``, where every row's difference of two logs
#   carries the same error, so the mean cannot average it out.
# - explained_variance [36, on 100,000 rows]: two ``var_pop`` (r2's total,
#   above), so the same limit where the target's mean is far above its
#   spread (``offset``).
# - the deviances [1 on spread data]: per row scikit-learn's formula, a
#   difference of terms (logs or powers) that cancel where the prediction is
#   near the target, then the compensated mean. Where every row is near
#   (the constant datasets, ``zero target``'s exact rows at power -1) the
#   cancellation is the error, and scikit-learn and numpy land on the same
#   double as sqlearn: those are WIDE, each for the power measured. At -1
#   an exact prediction of 2 gives 2 * (8/6 - 4 + 8/3), whose three rounded
#   terms leave -8.9e-16 where the exact value is 0: a count of doubles from
#   0 is astronomically large though the error is one rounding of 8/3.
# - the D2 scores [5 for d2_tweedie, 6 for d2_pinball]: two compensated sums
#   of rows taken about a baseline rounded to a double, then one division.
BOUNDS = {
    "rmse": 2,
    "mae": 2,
    "r2": 16,
    "mse": 2,
    "max_error": 1,
    "median_absolute_error": 1,
    "mape": 2,
    "explained_variance": 48,
    "msle": 8,
    "rmsle": 4,
    "tweedie_deviance": 4,
    "poisson_deviance": 4,
    "gamma_deviance": 4,
    "pinball_loss": 2,
    "d2_tweedie": 8,
    "d2_pinball": 8,
    "d2_absolute_error": 8,
}
WIDE = {
    ("r2", "offset"): 120_000,
    ("explained_variance", "offset"): 120_000,
    ("tweedie_deviance, power=1.5", "constant"): 16,  # measured 12
    ("tweedie_deviance, power=1.0", "constant, offset"): 24,  # measured 20
    ("tweedie_deviance, power=1.5", "constant, offset"): 96,  # measured 86
    ("tweedie_deviance, power=2.0", "constant, offset"): 32,  # measured 23
    ("tweedie_deviance, power=-1.0", "zero target"): 40,  # measured 36
    ("tweedie_deviance, power=-1.0", "constant, exact"): 4_382_002_437_431_492_608,
    ("tweedie_deviance, power=3.0", "constant, offset"): 8,  # measured 4
    ("poisson_deviance", "constant, offset"): 24,  # measured 20
    ("gamma_deviance", "constant, offset"): 32,  # measured 23
    # On ``offset`` a log or a power of values near 1e6 is a difference of
    # terms a million times its size, in scikit-learn's formula and in every
    # library alike (scikit-learn and numpy measured as far or further);
    # each bound is its measurement (2026-11-19) with about a tenth to spare.
    ("msle", "offset"): 760_000,  # measured 683,262
    ("rmsle", "offset"): 360_000,  # measured 320,499
    ("tweedie_deviance, power=-1.0", "offset"): 620_000_000,  # 559,754,483
    ("tweedie_deviance, power=1.0", "offset"): 136_000_000_000,  # 122.8e9
    ("tweedie_deviance, power=1.5", "offset"): 70_000_000_000,  # 62.3e9
    ("tweedie_deviance, power=2.0", "offset"): 212_000_000_000,  # 191.9e9
    ("tweedie_deviance, power=3.0", "offset"): 288_000_000_000,  # 259.0e9
    ("poisson_deviance", "offset"): 136_000_000_000,  # 122.8e9
    ("gamma_deviance", "offset"): 212_000_000_000,  # 191.9e9
    ("d2_tweedie, power=-1.0", "offset"): 83_000_000_000,  # 74.4e9
    ("d2_tweedie, power=1.0", "offset"): 64_000_000_000,  # 57.7e9
    ("d2_tweedie, power=1.5", "offset"): 436_000_000_000,  # 392.2e9
    ("d2_tweedie, power=2.0", "offset"): 108_000_000_000,  # 97.0e9
    ("d2_tweedie, power=3.0", "offset"): 91_000_000_000,  # 82.0e9
}
"""Bounds wider than `BOUNDS` for one formula on one dataset, each at its
measurement and for the reason above `BOUNDS`. Keyed by formula, so a
widening for one power leaves every other power at its step's bound."""

POWERS = (-1.0, 0.0, 1.0, 1.5, 2.0, 3.0)
ALPHAS = (0.1, 0.5, 0.9)
NEAR_WHOLE = {"ten rows": (0.3, 0.7), "three rows": (1 / 3,)}
"""Alphas whose ``n * alpha`` is whole or one rounding from it, per dataset."""


@dataclass(frozen=True)
class Pair:
    """A dataset of targets and predictions, and whether every score runs on it.

    ``every`` False: a score whose range the values leave is not run on it.
    True: every score runs, and one whose range they leave must be refused.
    """

    data: _cases.Dataset
    y: tuple
    p: tuple
    every: bool


def _pairs() -> list[Pair]:
    """Return each dataset: its target values and its predictions."""
    rng = np.random.default_rng(_cases.SEED)

    def draw(n: int, offset: float = 0.0) -> tuple[tuple, tuple]:
        y = offset + rng.normal(size=n)
        p = y + rng.normal(scale=0.5, size=n)
        return tuple(float(v) for v in y), tuple(float(v) for v in p)

    def positive(n: int, scale: float = 1.0) -> tuple[tuple, tuple]:
        y = scale * np.exp(rng.normal(scale=0.5, size=n))
        p = y * np.exp(rng.normal(scale=0.3, size=n))
        return tuple(float(v) for v in y), tuple(float(v) for v in p)

    out: list[tuple[str, tuple, tuple, str, bool]] = []
    for name, n in _cases.SIZES.items():
        y, p = draw(n)
        out.append((name, y, p, f"{n:,} rows", False))
    y, p = draw(1_000, 1e6)
    out.append(("offset", y, p, "target mean 1e6, spread 1", False))
    y, p = draw(10)
    out.append(("ten rows", y, p, "10 rows: alpha 0.3 and 0.7 whole", False))
    y, p = draw(3)
    out.append(("three rows", y, p, "3 rows: alpha 1/3 nearly whole", False))
    for name, n in (("positive", 1_000), ("positive, large", 100_000)):
        y, p = positive(n)
        out.append((name, y, p, f"{n:,} rows above 0", False))
    y, p = positive(1_000, 1e-9)
    out.append(("tiny", y, p, "1,000 rows near 1e-9", False))
    counts = tuple(float(v) for v in rng.poisson(2.0, size=1_000))
    scale = rng.uniform(0.5, 1.5, 1_000)
    guess = tuple(float(v) for v in (np.array(counts) + 0.5) * scale)
    out.append(("counts", counts, guess, "counts with 0, predictions above 0", True))
    out.append(("below -1", (0.5, -1.0, 2.0, 3.0), (1.0, 1.0, 2.0, 2.5),
                "a target of -1", True))  # fmt: skip
    out.append(("zero prediction", (1.0, 2.0, 3.0, 4.0), (1.5, 0.0, 2.5, 4.0),
                "a prediction of 0", True))  # fmt: skip
    out.append(("zero target", (0.0, 2.0, 3.0, 4.0), (0.5, 1.5, 2.5, 4.0),
                "a target of 0", True))  # fmt: skip
    out.append(("negative mean", (-1.0, 0.5), (1.0, 1.0),
                "target mean below 0, predictions above 0", True))  # fmt: skip
    y, p = positive(1_000)
    out.append(("null", y, tuple(_cases._gaps(rng, list(p), None)),
                "a tenth of the predictions NULL", True))  # fmt: skip
    y, p = positive(1_000)
    out.append(("nan", y, tuple(_cases._gaps(rng, list(p), math.nan)),
                "a tenth of the predictions NaN", True))  # fmt: skip
    out.append(("empty", (), (), "no rows", True))
    out.append(("constant", (2.0,) * 10, (2.0, 1.0, 3.0) * 3 + (2.0,),
                "a constant target, predicted off", True))  # fmt: skip
    out.append(("constant, exact", (2.0,) * 10, (2.0,) * 10,
                "a constant target, predicted exactly", True))  # fmt: skip
    out.append(("constant, offset", (2.0,) * 10, (1.5,) * 10,
                "a constant target, every prediction 0.5 off", True))  # fmt: skip
    out.append(("constant, inexact offset", (0.3,) * 1_000, (0.1,) * 1_000,
                "target 0.3, prediction 0.1: no short binary fraction",
                True))  # fmt: skip
    out.append(("constant zero", (0.0,) * 6, (0.5, 1.0, 2.0) * 2,
                "a constant target of 0, predicted off", True))  # fmt: skip
    return [
        Pair(_cases.Dataset(name, "y", y, note), y, p, every)
        for name, y, p, note, every in out
    ]


# The ranges, as scikit-learn refuses rows (and sqlearn with it).


def _anywhere(y: tuple, p: tuple) -> bool:
    return True


def _above_minus_one(y: tuple, p: tuple) -> bool:
    return all(v > -1 for v in (*y, *p))


def _tweedie_range(power: float) -> Callable[[tuple, tuple], bool]:
    if 0 < power < 1:
        msg = f"no Tweedie deviance has power {power!r}: scikit-learn refuses it"
        raise ValueError(msg)

    def inside(y: tuple, p: tuple) -> bool:
        if power == 0:
            return True
        if not all(v > 0 for v in p):
            return False
        if power >= 2:
            return all(v > 0 for v in y)
        if power >= 1:
            return all(v >= 0 for v in y)
        return True

    return inside


# The exact values.


def _diffs(y: tuple, p: tuple) -> list[Fraction]:
    return [Fraction(a) - Fraction(b) for a, b in zip(y, p, strict=True)]


def _mpf(x: Fraction) -> mpmath.mpf:
    return mpmath.mpf(x.numerator) / x.denominator


def _sum_squares_about_mean(values: list[Fraction]) -> Fraction:
    mean = sum(values, Fraction(0)) / len(values)
    return sum(((v - mean) ** 2 for v in values), Fraction(0))


def _constant(y: tuple) -> bool:
    return min(y) == max(y)


def _exact_rmse(y: tuple, p: tuple) -> mpmath.mpf:
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.sqrt(_mpf(_exact_mse(y, p)))


def _exact_mae(y: tuple, p: tuple) -> Fraction:
    return sum((abs(d) for d in _diffs(y, p)), Fraction(0)) / len(y)


def _exact_mse(y: tuple, p: tuple) -> Fraction:
    return sum((d * d for d in _diffs(y, p)), Fraction(0)) / len(y)


def _exact_r2(y: tuple, p: tuple) -> Fraction:
    squares = _exact_mse(y, p) * len(y)
    total = _sum_squares_about_mean([Fraction(a) for a in y])
    if total == 0:
        return Fraction(1 if squares == 0 else 0)
    return 1 - squares / total


def _exact_max_error(y: tuple, p: tuple) -> Fraction:
    return max(abs(d) for d in _diffs(y, p))


def _exact_median_absolute_error(y: tuple, p: tuple) -> Fraction:
    ordered = sorted(abs(d) for d in _diffs(y, p))
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _exact_mape(y: tuple, p: tuple) -> Fraction:
    terms = (
        abs(d) / max(abs(Fraction(a)), Fraction(EPS))
        for d, a in zip(_diffs(y, p), y, strict=True)
    )
    return sum(terms, Fraction(0)) / len(y)


def _exact_explained_variance(y: tuple, p: tuple) -> Fraction:
    errors = _sum_squares_about_mean(_diffs(y, p))
    if _constant(y):
        return Fraction(1 if errors == 0 else 0)
    return 1 - errors / _sum_squares_about_mean([Fraction(a) for a in y])


@functools.cache
def _exact_msle(y: tuple, p: tuple) -> mpmath.mpf:
    with mpmath.workdps(_cases.DIGITS):
        terms = [
            (mpmath.log1p(mpmath.mpf(a)) - mpmath.log1p(mpmath.mpf(b))) ** 2
            for a, b in zip(y, p, strict=True)
        ]
        return mpmath.fsum(terms) / len(y)


def _exact_rmsle(y: tuple, p: tuple) -> mpmath.mpf:
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.sqrt(_exact_msle(y, p))


RATIONAL = (-1.0, 3.0)
"""Powers whose deviance has only whole powers: exact as a `Fraction`."""


def _deviance(y: object, mu: object, power: float) -> object:
    """Return one row's Tweedie deviance, as scikit-learn writes it (power not 0).

    `y` and `mu` are `Fraction` s at a power in `RATIONAL`, else mpmath
    numbers.
    """
    if power == 1:
        xlogy = 0 if y == 0 else y * mpmath.log(y / mu)  # type: ignore[operator]
        return 2 * (xlogy - y + mu)  # type: ignore[operator]
    if power == 2:
        return 2 * (mpmath.log(mu / y) + y / mu - 1)  # type: ignore[operator]
    q = int(power) if power in RATIONAL else mpmath.mpf(power)
    return 2 * (
        max(y, 0) ** (2 - q) / ((1 - q) * (2 - q))  # type: ignore[operator]
        - y * mu ** (1 - q) / (1 - q)  # type: ignore[operator]
        + mu ** (2 - q) / (2 - q)  # type: ignore[operator]
    )


@functools.cache
def _deviance_sum(y: tuple, mu: tuple | Fraction, power: float) -> object:
    """Return the exact sum of the deviances of `y` about `mu`.

    `mu` is a column of predictions or one value, a baseline.
    """
    rational = power in RATIONAL
    cast = Fraction if rational else _mpf
    guesses = mu if isinstance(mu, tuple) else (mu,) * len(y)
    rows = (
        _deviance(cast(Fraction(a)), cast(Fraction(b)), power)
        for a, b in zip(y, guesses, strict=True)
    )
    if rational:
        return sum(rows, Fraction(0))
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.fsum(rows)


def _exact_tweedie(power: float) -> Callable[[tuple, tuple], Fraction | mpmath.mpf]:
    def exact(y: tuple, p: tuple) -> Fraction | mpmath.mpf:
        if power == 0:
            return _exact_mse(y, p)
        with mpmath.workdps(_cases.DIGITS):
            return _deviance_sum(y, p, power) / len(y)  # type: ignore[operator]

    return exact


def _exact_d2_tweedie(power: float) -> Callable[[tuple, tuple], Fraction | mpmath.mpf]:
    def exact(y: tuple, p: tuple) -> Fraction | mpmath.mpf:
        if _constant(y):  # ADR 0054
            return Fraction(1 if all(a == b for a, b in zip(y, p, strict=True)) else 0)
        if power == 0:
            return _exact_r2(y, p)
        mean = sum((Fraction(a) for a in y), Fraction(0)) / len(y)
        with mpmath.workdps(_cases.DIGITS):
            model, baseline = _deviance_sum(y, p, power), _deviance_sum(y, mean, power)
            return 1 - model / baseline  # type: ignore[operator]

    return exact


def _pinball_sum(y: tuple, guesses: list[Fraction], alpha: float) -> Fraction:
    a = Fraction(alpha)
    total = Fraction(0)
    for target, guess in zip(y, guesses, strict=True):
        d = Fraction(target) - guess
        total += a * d if d > 0 else (a - 1) * d
    return total


def _exact_pinball(alpha: float) -> Callable[[tuple, tuple], Fraction]:
    def exact(y: tuple, p: tuple) -> Fraction:
        return _pinball_sum(y, [Fraction(v) for v in p], alpha) / len(y)

    return exact


def _quantile(y: tuple, alpha: float) -> Fraction:
    """Return the exact mean of the rows scikit-learn's baseline averages.

    The rows are picked in doubles, as ``_weighted_percentile(y, ones,
    alpha * 100, average=True)`` picks them: the cumulative weights are 1 to
    n, ``k = alpha * 100 / 100 * n``, the first row whose place is at least
    ``k`` (kept within 1 to n), and the next one too (at most the last)
    unless the row's place passes ``k`` by more than eps.
    """
    ordered = sorted(y)
    n = len(ordered)
    k = alpha * 100 / 100 * n
    if k == 0:
        k = math.nextafter(k, k + 1)
    i = min(max(math.ceil(k) - 1, 0), n - 1)
    j = i if (i + 1) - k > EPS else min(i + 1, n - 1)
    return (Fraction(ordered[i]) + Fraction(ordered[j])) / 2


def _exact_d2_pinball(alpha: float) -> Callable[[tuple, tuple], Fraction]:
    def exact(y: tuple, p: tuple) -> Fraction:
        model = _pinball_sum(y, [Fraction(v) for v in p], alpha)
        baseline = _pinball_sum(y, [_quantile(y, alpha)] * len(y), alpha)
        if baseline == 0:  # scikit-learn's force_finite (ADR 0054 when constant)
            return Fraction(1 if model == 0 else 0)
        return 1 - model / baseline

    return exact


# DuckDB alone: hand-written SQL over table ``data(y, p)``.


def _lit(x: float) -> str:
    return f"{x!r}::DOUBLE"


def _deviance_sql(y: str, mu: str, power: float) -> str:
    if power == 0:
        return f"({y} - {mu}) * ({y} - {mu})"
    if power == 1:
        xlogy = f"CASE WHEN {y} = 0 THEN 0 ELSE {y} * ln({y} / {mu}) END"
        return f"2 * ({xlogy} - {y} + {mu})"
    if power == 2:
        return f"2 * (ln({mu} / {y}) + {y} / {mu} - 1)"
    a, b = _lit(1 - power), _lit(2 - power)
    return (
        f"2 * (pow(greatest({y}, 0), {b}) / ({a} * {b}) "
        f"- {y} * pow({mu}, {a}) / {a} + pow({mu}, {b}) / {b})"
    )


def _pinball_sql(y: str, mu: str, alpha: float) -> str:
    return (
        f"({_lit(alpha)} * greatest({y} - {mu}, 0) "
        f"+ {_lit(1 - alpha)} * greatest({mu} - {y}, 0))"
    )


def _d2_tweedie_sql(power: float) -> str:
    return (
        "SELECT 1 - fsum(" + _deviance_sql("y", "p", power) + ") / fsum("
        + _deviance_sql("y", "m", power) + ") FROM (SELECT *, favg(y) OVER () AS m "
        "FROM data)"
    )  # fmt: skip


def _d2_pinball_sql(alpha: float) -> str:
    k = f"{_lit(alpha * 100 / 100)} * n"
    i = f"least(greatest(ceil({k}), 1), n)"
    return (
        "WITH s AS (SELECT y, p, row_number() OVER (ORDER BY y) AS r, "
        "count(*) OVER () AS n FROM data), "
        f"q AS (SELECT y, p, avg(CASE WHEN r = {i} OR ({i} - {k} <= {EPS!r} "
        f"AND r = least({i} + 1, n)) THEN y END) OVER () AS m FROM s) "
        f"SELECT 1 - fsum({_pinball_sql('y', 'p', alpha)}) / "
        f"fsum({_pinball_sql('y', 'm', alpha)}) FROM q"
    )


def _aggregate(expression: str) -> str:
    return f"SELECT {expression} FROM data"


def _mean_deviance_sql(power: float) -> str:
    return _aggregate(f"favg({_deviance_sql('y', 'p', power)})")


_LOG = "(ln(1 + y) - ln(1 + p))"


# numpy, with scikit-learn's force_finite rule for the scores of a fraction.


def _fraction(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return float(1 - numerator / denominator)


def _np_deviance(y: np.ndarray, mu: np.ndarray, power: float) -> np.ndarray:
    if power == 0:
        return (y - mu) ** 2
    if power == 1:
        safe = np.where(y == 0, 1.0, y)
        return 2 * (np.where(y == 0, 0.0, y * np.log(safe / mu)) - y + mu)
    if power == 2:
        return 2 * (np.log(mu / y) + y / mu - 1)
    return 2 * (
        np.maximum(y, 0) ** (2 - power) / ((1 - power) * (2 - power))
        - y * mu ** (1 - power) / (1 - power)
        + mu ** (2 - power) / (2 - power)
    )


def _np_pinball(y: np.ndarray, mu: np.ndarray, alpha: float) -> np.ndarray:
    return alpha * np.maximum(y - mu, 0) + (1 - alpha) * np.maximum(mu - y, 0)


def _np_d2_tweedie(power: float) -> Callable[[np.ndarray, np.ndarray], float]:
    def score(y: np.ndarray, p: np.ndarray) -> float:
        mean = np.full_like(y, np.mean(y))
        return _fraction(
            np.sum(_np_deviance(y, p, power)), np.sum(_np_deviance(y, mean, power))
        )

    return score


def _np_d2_pinball(alpha: float) -> Callable[[np.ndarray, np.ndarray], float]:
    def score(y: np.ndarray, p: np.ndarray) -> float:
        q = np.quantile(y, alpha, method="averaged_inverted_cdf")
        return _fraction(
            np.sum(_np_pinball(y, p, alpha)),
            np.sum(_np_pinball(y, np.full_like(y, q), alpha)),
        )

    return score


def _np_explained_variance(y: np.ndarray, p: np.ndarray) -> float:
    return _fraction(float(np.var(y - p)), float(np.var(y)))


def _np_r2(y: np.ndarray, p: np.ndarray) -> float:
    e = y - p
    return _fraction(float(np.sum(e * e)), float(np.sum((y - y.mean()) ** 2)))


@dataclass(frozen=True)
class Score:
    """One metric at one setting and its references."""

    step: str
    formula: str
    metric: sq.metrics.Metric
    inside: Callable[[tuple, tuple], bool]
    exact: Callable[[tuple, tuple], Fraction | mpmath.mpf]
    sql: str
    numpy: Callable[[np.ndarray, np.ndarray], float]
    sklearn: Callable[[np.ndarray, np.ndarray], float]
    alphas_from: str = ""


def _scores() -> list[Score]:
    """Return every metric at every setting validated, plain ones first."""
    m = sq.metrics
    out = [
        Score("rmse", "rmse", m.rmse, _anywhere, _exact_rmse,
              _aggregate("sqrt(favg((y - p) * (y - p)))"),
              lambda y, p: float(np.sqrt(np.mean((y - p) ** 2))),
              skm.root_mean_squared_error),
        Score("mae", "mae", m.mae, _anywhere, _exact_mae,
              _aggregate("favg(abs(y - p))"),
              lambda y, p: float(np.mean(np.abs(y - p))), skm.mean_absolute_error),
        Score("r2", "r2", m.r2, _anywhere, _exact_r2,
              _aggregate("1 - fsum((y - p) * (y - p)) / (var_pop(y) * count(y))"),
              _np_r2, skm.r2_score),
        Score("mse", "mse", m.mse, _anywhere, _exact_mse,
              _aggregate("favg((y - p) * (y - p))"),
              lambda y, p: float(np.mean((y - p) ** 2)), skm.mean_squared_error),
        Score("max_error", "max_error", m.max_error, _anywhere, _exact_max_error,
              _aggregate("max(abs(y - p))"),
              lambda y, p: float(np.max(np.abs(y - p))), skm.max_error),
        Score("median_absolute_error", "median_absolute_error",
              m.median_absolute_error, _anywhere, _exact_median_absolute_error,
              _aggregate("median(abs(y - p))"),
              lambda y, p: float(np.median(np.abs(y - p))),
              skm.median_absolute_error),
        Score("mape", "mape", m.mape, _anywhere, _exact_mape,
              _aggregate(f"favg(abs(y - p) / greatest(abs(y), {EPS!r}))"),
              lambda y, p: float(np.mean(np.abs(y - p) / np.maximum(np.abs(y), EPS))),
              skm.mean_absolute_percentage_error),
        Score("explained_variance", "explained_variance", m.explained_variance,
              _anywhere, _exact_explained_variance,
              _aggregate("1 - var_pop(y - p) / var_pop(y)"),
              _np_explained_variance, skm.explained_variance_score),
        Score("msle", "msle", m.msle, _above_minus_one, _exact_msle,
              _aggregate(f"favg({_LOG} * {_LOG})"),
              lambda y, p: float(np.mean((np.log1p(y) - np.log1p(p)) ** 2)),
              skm.mean_squared_log_error),
        Score("rmsle", "rmsle", m.rmsle, _above_minus_one, _exact_rmsle,
              _aggregate(f"sqrt(favg({_LOG} * {_LOG}))"),
              lambda y, p: float(np.sqrt(np.mean((np.log1p(y) - np.log1p(p)) ** 2))),
              skm.root_mean_squared_log_error),
    ]  # fmt: skip
    for power in POWERS:
        out.append(Score(
            "tweedie_deviance", f"tweedie_deviance, power={power!r}",
            m.tweedie_deviance(power=power), _tweedie_range(power),
            _exact_tweedie(power), _mean_deviance_sql(power),
            lambda y, p, w=power: float(np.mean(_np_deviance(y, p, w))),
            lambda y, p, w=power: skm.mean_tweedie_deviance(y, p, power=w),
        ))  # fmt: skip
    for step, power, theirs in (
        ("poisson_deviance", 1.0, skm.mean_poisson_deviance),
        ("gamma_deviance", 2.0, skm.mean_gamma_deviance),
    ):
        out.append(Score(
            step, step, getattr(m, step), _tweedie_range(power),
            _exact_tweedie(power), _mean_deviance_sql(power),
            lambda y, p, w=power: float(np.mean(_np_deviance(y, p, w))), theirs,
        ))  # fmt: skip
    for alpha in ALPHAS:
        out.append(Score(
            "pinball_loss", f"pinball_loss, alpha={alpha!r}",
            m.pinball_loss(alpha=alpha), _anywhere, _exact_pinball(alpha),
            _aggregate(f"favg({_pinball_sql('y', 'p', alpha)})"),
            lambda y, p, a=alpha: float(np.mean(_np_pinball(y, p, a))),
            lambda y, p, a=alpha: skm.mean_pinball_loss(y, p, alpha=a),
        ))  # fmt: skip
    for power in POWERS:
        out.append(Score(
            "d2_tweedie", f"d2_tweedie, power={power!r}",
            m.d2_tweedie(power=power), _tweedie_range(power),
            _exact_d2_tweedie(power), _d2_tweedie_sql(power), _np_d2_tweedie(power),
            lambda y, p, w=power: skm.d2_tweedie_score(y, p, power=w),
        ))  # fmt: skip
    near = sorted({a for alphas in NEAR_WHOLE.values() for a in alphas})
    for alpha in (*ALPHAS, *near):
        out.append(Score(
            "d2_pinball", f"d2_pinball, alpha={alpha!r}",
            m.d2_pinball(alpha=alpha), _anywhere, _exact_d2_pinball(alpha),
            _d2_pinball_sql(alpha), _np_d2_pinball(alpha),
            lambda y, p, a=alpha: skm.d2_pinball_score(y, p, alpha=a),
            alphas_from="" if alpha in ALPHAS else "near",
        ))  # fmt: skip
    out.append(Score(
        "d2_absolute_error", "d2_absolute_error", m.d2_absolute_error, _anywhere,
        _exact_d2_pinball(0.5), _d2_pinball_sql(0.5), _np_d2_pinball(0.5),
        skm.d2_absolute_error_score,
    ))  # fmt: skip
    return out


def _runs_on(score: Score, pair: Pair) -> bool:
    """Tell whether a score is validated on a dataset."""
    if score.alphas_from:
        alpha = score.metric.alpha  # type: ignore[attr-defined]
        return alpha in NEAR_WHOLE.get(pair.data.name, ())
    if pair.every:
        return True
    return score.inside(pair.y, pair.p)


def _duckdb(sql: str, y: tuple, p: tuple, threads: int | None) -> float:
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    _cases.table(con, "data", {"y": y, "p": p}, "DOUBLE")
    return con.sql(sql).fetchall()[0][0]


def cases() -> list[dict]:
    """Return the cases of the regression metrics: each dataset and reference."""
    out = []
    scores = _scores()
    for pair in _pairs():
        y, p = pair.y, pair.p
        complete = bool(y) and not any(_cases.is_missing(v) for v in (*y, *p))
        for score in scores:
            if not _runs_on(score, pair):
                continue
            answerable = complete and score.inside(y, p)
            exact = score.exact(y, p) if answerable else None

            def ours(metric=score.metric, y=y, p=p) -> float:
                rel = _cases.sqlearn_table({"y": y, "prediction": p}, "DOUBLE")
                return metric.compute(rel, "y")

            def arrays(y=y, p=p) -> tuple[np.ndarray, np.ndarray]:
                return _cases.as_nan(y), _cases.as_nan(p)

            sql = score.sql
            answers = {
                "sqlearn": ours,
                "duckdb": lambda s=sql, y=y, p=p: _duckdb(s, y, p, None),
                "duckdb, 1 thread": lambda s=sql, y=y, p=p: _duckdb(s, y, p, 1),
                "numpy": lambda f=score.numpy, a=arrays: f(*a()),
                "scikit-learn": lambda f=score.sklearn, a=arrays: f(*a()),
            }
            out += _cases.measure_all(
                step=score.step,
                formula=score.formula,
                data=pair.data,
                type="DOUBLE",
                exact=exact,
                bound=WIDE.get((score.formula, pair.data.name), BOUNDS[score.step]),
                answers=answers,
            )
    return out
