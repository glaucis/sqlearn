"""Validate ``sq.explore`` against the exact value of every statistic.

The canonical values (ADR 0016), from the doubles' exact values:

- ``profile``: the mean, the extremes and the quartiles are `Fraction`s (a
  quartile's rank found as numpy finds it, in doubles, its value then
  interpolated exactly); the sample standard deviation (ddof 1) and the
  sample-adjusted skewness are mpmath at `_cases.DIGITS` digits, the root of
  an exact rational; the excess kurtosis, pandas' sample-adjusted one, is
  rational and so a `Fraction`. NULL and NaN are missing, and ±infinity is
  left out of every numeric statistic and counted only in ``infinite``. The
  counts (rows, missing, distinct, zeros, negative, infinite, a text's
  lengths) and the shares (one division of two counts, so the double nearest
  the exact ratio) must be equal;
- ``histogram``: the edges of numpy's linspace rule computed exactly,
  ``low + k (high - low) / bins``, then rounded once; each bin's count is
  the values between numpy's edges, the last bin closed, and must be
  equal. A column of one distinct finite value has one bin, its low and
  high that value (sqlearn's rule; numpy widens it by 0.5 either side);
- ``top``: a `collections.Counter` of the values, NULL and NaN one missing
  value, the commonest first, ties by the value as DuckDB writes it as text
  (the rule ``top`` states), the missing value last; every value, count and
  share must be equal;
- ``missing``: a `collections.Counter` of each row's tuple of missing flags,
  the commonest first, ties by the flags (present before missing, in the
  columns' order); every pattern, count and share must be equal;
- ``correlations``: Pearson's ``Sxy / sqrt(Sxx Syy)`` over each pair's rows
  where both values are present and finite, the sums exact integers (the
  doubles scaled by a power of two) and the root mpmath's; Spearman's the
  same over average ranks found among those rows. NULL where fewer than two
  such rows or either column has no variance over them.

A correlation lies in [-1, 1], and the generated data puts many of them near
0 (a column against an unrelated one), where a plain ULP count measures the
exact value's own tiny scale and not the computation: every correlation is
measured in ULPs of 1, the scale of its range (``ulps`` holds that distance
as a float and ``ulps_of`` the scale), as ``validate_pca`` measures in ULPs
of a scale. The skewness and the excess kurtosis, near 0 on normal data for
the same reason, are measured in ULPs of 1 as well: each is a ratio of
moments whose scale is 1 (the excess kurtosis is that ratio less about 3).
In plain ULPs the kurtosis read 2,217 for sqlearn and 2,476 for pandas,
which measures how close to 0 it is, not the computation.

A histogram's edges are measured in ULPs of the larger of the extremes'
magnitudes, the scale ``low + k * width`` is rounded at: an edge near 0
between a negative low and a positive high carries that rounding (on
``signed``, an edge at 0.3 between -3.9 and 3.1 is 13 plain ULPs off for
sqlearn and numpy alike, 1.6 ULPs of 3.9). Its counts are those of the
edges numpy's linspace gives in doubles, ``low + k * ((high - low) /
bins)``, the bins ``histogram`` promises: against the exactly rounded
edges, 7 values of 0.3 on ``signed`` move to the next bin for sqlearn and
numpy alike, an artefact of the exact edge, not an error of either.

The datasets: `_cases.numbers()`, and one more, ``signed``: 1,000 values
around 0, rounded to one decimal (so they hold ties, zeros and negative
zeros), a tenth NaN, a twentieth NULL and six infinities; ``profile`` and
``top`` also take `_cases.labels()`, and ``profile`` each numeric dataset
as BOOLEAN (``x > 1000``; ``x > 0`` on ``signed``). ``missing`` and
``correlations`` take each numeric dataset beside three columns generated
from `_cases.SEED`: ``related`` (0.8 of the column plus noise, a twentieth
NULL), ``unrelated`` (independent, a tenth NaN) and ``city`` (text, a tenth
NULL).

Beside sqlearn: pandas (``describe``'s statistics, ``skew``, ``kurt``,
``nunique``, ``isna``, ``value_counts``, ``isna().value_counts()``,
``corr``) and numpy (``mean``, ``std(ddof=1)``, ``min``, ``max``,
``quantile``, ``histogram``, ``corrcoef``). They are fed the same rows, with
±infinity as NaN for the numeric statistics, so the comparison is like for
like. pandas counts ``top``'s values and ``missing``'s patterns without
sqlearn's order of ties: every count is compared, not the order. A function
a reference lacks is recorded as skipped with the reason.
"""

import bisect
import math
import warnings
from collections import Counter
from collections.abc import Callable, Sequence
from fractions import Fraction

import duckdb
import mpmath
import numpy as np
import pandas as pd

import sqlearn as sq
from validation import _cases

STEP = "explore"

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. Where DuckDB's threads
# finish in another order from run to run (ADR 0043), the bound is set from
# the worst of six runs. First measured (2026-11-21, six runs):
# - 0 ULPs for the extremes, the median, the third quartile and the share
#   true; 1 for the first quartile (large set: the interpolation rounded);
# - 25 for the mean on the first run (large set), 8 to 27 over six: the
#   profile's mean is DuckDB's `avg`, one sum of doubles, where `sq.agg.mean`
#   (`favg`, compensated) reaches 1; hence 32;
# - 6 for the standard deviation (medium set, every run): DuckDB's one-pass
#   `stddev_samp`, where `sq.agg.std` (two compensated passes) reaches 2;
#   hence 8;
# - in ULPs of 1: 3.2 for the skewness (nan set) and 36 to 37 for the excess
#   kurtosis (reserved and large sets), DuckDB's `skewness` and `kurtosis`;
#   pandas is as far (7.9 on the small set); hence 4 and 64;
# - in ULPs of the larger extreme: 1.6 for the histogram's edges (signed
#   set), the same as numpy's; hence 2;
# - in ULPs of 1: 33.2 for Pearson (large set, x ~ related, every run;
#   pandas 32.7, numpy 0.8), DuckDB's `corr`; hence 64; for Spearman (large
#   set) the worst of each of five more runs (2026-11-21) was 16.4, 10.9, 9.0,
#   9.2 and 8.7 (the earlier six: 8.6 to 9.3): DuckDB sums doubles in
#   thread-finish order (ADR 0043), and the pair `x ~ unrelated` has a
#   correlation near 0.002, so a rounding of the sums moves it by many ULPs;
#   the worst, 16.4, is above 16, hence 32.
BOUNDS = {
    "mean": 32,
    "share true": 1,
    "std": 8,
    "min": 1,
    "q25": 1,
    "median": 1,
    "q75": 1,
    "max": 1,
    "skewness": 4,
    "kurtosis": 64,
    "edges": 2,
    "pearson": 64,
    "spearman": 32,
}

QUARTILES = {"q25": 0.25, "median": 0.5, "q75": 0.75}
BINS = (1, 10)
"""The bin counts every histogram is validated at."""
K = 10
"""How many values `top` keeps, and patterns `missing` keeps."""


# The datasets.


def signed() -> _cases.Dataset:
    """Return 1,000 values around 0 with ties, zeros, gaps and infinities."""
    rng = np.random.default_rng(_cases.SEED)
    values: list[float | None] = [round(float(v), 1) for v in rng.normal(0, 1, 1000)]
    values = _cases._gaps(rng, values, math.nan)
    holes = rng.random(len(values)) < 0.05
    values = [None if hole else v for v, hole in zip(values, holes, strict=True)]
    for i, place in enumerate(rng.choice(len(values), 6, replace=False)):
        values[int(place)] = math.inf if i % 2 else -math.inf
    return _cases.Dataset(
        "signed",
        "x",
        tuple(values),
        "1,000 values normal(0, 1) to one decimal, NaN, NULL and ±inf",
    )


def numeric() -> list[_cases.Dataset]:
    """Return the numeric datasets: `_cases.numbers()` and ``signed``."""
    return [*_cases.numbers(), signed()]


def usable(v: object) -> bool:
    """Tell whether a value enters a numeric statistic: present and finite."""
    return not _cases.is_missing(v) and math.isfinite(v)  # type: ignore[arg-type]


def finite(values: Sequence) -> list[float]:
    """Return the values present and finite."""
    return [v for v in values if usable(v)]


def companions(data: _cases.Dataset) -> dict[str, tuple]:
    """Return the dataset's column with three generated columns beside it."""
    rng = np.random.default_rng(_cases.SEED)
    n = len(data.values)
    around = 0.0 if data.name == "signed" else 1_000.0
    spread = 1.0 if data.name == "signed" else 100.0
    base = [v if usable(v) else around for v in data.values]
    noise = rng.normal(0, 0.6 * spread, n)
    related: list[float | None] = [
        0.8 * b + float(e) for b, e in zip(base, noise, strict=True)
    ]
    if data.name == "signed":
        related = [round(v, 1) for v in related]  # type: ignore[arg-type]
    holes = rng.random(n) < 0.05
    related = [None if h else v for v, h in zip(related, holes, strict=True)]
    unrelated = _cases._gaps(rng, [float(v) for v in rng.normal(0, 1, n)], math.nan)
    city = _cases._gaps(rng, [str(w) for w in rng.choice(_cases.WORDS, n)], None)
    return {
        data.column: data.values,
        "related": tuple(related),
        "unrelated": tuple(unrelated),
        "city": tuple(city),
    }


def as_booleans(data: _cases.Dataset) -> _cases.Dataset:
    """Return the dataset as BOOLEAN: above its centre, missing kept NULL."""
    cut = 0.0 if data.name == "signed" else 1_000.0
    values = tuple(None if not usable(v) else v > cut for v in data.values)  # type: ignore[operator]
    return _cases.Dataset(data.name, data.column, values, data.note + ", as x > centre")


def nan_series(values: Sequence) -> pd.Series:
    """Return a float Series, NULL, NaN and ±infinity all NaN."""
    return pd.Series([v if usable(v) else math.nan for v in values], dtype=float)


# The exact values.


def scaled_integers(values: Sequence[float]) -> tuple[list[int], int]:
    """Return the doubles times ``2**e``, all integers, and that exponent ``e``."""
    exponent = max(
        (Fraction(v).denominator.bit_length() - 1 for v in values), default=0
    )
    return [int(Fraction(v) * 2**exponent) for v in values], exponent


def central_sums(values: Sequence[float], powers: Sequence[int]) -> dict[int, Fraction]:
    """Return the exact sums of the deviations from the mean to each power.

    With ``X = x 2**e`` integers, ``x - mean = (n X - sum X) / (n 2**e)``,
    so each sum is an integer over ``(n 2**e) ** p``.
    """
    n = len(values)
    big, exponent = scaled_integers(values)
    total = sum(big)
    deviations = [n * x - total for x in big]
    return {
        p: Fraction(sum(d**p for d in deviations), (n * 2**exponent) ** p)
        for p in powers
    }


def exact_mean(values: Sequence[float]) -> Fraction | None:
    """Return the exact mean, or None for no values."""
    return _cases.exact_mean(list(values)) if values else None


def exact_std(values: Sequence[float]) -> mpmath.mpf | None:
    """Return the sample standard deviation (ddof 1), or None below two values."""
    if len(values) < 2:
        return None
    variance = central_sums(values, [2])[2] / (len(values) - 1)
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.sqrt(mpmath.mpf(variance.numerator) / variance.denominator)


def exact_skewness(values: Sequence[float]) -> mpmath.mpf | None:
    """Return pandas' sample-adjusted skewness, or None below three values."""
    n = len(values)
    if n < 3:
        return None
    sums = central_sums(values, [2, 3])
    if sums[2] == 0:
        return None
    with mpmath.workdps(_cases.DIGITS):
        m2 = mpmath.mpf(sums[2].numerator) / sums[2].denominator
        m3 = mpmath.mpf(sums[3].numerator) / sums[3].denominator
        return n * mpmath.sqrt(n - 1) / (n - 2) * m3 / m2**1.5


def exact_kurtosis(values: Sequence[float]) -> Fraction | None:
    """Return pandas' sample-adjusted excess kurtosis, or None below four values."""
    n = len(values)
    if n < 4:
        return None
    sums = central_sums(values, [2, 4])
    if sums[2] == 0:
        return None
    left = Fraction(n * (n + 1) * (n - 1)) * sums[4]
    left /= (n - 2) * (n - 3) * sums[2] ** 2
    return left - Fraction(3 * (n - 1) ** 2, (n - 2) * (n - 3))


def exact_quartile(ordered: Sequence[float], q: float) -> Fraction | None:
    """Return the linear quantile: rank as numpy finds it in doubles, value exact."""
    if not ordered:
        return None
    index = (len(ordered) - 1) * q
    low = math.floor(index)
    high = min(low + 1, len(ordered) - 1)
    weight = Fraction(index - low)
    lo, hi = Fraction(ordered[low]), Fraction(ordered[high])
    return lo + weight * (hi - lo)


def average_ranks(values: Sequence[float]) -> list[Fraction]:
    """Return each value's average rank from 1, ties sharing the mean of theirs."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks: list[Fraction] = [Fraction(0)] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        rank = Fraction(start + end + 2, 2)
        for i in order[start : end + 1]:
            ranks[i] = rank
        start = end + 1
    return ranks


def exact_pearson(xs: Sequence, ys: Sequence) -> mpmath.mpf | None:
    """Return the exact Pearson correlation, or None with no variance."""
    n = len(xs)
    if n < 2:
        return None
    x, y = scaled_integers(xs)[0], scaled_integers(ys)[0]
    sx, sy = sum(x), sum(y)
    sxy = n * sum(a * b for a, b in zip(x, y, strict=True)) - sx * sy
    sxx = n * sum(a * a for a in x) - sx * sx
    syy = n * sum(b * b for b in y) - sy * sy
    if sxx == 0 or syy == 0:
        return None
    with mpmath.workdps(_cases.DIGITS):
        return mpmath.mpf(sxy) / mpmath.sqrt(mpmath.mpf(sxx) * syy)


def complete(xs: Sequence, ys: Sequence) -> tuple[list[float], list[float]]:
    """Return a pair's rows where both values are present and finite."""
    both = [(a, b) for a, b in zip(xs, ys, strict=True) if usable(a) and usable(b)]
    return [a for a, _ in both], [b for _, b in both]


def exact_correlation(xs: Sequence, ys: Sequence, method: str) -> mpmath.mpf | None:
    """Return a pair's exact correlation by `method` over its complete rows."""
    a, b = complete(xs, ys)
    if method == "spearman":
        a = [float(2 * r) for r in average_ranks(a)]
        b = [float(2 * r) for r in average_ranks(b)]
    return exact_pearson(a, b)


# Measuring.


def _quiet(compute: Callable[[], object]) -> object:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return compute()


def _head(formula: str, data: _cases.Dataset, kind: str, bound: int) -> dict:
    return {
        "step": STEP,
        "formula": formula,
        "dataset": data.name,
        "rows": len(data.values),
        "type": kind,
        "bound": bound,
    }


def _is_null(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def measured(
    head: dict,
    exact: Fraction | mpmath.mpf | None,
    answers: dict[str, Callable[[], object]],
    *,
    scale: float | None = None,
    notes: dict[str, str] | None = None,
) -> list[dict]:
    """Measure each reference's answer against `exact`, in ULPs of `scale` if given.

    `exact` None means the statistic is undefined on the input: sqlearn must
    give NULL to pass, and each reference is skipped with what it gave.
    """
    out = []
    for reference, answer in answers.items():
        note = (notes or {}).get(reference, "")
        try:
            raw = _quiet(answer)
        except Exception as exc:  # noqa: BLE001  (each library's refusal is recorded)
            out.append(
                _cases.skipped(
                    reference=reference,
                    result="fail" if reference == "sqlearn" else "skipped",
                    note=_cases.first_line(exc),
                    **head,
                )
            )
            continue
        if exact is None:
            null = _is_null(raw)
            out.append(
                _cases.skipped(
                    reference=reference,
                    result=("pass" if null else "fail")
                    if reference == "sqlearn"
                    else "skipped",
                    note=f"undefined on this input; returned {raw!r}",
                    **head,
                )
            )
            continue
        value = math.nan if raw is None else float(raw)  # type: ignore[arg-type]
        case = _cases.case(
            reference=reference, value=value, exact=exact, note=note, **head
        )
        if scale is not None:
            with mpmath.workdps(_cases.DIGITS):
                target = _cases._mpf(exact)
                distance = (
                    math.inf
                    if math.isnan(value)
                    else float(abs(mpmath.mpf(value) - target) / math.ulp(scale))
                )
            case["ulps"] = distance
            case["ulps_of"] = scale
            case["result"] = _cases.judge(reference, distance, head["bound"])
        out.append(case)
    return out


def agreed(
    head: dict, reference: str, mismatches: int, cells: int, compared_with: str
) -> dict:
    """Record an answer compared value by value with the exact one.

    sqlearn fails on any difference; a reference that differs is an anomaly.
    """
    fields = {k: v for k, v in head.items() if k != "bound"}
    out = _cases.exact_case(
        mismatches=mismatches,
        cells=cells,
        compared_with=compared_with,
        **fields,
    )
    out["reference"] = reference
    out["result"] = _cases.judge(reference, mismatches, 0)
    return out


def differences(got: Sequence, want: Sequence) -> tuple[int, int]:
    """Return how many cells differ and how many there are, rows aligned."""
    cells = max(len(got), len(want))
    return sum(1 for a, b in zip(got, want, strict=False) if a != b) + abs(
        len(got) - len(want)
    ), cells


def missing_reason(head: dict, reference: str, why: str) -> dict:
    """Record a reference that has no such function."""
    return _cases.skipped(reference=reference, note=why, **head)


# profile


def _table(data: _cases.Dataset, kind: str) -> duckdb.DuckDBPyRelation:
    return _cases.sqlearn_table({data.column: data.values}, kind)


def _profiled(data: _cases.Dataset, kind: str) -> dict:
    rows = sq.explore.profile(_table(data, kind), out="pandas").to_dict("records")
    return {k: (None if _is_null(v) or v is pd.NA else v) for k, v in rows[0].items()}


def _counts(data: _cases.Dataset, row: dict, kind: str) -> list[dict]:
    """Each count and share of a profile, against the exact one."""
    values = data.values
    present = [v for v in values if not _cases.is_missing(v)]
    rows, missing = len(values), len(values) - len(present)
    exact: dict[str, object] = {
        "rows": rows,
        "missing": missing,
        "distinct": len(set(present)),
        "missing_share": None if rows == 0 else missing / rows,
        "distinct_share": None
        if not present
        else min(len(set(present)) / len(present), 1.0),
    }
    if kind == "DOUBLE":
        exact |= {
            "zeros": sum(1 for v in present if math.isfinite(v) and v == 0),
            "negative": sum(1 for v in present if math.isfinite(v) and v < 0),
            "infinite": sum(1 for v in present if math.isinf(v)),
        }
    if kind == "VARCHAR":
        lengths = [len(v) for v in present]
        exact |= {
            "min_length": min(lengths, default=None),
            "max_length": max(lengths, default=None),
        }
    series = (
        pd.Series(_cases.as_nan(values))
        if kind == "DOUBLE"
        else pd.Series(list(values), dtype="boolean" if kind == "BOOLEAN" else object)
    )
    raw = _cases.as_nan(values) if kind == "DOUBLE" else None
    texts = series.dropna().astype(str).str.len() if kind == "VARCHAR" else None
    pandas: dict[str, Callable[[], object]] = {
        "rows": lambda: len(series),
        "missing": lambda: int(series.isna().sum()),
        "distinct": lambda: int(series.nunique()),
        "zeros": lambda: int((series == 0).sum()),
        "negative": lambda: int(series[np.isfinite(raw)].lt(0).sum()),  # type: ignore[arg-type]
        "infinite": lambda: int(np.isinf(raw).sum()),  # type: ignore[arg-type]
        "min_length": lambda: None if texts.empty else int(texts.min()),  # type: ignore[union-attr]
        "max_length": lambda: None if texts.empty else int(texts.max()),  # type: ignore[union-attr]
    }
    out = []
    for name, want in exact.items():
        head = _head(f"profile: {name}", data, kind, 0)
        got = row[name]
        out.append(
            agreed(head, "sqlearn", int(got != want), 1, "the exact count or ratio")
        )
        if name in pandas:
            theirs = _quiet(pandas[name])
            out.append(
                agreed(head, "pandas", int(theirs != want), 1, "the exact count")
            )
    return out


def _numbers(data: _cases.Dataset, row: dict) -> list[dict]:
    """Each numeric statistic of a profile, against its exact value."""
    values = finite(data.values)
    ordered = sorted(values)
    series = nan_series(data.values)
    array = np.array(values, dtype=float)
    exact: dict[str, Fraction | mpmath.mpf | None] = {
        "mean": exact_mean(values),
        "std": exact_std(values),
        "min": Fraction(ordered[0]) if ordered else None,
        "max": Fraction(ordered[-1]) if ordered else None,
        "skewness": exact_skewness(values),
        "kurtosis": exact_kurtosis(values),
    }
    exact |= {name: exact_quartile(ordered, q) for name, q in QUARTILES.items()}
    pandas: dict[str, Callable[[], object]] = {
        "mean": series.mean,
        "std": series.std,
        "min": series.min,
        "max": series.max,
        "skewness": series.skew,
        "kurtosis": series.kurt,
    }
    pandas |= {n: (lambda q=q: series.quantile(q)) for n, q in QUARTILES.items()}
    numpy: dict[str, Callable[[], object]] = {
        "mean": lambda: np.mean(array),
        "std": lambda: np.std(array, ddof=1),
        "min": lambda: np.min(array),
        "max": lambda: np.max(array),
    }
    numpy |= {n: (lambda q=q: np.quantile(array, q)) for n, q in QUARTILES.items()}
    out = []
    for name in BOUNDS:
        if name not in exact:
            continue
        head = _head(f"profile: {name}", data, "DOUBLE", BOUNDS[name])
        answers = {"sqlearn": lambda name=name: row[name], "pandas": pandas[name]}
        if name in numpy:
            answers["numpy"] = numpy[name]
        out += measured(
            head,
            exact[name],
            answers,
            scale=1.0 if name in ("skewness", "kurtosis") else None,
        )
        if name not in numpy:
            out.append(missing_reason(head, "numpy", f"numpy has no {name} function"))
    return out


def _booleans(data: _cases.Dataset) -> list[dict]:
    """The share true of a BOOLEAN column, and its counts."""
    flags = as_booleans(data)
    row = _profiled(flags, "BOOLEAN")
    present = [v for v in flags.values if v is not None]
    exact = Fraction(sum(present), len(present)) if present else None
    head = _head("profile: share true", flags, "BOOLEAN", BOUNDS["share true"])
    out = _counts(flags, row, "BOOLEAN")
    out += measured(
        head,
        exact,
        {
            "sqlearn": lambda: row["mean"],
            "pandas": lambda: pd.Series(list(flags.values), dtype="boolean").mean(),
            "numpy": lambda: np.mean(np.array(present, dtype=float)),
        },
    )
    return out


def profile_cases() -> list[dict]:
    """Return every profile statistic's cases."""
    out = []
    for data in numeric():
        row = _profiled(data, "DOUBLE")
        out += _counts(data, row, "DOUBLE")
        out += _numbers(data, row)
        out += _booleans(data)
    for data in _cases.labels():
        out += _counts(data, _profiled(data, "VARCHAR"), "VARCHAR")
    return out


# histogram


def exact_histogram(
    values: Sequence[float], bins: int
) -> tuple[list[Fraction], list[int]]:
    """Return the exact edges and each bin's count, numpy's rule.

    The counts are those of the edges numpy's linspace gives in doubles,
    ``low + k * ((high - low) / bins)``, the bins the docstring promises: a
    value on an edge goes to the bin that double edge starts, even where
    the exact edge lies on its other side.
    """
    usable_values = finite(values)
    if not usable_values:
        return [], []
    low, high = min(usable_values), max(usable_values)
    if low == high:
        return [Fraction(low), Fraction(high)], [len(usable_values)]
    width = (Fraction(high) - Fraction(low)) / bins
    edges = [Fraction(low) + k * width for k in range(bins)] + [Fraction(high)]
    step = (high - low) / bins
    doubles = [low + k * step for k in range(bins)] + [high]
    counts = [0] * bins
    for v in usable_values:
        counts[min(bisect.bisect_right(doubles, v) - 1, bins - 1)] += 1
    return edges, counts


def _edges_case(
    head: dict, reference: str, got: Sequence[float], edges: Sequence[Fraction]
) -> dict:
    """The worst edge of a histogram against the exact edges.

    Measured in ULPs of the larger of the extremes' magnitudes: an edge is
    ``low`` plus a multiple of the width, rounded at that scale, so an edge
    near 0 between a negative low and a positive high carries that scale's
    rounding, not its own.
    """
    if len(got) != len(edges):
        return _cases.skipped(
            reference=reference,
            result="fail" if reference == "sqlearn" else "anomaly",
            note=f"{len(got) - 1} bins, not {len(edges) - 1}",
            **head,
        )
    scale = max(abs(float(edges[0])), abs(float(edges[-1])))
    if scale == 0:
        scale = 1.0
    worst = max(range(len(edges)), key=lambda i: abs(Fraction(got[i]) - edges[i]))
    out = _cases.case(
        reference=reference,
        value=float(got[worst]),
        exact=edges[worst],
        note=f"the worst of {len(edges)} edges, edge {worst}",
        **head,
    )
    distance = float(
        abs(Fraction(got[worst]) - edges[worst]) / Fraction(math.ulp(scale))
    )
    out["ulps"] = distance
    out["ulps_of"] = scale
    out["result"] = _cases.judge(reference, distance, head["bound"])
    return out


def histogram_cases() -> list[dict]:
    """Return each histogram's edges and counts against the exact ones."""
    out = []
    for data in numeric():
        values = finite(data.values)
        for bins in BINS:
            edges, counts = exact_histogram(data.values, bins)
            rows = sq.explore.histogram(
                _table(data, "DOUBLE"), bins=bins, out="pandas"
            ).to_dict("records")
            got_edges = [r["low"] for r in rows] + [r["high"] for r in rows[-1:]]
            got_counts = [int(r["count"]) for r in rows]
            formula = f"histogram, bins={bins}"
            edge_head = _head(f"{formula}: edges", data, "DOUBLE", BOUNDS["edges"])
            count_head = _head(f"{formula}: counts", data, "DOUBLE", 0)
            pandas = "pandas has no histogram of its own (Series.hist draws numpy's)"
            if not edges:
                note = "no finite value: no bins"
                mismatches = len(rows)
                out.append(agreed(count_head, "sqlearn", mismatches, 1, note))
                out.append(
                    missing_reason(edge_head, "numpy", "numpy refuses no values")
                )
                out.append(missing_reason(count_head, "pandas", pandas))
                continue
            out.append(_edges_case(edge_head, "sqlearn", got_edges, edges))
            mismatches, cells = differences(got_counts, counts)
            out.append(
                agreed(count_head, "sqlearn", mismatches, cells, "the exact counts")
            )
            if len(counts) == 1 and len(set(values)) == 1:
                why = "one distinct value: numpy widens the range by 0.5 either side"
                out.append(missing_reason(edge_head, "numpy", why))
                out.append(missing_reason(count_head, "numpy", why))
            else:
                theirs, their_edges = np.histogram(np.array(values), bins)
                out.append(_edges_case(edge_head, "numpy", their_edges.tolist(), edges))
                mismatches, cells = differences(theirs.tolist(), counts)
                out.append(
                    agreed(count_head, "numpy", mismatches, cells, "the exact counts")
                )
            out.append(missing_reason(count_head, "pandas", pandas))
    return out


# top


def _texts(values: Sequence, kind: str) -> dict:
    """Return each distinct value's text as DuckDB writes it (the tie rule)."""
    distinct = list({v for v in values if not _cases.is_missing(v)})
    if kind == "VARCHAR":
        return {v: v for v in distinct}
    con = duckdb.connect()
    found = _cases.table(con, "t", {"v": tuple(distinct)}, "DOUBLE")
    texts = found.project("CAST(v AS VARCHAR)").fetchall()
    return {v: t for v, (t,) in zip(distinct, texts, strict=True)}


def exact_top(values: Sequence, kind: str) -> list[tuple]:
    """Return the commonest values: (value, count, share), ties by text, NULL last."""
    counts = Counter(None if _cases.is_missing(v) else v for v in values)
    texts = _texts(values, kind)
    ordered = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0] is None, texts.get(item[0], "")),
    )
    return [(v, n, n / len(values)) for v, n in ordered[:K]]


def _read_value(text: str | None, kind: str) -> object:
    if text is None or kind == "VARCHAR":
        return text
    return float(text)


def top_cases() -> list[dict]:
    """Return each top's values, counts and shares against the exact ones."""
    out = []
    datasets = [(d, "DOUBLE") for d in numeric()] + [
        (d, "VARCHAR") for d in _cases.labels()
    ]
    for data, kind in datasets:
        head = _head(f"top, k={K}", data, kind, 0)
        rows = sq.explore.top(_table(data, kind), k=K).fetchall()
        got = [
            cell
            for _, text, n, share in rows
            for cell in (_read_value(text, kind), n, share)
        ]
        want = [cell for row in exact_top(data.values, kind) for cell in row]
        mismatches, cells = differences(got, want)
        out.append(
            agreed(head, "sqlearn", mismatches, cells, "collections.Counter, sorted")
        )
        series = (
            pd.Series(_cases.as_nan(data.values))
            if kind == "DOUBLE"
            else pd.Series(list(data.values), dtype=object)
        )
        theirs = {
            (None if _is_null(v) else v): int(n)
            for v, n in series.value_counts(dropna=False).items()
        }
        exact = Counter(None if _cases.is_missing(v) else v for v in data.values)
        keys = set(theirs) | set(exact)
        mismatches = sum(1 for key in keys if theirs.get(key) != exact.get(key))
        out.append(
            agreed(
                head,
                "pandas",
                mismatches,
                len(keys),
                "collections.Counter: every value's count, not the order of ties",
            )
        )
        out.append(
            missing_reason(
                head, "numpy", "numpy has no count of values by value with NULL"
            )
        )
    return out


# missing


def exact_missing(columns: dict[str, tuple]) -> list[tuple]:
    """Return the commonest patterns: (names missing, count, share)."""
    names = list(columns)
    rows = len(next(iter(columns.values())))
    flags = Counter(
        tuple(_cases.is_missing(columns[c][i]) for c in names) for i in range(rows)
    )
    ordered = sorted(flags.items(), key=lambda item: (-item[1], item[0]))
    return [
        ([c for c, gone in zip(names, f, strict=True) if gone], n, n / rows)
        for f, n in ordered[:K]
    ]


def _frame(columns: dict[str, tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            c: pd.Series(_cases.as_nan(v))
            if c != "city"
            else pd.Series(list(v), dtype=object)
            for c, v in columns.items()
        }
    )


def _kinds(columns: dict[str, tuple]) -> dict[str, str]:
    return {c: "VARCHAR" if c == "city" else "DOUBLE" for c in columns}


def missing_cases() -> list[dict]:
    """Return each dataset's patterns of missing values against the exact ones."""
    out = []
    for data in numeric():
        columns = companions(data)
        head = _head(f"missing, patterns={K}", data, "DOUBLE, VARCHAR", 0)
        rel = _cases.sqlearn_table(columns, _kinds(columns))
        got = [
            cell
            for m, n, share in sq.explore.missing(rel, patterns=K).fetchall()
            for cell in (list(m), n, share)
        ]
        want = [cell for row in exact_missing(columns) for cell in row]
        mismatches, cells = differences(got, want)
        out.append(
            agreed(head, "sqlearn", mismatches, cells, "collections.Counter, sorted")
        )
        names = list(columns)
        rows = len(data.values)
        exact = Counter(
            tuple(_cases.is_missing(columns[c][i]) for c in names) for i in range(rows)
        )
        theirs = (
            {
                tuple(bool(f) for f in k): int(n)
                for k, n in _frame(columns).isna().value_counts().items()
            }
            if rows
            else {}
        )
        keys = set(theirs) | set(exact)
        mismatches = sum(1 for key in keys if theirs.get(key) != exact.get(key))
        out.append(
            agreed(
                head,
                "pandas",
                mismatches,
                len(keys),
                "collections.Counter: every pattern's count, not the order of ties",
            )
        )
        out.append(missing_reason(head, "numpy", "numpy has no count of patterns"))
    return out


# correlations


def _pandas_corr(columns: dict[str, tuple], a: str, b: str, method: str) -> float:
    frame = pd.DataFrame({c: nan_series(columns[c]) for c in (a, b)})
    return float(frame.corr(method=method).loc[a, b])  # type: ignore[arg-type]


def _numpy_corr(columns: dict[str, tuple], a: str, b: str) -> float | None:
    xs, ys = complete(columns[a], columns[b])
    if len(xs) < 2:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


def correlation_cases() -> list[dict]:
    """Return each pair's Pearson and Spearman correlation against the exact one."""
    out = []
    for data in numeric():
        columns = companions(data)
        numbers = {c: v for c, v in columns.items() if c != "city"}
        rel = _cases.sqlearn_table(numbers, "DOUBLE")
        names = list(numbers)
        for method in ("pearson", "spearman"):
            found = sq.explore.correlations(rel, method=method).fetchall()
            ours = {(a, b): (r, n) for a, b, r, n in found}
            for i, a in enumerate(names):
                for b in names[i + 1 :]:
                    formula = f"correlations, {method}: {a} ~ {b}"
                    head = _head(formula, data, "DOUBLE", BOUNDS[method])
                    r, n = ours.get((a, b), (math.nan, -1))
                    rows = len(complete(columns[a], columns[b])[0])
                    out.append(
                        agreed(
                            {**head, "formula": f"{formula}: rows"},
                            "sqlearn",
                            int(n != rows),
                            1,
                            "the exact count of complete rows",
                        )
                    )
                    answers: dict[str, Callable[[], object]] = {
                        "sqlearn": lambda r=r: r,
                        "pandas": lambda c=columns, a=a, b=b, m=method: _pandas_corr(
                            c, a, b, m
                        ),
                    }
                    if method == "pearson":
                        answers["numpy"] = lambda c=columns, a=a, b=b: _numpy_corr(
                            c, a, b
                        )
                    out += measured(
                        head,
                        exact_correlation(columns[a], columns[b], method),
                        answers,
                        scale=1.0,
                    )
                    if method == "spearman":
                        out.append(
                            missing_reason(
                                head, "numpy", "numpy has no rank correlation"
                            )
                        )
    return out


def cases() -> list[dict]:
    """Return every exploration function's cases."""
    return [
        *profile_cases(),
        *histogram_cases(),
        *top_cases(),
        *missing_cases(),
        *correlation_cases(),
    ]
