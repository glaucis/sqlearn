"""Validate the feature selectors against exact arithmetic.

The canonical values are computed in pure Python from the doubles' exact
values (ADR 0016), every one a `Fraction`:

- ``variances_``: each column's population variance over its present
  values; at ``threshold=0`` the smaller of it and the column's range
  (largest less least value), as scikit-learn's ``VarianceThreshold``
  takes, the variance alone where a value is missing.
- ``f_classif``: scikit-learn's ``f_oneway``, the between-class over the
  within-class mean square, from the exact per-class sums.
- ``f_regression``: ``cov² (n - 2) / (var(x) var(y) - cov²)``, the F of the
  correlation, from the exact sums; 0 where a column or the target is
  constant and at two rows (``force_finite``).
- ``chi2``: the observed per-class sums of the column against the
  expected ones (each class's share of the column's total).

NaN where the exact answer is 0 / 0 (``f_classif`` of a constant column,
``chi2`` of a column of zeros, either with one class): such a score is
compared as a value, NaN or not, and ranks lowest. Under ``f_regression``
an exactly linear column (``linear``: 2y, exact in doubles) has an infinite
F, which ``force_finite`` ranks as the largest double, and a column linear
but for a rounding per row (``nearly linear``: 2y + 1) an exact F of 3.7e34,
beyond what doubles of the learned variances resolve: neither score is
measured in doubles; which columns are kept is compared instead (spec
§4.4). They are in two datasets, since beside each other both score the
largest double and tie.

The kept columns (``columns_out_``) are compared exactly (no rounding) with
the columns the selection rule keeps from the exact scores: scikit-learn's
``SelectKBest`` (a stable sort, so among equal scores the later column) and
``SelectPercentile`` (above numpy's linear percentile, then the earliest of
the columns equal to it), a NaN score as the lowest double. scikit-learn's
own kept columns are compared with the same exact ones.

Beside sqlearn: DuckDB alone (hand-written SQL: per-class ``fsum`` of the
column and its square, not shifted; ``covar_pop`` and ``var_pop``;
``var_pop``), at DuckDB's threads and at one thread, numpy (per-class means
about the grand mean, two passes; ``corrcoef``; ``nanvar``), and
scikit-learn 1.9.1. A missing (NULL, NaN) or infinite value in a scored
column, a missing target value, and a negative value for ``chi2`` have no
answer: sqlearn must refuse them, as must it refuse a setting that leaves
no column at all (spec §4.2). ``variance`` ignores missing values, as
scikit-learn's ``nanvar`` does, and is measured on ``null`` and ``nan``.

Anomalies expected of the references, by design rather than defect:

- The exact score (spec §4.4): on ``far from zero`` (columns at 1e6 plus
  noise) scikit-learn's ``f_oneway`` and DuckDB alone sum the column and its
  square unshifted, so the sums of squares are differences of terms near
  1e15: scikit-learn's ``f_classif`` lands 14% off on ``far`` and 0.9% on
  ``far signal``, DuckDB alone 4.7%, numpy's two passes 1e-9 relative (each
  class mean carries the offset's rounding); ``chi2``'s observed less
  expected sums cancel the same way in every reference (6e-10 to 6e-9
  relative). On ``far from zero, numeric`` scikit-learn's ``f_regression``
  is 0.15% off. sqlearn sums the column less its minimum, combines the sums
  exactly, and passes there; the kept columns agree.
- The exact score again, on ``nearly linear`` (a column 2y + 1, rounded per
  row, exact F 3.7e34): scikit-learn's r² rounds above 1, its F is negative
  (-6.5e16) and the column ranks lowest, so scikit-learn keeps other
  columns at every setting but ``k="all"``; sqlearn keeps it (spec §4.4).
- ``constant``: the column of 0.1's exact ``f_classif`` is 0 / 0, NaN, and
  ranks lowest; scikit-learn's sums leave a zero (-0.0 in spec §4.4, 0.0
  here), as do numpy's and DuckDB alone's, so scikit-learn's ``best, k=3``
  keeps it over the column of zeros (NaN in both), where the exact rule
  keeps the later of the two tied lowest. Its ``f_regression`` (exactly 0: the column is
  constant) is 1.7e-19 in scikit-learn, whose centred column is a
  rounding off 0, so ``best, k=3`` keeps it over the column of zeros there
  too; its ``chi2`` (exactly 0) is 2.6e-29 in scikit-learn; its
  variance (exactly 0) is a rounding above 0 in numpy and scikit-learn
  (``nanvar`` subtracts a mean of 0.1's that is not exact), which
  ``threshold=0``'s range rescues and ``threshold=0.5`` does not show.
- DuckDB alone has no ``force_finite`` rule: ``f_regression`` of a constant
  column, a constant target and two rows is NaN where the answer is 0.
  With one class, numpy's and DuckDB alone's ``chi2`` sum over the one
  class and score 0, where scikit-learn's label binarizer adds an empty
  second class (0 / 0, NaN), as sqlearn follows.
- Sums of 1,000 rows and more. DuckDB alone's ``var_pop`` is a running
  update, not compensated (12 doubles on 1,000 rows, 181 on 100,000, 78,281
  at 1e6). scikit-learn's ``variances_`` is ``nanvar`` along axis 0 of the
  whole table, which numpy sums row by row rather than pairwise (28 doubles
  on 1,000 rows, 1,618 on 100,000; numpy's ``nanvar`` of one column passes),
  and its ``f_classif`` and ``chi2`` sum unshifted products of the table
  (1,519 and 3,546 doubles on ``large``).
"""

import functools
import math
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import duckdb
import numpy as np
from sklearn import feature_selection as skf

import sqlearn as sq
from validation import _cases

SCORES = ("f_classif", "f_regression", "chi2")
THRESHOLDS = (0.0, 0.5)
KS: tuple[int | str, ...] = (1, 2, 3, "all")
PERCENTILES = (25, 50, 75)

# Set from the first measurement (ADR 0016), in doubles between the answer and
# the exact value. Loosening a bound needs a written reason here, never a
# quiet edit. First measured 2026-11-19 (in brackets, the most measured over
# every dataset but those in WIDE), each with about a tenth to spare:
# - variance [1]: two passes, the compensated mean then the compensated mean
#   of the squared deviations (``sqlearn.agg.var``, issue #42).
# - f_classif [287, ``medium``'s noise column]: compensated sums (fsum) of
#   the column less its minimum, per class, combined exactly. Each sum is
#   within a rounding, but the between-class sum of squares is a difference
#   of two terms (the classes' squared sums over their counts, and the
#   squared total over n) that nearly agree where the class means nearly
#   agree, so the rounding of the sums is amplified as F falls: 287 at F
#   0.0069 (``medium``'s noise), 215 at F 1.6e-5 (``small``'s signal), where
#   numpy's two passes about the means measure 138 and scikit-learn 133. At
#   F above 1, 21 or less.
# - f_regression [172, ``numbers, large``]: DuckDB's ``covar_pop`` and
#   ``var_pop`` (a running update about the mean, not compensated, spec §6),
#   then ``cov² (n - 2) / (var(x) var(y) - cov²)`` combined exactly from the
#   three doubles; DuckDB alone, which finishes the same three in doubles,
#   measures the same.
# - chi2 [17, ``small``]: compensated per-class sums combined exactly; the
#   difference of the observed and the expected sums cancels the same way
#   on columns that do not depend on the class.
BOUNDS = {
    "variance": 2,
    "f_classif": 320,
    "f_regression": 192,
    "chi2": 20,
}
WIDE = {
    # Columns at 1e6 plus noise: ``covar_pop`` and ``var_pop``'s running
    # update keeps the mean but not every digit of each deviation from it,
    # and the covariance, small beside the offset, carries a relative error
    # near 1e-9: measured 10,093,532 doubles (1.5e-9 relative) on ``far``
    # and 1,292,258 on ``far signal``, 2026-11-19, against scikit-learn's
    # 0.15% (spec §4.4). A step's learn sees only its columns, so it cannot
    # shift by the mean first: the limit of the aggregate, recorded and
    # named, as r2's in the regression runner.
    ("f_regression", "far from zero, numeric"): 11_200_000,
}
"""Bounds wider than `BOUNDS` for one score on one dataset, each at its
measurement and for the reason above `BOUNDS`."""

Exact = Fraction | float
"""An exact score: a `Fraction`, or a float only for NaN (0 / 0) or infinity."""


@dataclass(frozen=True)
class Problem:
    """A table of numeric columns and a target, and the scores run on it.

    ``every`` True: a refusal dataset, where every column is scored (chi2
    too, on negative values) and sqlearn must refuse what has no answer.
    ``unmeasured``: columns whose score is recorded, not measured (a
    column linear but for one rounding per row, spec §4.4).
    """

    name: str
    note: str
    columns: dict[str, tuple]
    target: tuple
    kind: str
    scores: tuple[str, ...]
    variance: bool = True
    every: bool = False
    unmeasured: tuple[str, ...] = ()

    @property
    def rows(self) -> int:
        """Return the number of rows."""
        return len(self.target)

    def scored(self, score: str) -> list[str]:
        """Return the columns `score` is run on: chi2 takes no negative value."""
        if score != "chi2" or self.every:
            return list(self.columns)
        return [c for c, v in self.columns.items() if all(x >= 0 for x in _present(v))]


def _present(values: tuple) -> list[float]:
    return [v for v in values if not _cases.is_missing(v)]


def _floats(values: np.ndarray) -> tuple:
    return tuple(float(v) for v in values)


def _classes(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    """Return `n` labels from 0 to `k` - 1, each class about as often, shuffled."""
    return rng.permutation(np.arange(n) % k)


def _problems() -> list[Problem]:
    """Return each dataset: its columns, its target and the scores run on it."""
    rng = np.random.default_rng(_cases.SEED)
    classes = ("f_classif", "chi2")

    def labelled(n: int, k: int) -> tuple[dict[str, tuple], tuple]:
        y = _classes(rng, n, k)
        return {
            "signal": _floats(rng.normal(size=n) + y),
            "noise": _floats(rng.normal(size=n)),
            "uniform": _floats(rng.uniform(size=n) + 0.5 * y),
            "counts": _floats(rng.poisson(2.0 + y, size=n)),
            "weak": _floats(rng.normal(5.0, 2.0, size=n) + 0.2 * y),
        }, tuple(int(v) for v in y)

    def numeric(n: int) -> tuple[dict[str, tuple], tuple]:
        y = rng.normal(size=n)
        return {
            "signal": _floats(y + rng.normal(size=n)),
            "noise": _floats(rng.normal(size=n)),
            "weak": _floats(0.1 * y + rng.normal(size=n)),
            "counts": _floats(rng.poisson(3.0, size=n)),
        }, _floats(y)

    out = []
    for name, n, k in (("small", 10, 2), ("medium", 1_000, 3), ("large", 100_000, 3)):
        cols, y = labelled(n, k)
        out.append(Problem(name, f"{n:,} rows, {k} classes", cols, y, "BIGINT",
                           classes))  # fmt: skip
    for name, n in (("numbers, small", 10), ("numbers, medium", 1_000),
                    ("numbers, large", 100_000)):  # fmt: skip
        cols, y = numeric(n)
        out.append(Problem(name, f"{n:,} rows, a numeric target", cols, y, "DOUBLE",
                           ("f_regression",)))  # fmt: skip
    cols, y = labelled(1_000, 3)
    words = tuple(_cases.WORDS[v] for v in y)
    out.append(Problem("text classes", "1,000 rows, 3 classes named by text", cols,
                       words, "VARCHAR", classes, variance=False))  # fmt: skip
    y = _classes(rng, 1_000, 3)
    far = {
        "far": _floats(1e6 + rng.normal(size=1_000)),
        "far signal": _floats(1e6 + rng.normal(size=1_000) + 0.1 * y),
        "near": _floats(rng.normal(size=1_000) + 0.1 * y),
    }
    out.append(Problem("far from zero", "1,000 rows, columns at 1e6 plus noise",
                       far, tuple(int(v) for v in y), "BIGINT",
                       classes))  # fmt: skip
    t = rng.normal(size=1_000)
    far = {
        "far": _floats(1e6 + rng.normal(size=1_000)),
        "far signal": _floats(1e6 + rng.normal(size=1_000) + 0.05 * t),
        "near": _floats(rng.normal(size=1_000) + 0.05 * t),
    }
    out.append(Problem("far from zero, numeric", "1,000 rows, columns at 1e6",
                       far, _floats(t), "DOUBLE", ("f_regression",),
                       variance=False))  # fmt: skip
    # One linear column a dataset: an exactly linear column (2y, exact in
    # doubles, r² exactly 1) and one linear but for a rounding per row
    # (2y + 1) both score the largest double, so beside each other they tie.
    for name, line, note, unmeasured in (
        ("linear", lambda t: 2 * t, "a column 2y: r² exactly 1", ()),
        ("nearly linear", lambda t: 2 * t + 1, "a column 2y + 1, rounded per row",
         ("linear",)),
    ):  # fmt: skip
        t = rng.normal(size=60)
        linear = {
            "noise": _floats(rng.normal(size=60)),
            "linear": _floats(line(t)),
            "signal": _floats(t + rng.normal(size=60)),
        }
        out.append(Problem(name, f"60 rows, {note}", linear, _floats(t), "DOUBLE",
                           ("f_regression",), variance=False,
                           unmeasured=unmeasured))  # fmt: skip
    y = _classes(rng, 100, 2)
    signal = _floats(rng.uniform(size=100) + 0.3 * y)
    ties = {
        "noise": _floats(rng.uniform(size=100)),
        "signal": signal,
        "twin": signal,
        "strong": _floats(rng.uniform(size=100) + y),
    }
    out.append(Problem("ties", "100 rows, a column and its twin", ties,
                       tuple(int(v) for v in y),
                       "BIGINT", SCORES, variance=False))  # fmt: skip
    cols, y = labelled(100, 2)
    constant = {
        "flat": (0.1,) * 100,
        "zero": (0.0,) * 100,
        "signal": cols["signal"],
        "counts": cols["counts"],
    }
    out.append(Problem("constant", "100 rows, columns of 0.1 and of 0", constant,
                       y, "BIGINT", SCORES))  # fmt: skip
    cols, _ = labelled(20, 2)
    out.append(Problem("one class", "20 rows, every target 0", cols, (0,) * 20,
                       "BIGINT", classes, variance=False))  # fmt: skip
    out.append(Problem("two rows", "2 rows: no degree of freedom",
                       {"a": (1.0, 2.0), "b": (3.0, 3.5)}, (0.5, 2.5), "DOUBLE",
                       ("f_regression",), variance=False))  # fmt: skip
    cols, _ = numeric(100)
    out.append(Problem("constant target", "100 rows, every target 1.5", cols,
                       (1.5,) * 100, "DOUBLE", ("f_regression",),
                       variance=False))  # fmt: skip
    cols, y = labelled(1_000, 2)
    holed = dict(cols, signal=tuple(_cases._gaps(rng, list(cols["signal"]), None)))
    out.append(Problem("null", "a tenth of one column NULL", holed, y, "BIGINT",
                       SCORES, every=True))  # fmt: skip
    holed = dict(cols, signal=tuple(_cases._gaps(rng, list(cols["signal"]), math.nan)))
    out.append(Problem("nan", "a tenth of one column NaN", holed, y, "BIGINT",
                       SCORES, every=True))  # fmt: skip
    counts = list(cols["counts"])
    counts[7] = math.inf
    out.append(Problem("infinity", "one value infinite",
                       dict(cols, counts=tuple(counts)), y, "BIGINT", SCORES,
                       variance=False, every=True))  # fmt: skip
    gaps = tuple(None if i == 3 else v for i, v in enumerate(y))
    out.append(Problem("missing target", "one target NULL", cols, gaps, "BIGINT",
                       SCORES, variance=False, every=True))  # fmt: skip
    out.append(Problem("negative", "values below 0 (chi2 refuses them)", cols, y,
                       "BIGINT", ("chi2",), variance=False, every=True))  # fmt: skip
    return out


# The exact scores.


def _by_class(x: tuple, y: tuple) -> dict[object, list[Fraction]]:
    groups: dict[object, list[Fraction]] = {}
    for v, label in zip(x, y, strict=True):
        groups.setdefault(label, []).append(Fraction(v))
    return groups


def _ratio(a: Fraction, b: Fraction) -> Exact:
    if b == 0:
        return math.nan if a == 0 else math.copysign(math.inf, a)
    return a / b


def _exact_f_classif(x: tuple, y: tuple) -> Exact:
    groups = _by_class(x, y)
    n, k = len(x), len(groups)
    if k == 1 or n == k:
        return math.nan  # 0 / 0: no degree of freedom
    sums = [(len(g), sum(g, Fraction(0)), sum((v * v for v in g), Fraction(0)))
            for g in groups.values()]  # fmt: skip
    total = sum((s for _, s, _ in sums), Fraction(0))
    between = sum((s * s / c for c, s, _ in sums), Fraction(0)) - total**2 / n
    within = sum((ss - s * s / c for c, s, ss in sums), Fraction(0))
    return _ratio(between / (k - 1), within / (n - k))


def _exact_chi2(x: tuple, y: tuple) -> Exact:
    groups = _by_class(x, y)
    if len(groups) == 1:
        return math.nan  # scikit-learn's second class holds nothing: 0 / 0
    n = len(x)
    observed = [(len(g), sum(g, Fraction(0))) for g in groups.values()]
    total = sum((o for _, o in observed), Fraction(0))
    if total == 0:
        return math.nan
    expected = [(o, Fraction(c, n) * total) for c, o in observed]
    return sum(((o - e) ** 2 / e for o, e in expected), Fraction(0))


def _exact_f_regression(x: tuple, y: tuple) -> Exact:
    n = len(x)
    fx = [Fraction(v) for v in x]
    fy = [Fraction(v) for v in y]
    sx, sy = sum(fx, Fraction(0)), sum(fy, Fraction(0))
    covariance = sum((a * b for a, b in zip(fx, fy, strict=True)), Fraction(0)) / n
    covariance -= sx * sy / n**2
    vx = sum((a * a for a in fx), Fraction(0)) / n - (sx / n) ** 2
    vy = sum((b * b for b in fy), Fraction(0)) / n - (sy / n) ** 2
    if vx * vy == 0:
        return Fraction(0)  # r is NaN, taken as 0 (force_finite)
    rest = vx * vy - covariance**2
    if rest == 0:
        return Fraction(0) if n == 2 else math.inf  # r² = 1
    return covariance**2 * (n - 2) / rest


EXACT: dict[str, Callable[[tuple, tuple], Exact]] = {
    "f_classif": _exact_f_classif,
    "f_regression": _exact_f_regression,
    "chi2": _exact_chi2,
}


def _exact_variance(values: tuple, threshold: float) -> Fraction:
    """Return the variance as scikit-learn's ``variances_`` holds it, exactly."""
    present = _present(values)
    variance = _cases.exact_variance(present)
    if threshold != 0 or len(present) < len(values):
        return variance
    return min(variance, Fraction(max(present)) - Fraction(min(present)))


# The selection rules, applied to exact scores.

LARGEST = Fraction(sys.float_info.max)
LOWEST = -LARGEST
"""Where a NaN score ranks: the lowest double, as scikit-learn's ``_clean_nans``."""


def _key(score: Exact) -> Exact:
    return LOWEST if isinstance(score, float) and math.isnan(score) else score


def _best(names: list[str], scores: list[Exact], k: int | str) -> list[str]:
    """Return the names SelectKBest keeps: the last `k` of a stable sort."""
    if k == "all":
        return names
    order = sorted(range(len(names)), key=lambda i: _key(scores[i]))
    kept = set(order[len(order) - int(k) :]) if k else set()
    return [c for i, c in enumerate(names) if i in kept]


def _lerp(a: Exact, b: Exact, t: float) -> Exact:
    if t == 0 or a == b:
        return a
    return a + (b - a) * Fraction(t)


def _percentile(names: list[str], scores: list[Exact], p: float) -> list[str]:
    """Return the names SelectPercentile keeps, as scikit-learn's mask.

    The threshold is numpy's linear ``percentile(scores, 100 - p)``, its
    position computed in doubles as numpy computes it; the scores are exact.
    """
    if p == 100:
        return names
    if p == 0:
        return []
    keys = [_key(s) for s in scores]
    ordered = sorted(keys)
    n = len(keys)
    q = (100 - p) / 100
    virtual = n * q + (1 - q) - 1
    below = min(max(math.floor(virtual), 0), n - 1)
    above = min(below + 1, n - 1)
    threshold = _lerp(ordered[below], ordered[above], virtual - below)
    mask = [s > threshold for s in keys]
    ties = [i for i, s in enumerate(keys) if s == threshold]
    for i in ties[: int(n * p / 100) - sum(mask)]:
        mask[i] = True
    return [c for c, m in zip(names, mask, strict=True) if m]


# The references.


def _np_f_classif(x: np.ndarray, y: np.ndarray) -> float:
    """Return the ANOVA F in two passes: class means about the grand mean."""
    labels = np.unique(y)
    n, k = len(x), len(labels)
    grand = x.mean()
    between = sum(np.sum(y == c) * (x[y == c].mean() - grand) ** 2 for c in labels)
    within = sum(np.sum((x[y == c] - x[y == c].mean()) ** 2) for c in labels)
    with np.errstate(all="ignore"):
        return float(np.float64(between / (k - 1)) / np.float64(within / (n - k)))


def _np_f_regression(x: np.ndarray, y: np.ndarray) -> float:
    with np.errstate(all="ignore"):
        r = np.corrcoef(x, y)[0, 1]
        f = r * r / (1 - r * r) * (len(x) - 2)
    if np.isnan(f):
        return 0.0
    return float(sys.float_info.max) if np.isinf(f) else float(f)


def _np_chi2(x: np.ndarray, y: np.ndarray) -> float:
    labels = np.unique(y)
    observed = np.array([x[y == c].sum() for c in labels])
    expected = np.array([np.mean(y == c) for c in labels]) * x.sum()
    with np.errstate(all="ignore"):
        return float(np.sum((observed - expected) ** 2 / expected))


NUMPY = {"f_classif": _np_f_classif, "f_regression": _np_f_regression,
         "chi2": _np_chi2}  # fmt: skip

SQL = {
    "f_classif": (
        "WITH g AS (SELECT y, count(*)::DOUBLE AS n, fsum(x) AS s, "
        "fsum(x * x) AS ss FROM data GROUP BY y), "
        "t AS (SELECT sum(n) AS n, count(*) AS k, fsum(s) AS s, fsum(ss) AS ss, "
        "fsum(s * s / n) AS b FROM g) "
        "SELECT ((b - s * s / n) / (k - 1)) / ((ss - b) / (n - k)) FROM t"
    ),
    "f_regression": (
        "SELECT covar_pop(x, y) ** 2 * (count(*) - 2) / "
        "(var_pop(x) * var_pop(y) - covar_pop(x, y) ** 2) FROM data"
    ),
    "chi2": (
        "WITH g AS (SELECT y, count(*)::DOUBLE AS n, fsum(x) AS o FROM data "
        "GROUP BY y), t AS (SELECT sum(n) AS n, fsum(o) AS o FROM g) "
        "SELECT fsum((g.o - g.n * t.o / t.n) ** 2 / (g.n * t.o / t.n)) FROM g, t"
    ),
}
"""Each score in DuckDB alone, over table ``data(x, y)``: the plain sums."""

SKLEARN = {"f_classif": skf.f_classif, "f_regression": skf.f_regression,
           "chi2": skf.chi2}  # fmt: skip


def _duckdb(sql: str, columns: dict[str, tuple], kind: str, threads: int | None):
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    kinds = dict.fromkeys(columns, "DOUBLE") | {"y": kind}
    _cases.table(con, "data", columns, kinds)
    return con.sql(sql).fetchall()[0][0]


def _frame(problem: Problem, names: list[str]) -> np.ndarray:
    return np.column_stack([_cases.as_nan(problem.columns[c]) for c in names])


def _labels(problem: Problem) -> np.ndarray:
    if problem.kind == "VARCHAR":
        return np.array(problem.target, dtype=object)
    return _cases.as_nan(problem.target)


@functools.cache
def _relation(name: str) -> duckdb.DuckDBPyRelation:
    problem = PROBLEMS[name]
    kinds = dict.fromkeys(problem.columns, "DOUBLE") | {"y": problem.kind}
    return _cases.sqlearn_table(problem.columns | {"y": problem.target}, kinds)


def _learn(problem: Problem, step: sq.Step) -> sq.Pipeline:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        uses_target = getattr(step, "uses_target", False)
        rel = _relation(problem.name)
        if not uses_target:
            rel = rel.project(", ".join(f'"{c}"' for c in problem.columns))
        return sq.Pipeline([step]).learn(rel, target="y" if uses_target else None)


def _sqlearn_scores(problem: Problem, score: str) -> dict[str, float]:
    names = problem.scored(score)
    step = sq.select.best(k="all", score=score, cols=names)
    return _learn(problem, step)["best"].scores_


# The cases.


def _value_case(head: dict, reference: str, value: float, exact: float) -> dict:
    """Record an answer whose exact value is NaN: it must be NaN too."""
    same = (math.isnan(value) and math.isnan(exact)) or value == exact
    if reference == "sqlearn":
        result = "pass" if same else "fail"
    else:
        result = "pass" if same else "anomaly"
    note = f"exact value {exact!r} (0 / 0); returned {value!r}"
    out = _cases.skipped(reference=reference, note=note, result=result, **head)
    out["value"] = value
    return out


def _score_cases(problem: Problem, score: str) -> list[dict]:
    """Return each column's score against its exact value, for each reference."""
    out = []
    names = problem.scored(score)
    y = problem.target
    answerable = all(
        not _cases.is_missing(v) and math.isfinite(v)
        for c in names
        for v in problem.columns[c]
    ) and not any(_cases.is_missing(v) for v in y)
    if score == "chi2":
        answerable = answerable and all(
            v >= 0 for c in names for v in problem.columns[c]
        )
    for column in names:
        x = problem.columns[column]
        exact = EXACT[score](x, y) if answerable else None
        head = {
            "step": score,
            "formula": f"{score} of {column}",
            "dataset": problem.name,
            "rows": problem.rows,
            "type": "DOUBLE",
            "bound": WIDE.get((score, problem.name), BOUNDS[score]),
        }
        index = names.index(column)

        def ours(p=problem, s=score, c=column) -> float:
            return _sqlearn_scores(p, s)[c]

        def theirs(p=problem, s=score, i=index, ns=tuple(names)) -> float:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                scores = SKLEARN[s](_frame(p, list(ns)), _labels(p))[0]
            return float(scores[i])

        def numpy(p=problem, s=score, c=column) -> float:
            return NUMPY[s](_cases.as_nan(p.columns[c]), _labels(p))

        sql = SQL[score]
        answers = {
            "sqlearn": ours,
            "duckdb": lambda q=sql, c=column: _duckdb(
                q, {"x": problem.columns[c], "y": y}, problem.kind, None
            ),
            "duckdb, 1 thread": lambda q=sql, c=column: _duckdb(
                q, {"x": problem.columns[c], "y": y}, problem.kind, 1
            ),
            "numpy": numpy,
            "scikit-learn": theirs,
        }
        if isinstance(exact, float) or column in problem.unmeasured:
            out += _special(head, exact, answers)  # type: ignore[arg-type]
            continue
        out += _cases.measure_all(
            data=_cases.Dataset(problem.name, column, x, problem.note),
            exact=exact,
            answers=answers,
            **{k: head[k] for k in ("step", "formula", "type", "bound")},
        )
    return out


def _special(head: dict, exact: Exact, answers: dict) -> list[dict]:
    """Record the answers where the exact value is NaN or infinite, or unmeasured.

    An unmeasured score (`Problem.unmeasured`) is finite but beyond what
    doubles of the learned variances resolve: r² within rounding of 1.
    """
    out = []
    for reference, answer in answers.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = answer()
        except Exception as exc:  # noqa: BLE001  (each library's own refusal is recorded)
            result = "fail" if reference == "sqlearn" else "skipped"
            out.append(_cases.skipped(reference=reference, result=result,
                                      note=_cases.first_line(exc), **head))  # fmt: skip
            continue
        if raw is None:
            result = "fail" if reference == "sqlearn" else "skipped"
            out.append(_cases.skipped(reference=reference, result=result,
                                      note="returned NULL", **head))  # fmt: skip
            continue
        value = float(raw)
        if isinstance(exact, Fraction) or math.isinf(exact):
            which = (
                "infinite (r² is 1)"
                if isinstance(exact, float)
                else f"{float(exact):.6g}, r² within rounding of 1"
            )
            note = (
                f"exact F {which}, not measured in doubles; returned "
                f"{value!r}; the kept columns are compared instead"
            )
            out.append(_cases.skipped(reference=reference, note=note, **head))
            continue
        out.append(_value_case(head, reference, value, exact))
    return out


def _kept_case(
    head: dict, reference: str, got: list[str], want: list[str], cells: int
) -> dict:
    """Compare kept columns with the exact rule's: by name and order."""
    mismatches = 0 if got == want else len(set(got) ^ set(want)) or 1
    out = _cases.exact_case(mismatches=mismatches, cells=cells,
                            compared_with="the rule on the exact scores",
                            note=f"kept {got}; the exact scores keep {want}",
                            **head)  # fmt: skip
    if reference != "sqlearn":
        out["reference"] = reference
        out["result"] = "pass" if mismatches == 0 else "anomaly"
    return out


def _refused(head: dict, learn: Callable[[], object]) -> dict:
    """Record a setting sqlearn must refuse: it must raise its own error."""
    try:
        learn()
    except sq.errors.SqlearnError as exc:
        return _cases.skipped(reference="sqlearn", result="pass", bound=0,
                              note="refused, as specified: " + _cases.first_line(exc),
                              **head)  # fmt: skip
    return _cases.skipped(reference="sqlearn", result="fail", bound=0,
                          note="no column would remain, yet sqlearn learned",
                          **head)  # fmt: skip


def _kept_cases(problem: Problem, score: str) -> list[dict]:
    """Return the kept columns of `best` and `percentile` against the exact rule."""
    names = problem.scored(score)
    if problem.every:
        return []
    exact = [EXACT[score](problem.columns[c], problem.target) for c in names]
    if score == "f_regression":  # force_finite: an infinite F is the largest double
        exact = [LARGEST if s == math.inf else s for s in exact]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs = SKLEARN[score](_frame(problem, names), _labels(problem))[0]
    out = []
    head = {"dataset": problem.name, "rows": problem.rows, "type": "DOUBLE"}
    settings = [("best", f"k={k!r}", k) for k in KS if k == "all" or k < len(names)]
    settings += [("percentile", f"percentile={p!r}", p) for p in PERCENTILES]
    for kind, setting, value in settings:
        if kind == "best":
            step = sq.select.best(k=value, score=score, cols=names)
            want = _best(names, exact, value)
            sk = skf.SelectKBest(lambda *_, s=theirs: s, k=value)
        else:
            step = sq.select.percentile(percentile=value, score=score, cols=names)
            want = _percentile(names, exact, value)
            sk = skf.SelectPercentile(lambda *_, s=theirs: s, percentile=value)
        formula = {"step": kind, "formula": f"{kind}, {setting}, score={score}"}
        if not want and len(names) == len(problem.columns):
            out.append(_refused(formula | head, lambda st=step: _learn(problem, st)))
            continue
        # The columns it does not choose pass beside it, unchanged.
        got = [c for c in _learn(problem, step).columns_out_ if c in names]
        sk.fit(_frame(problem, names), _labels(problem))
        sk_kept = [c for c, m in zip(names, sk.get_support(), strict=True) if m]
        for reference, kept in (("sqlearn", got), ("scikit-learn", sk_kept)):
            out.append(_kept_case(formula | head, reference, kept, want, len(names)))
    return out


def _variance_cases(problem: Problem) -> list[dict]:
    """Return each column's learned variance and the kept columns, per threshold."""
    out = []
    names = list(problem.columns)
    head = {"dataset": problem.name, "rows": problem.rows, "type": "DOUBLE"}
    for threshold in THRESHOLDS:
        pipe = _learn(problem, sq.select.variance(threshold=threshold))
        learned = pipe["variance"].variances_
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sk = skf.VarianceThreshold(threshold).fit(_frame(problem, names))
        formula = f"variance, threshold={threshold!r}"
        exact = {c: _exact_variance(problem.columns[c], threshold) for c in names}
        for i, column in enumerate(names):
            values = problem.columns[column]
            present = tuple(_present(values))
            whole = len(present) == len(values)
            sql = (
                "SELECT least(var_pop(x), max(x) - min(x)) FROM data"
                if threshold == 0 and whole
                else "SELECT var_pop(x) FROM data"
            )

            def np_variance(v=values, ranged=threshold == 0 and whole) -> float:
                a = _cases.as_nan(v)
                variance = float(np.nanvar(a))
                return min(variance, float(np.ptp(a))) if ranged else variance

            answers = {
                "sqlearn": lambda c=column, got=learned: got[c],
                "duckdb": lambda q=sql, v=present: _duckdb(q, {"x": v}, "DOUBLE", None),
                "duckdb, 1 thread": lambda q=sql, v=present: _duckdb(
                    q, {"x": v}, "DOUBLE", 1
                ),
                "numpy": np_variance,
                "scikit-learn": lambda i=i, sk=sk: float(sk.variances_[i]),
            }
            out += _cases.measure_all(
                step="variance",
                formula=f"{formula} of {column}",
                data=_cases.Dataset(problem.name, column, values, problem.note),
                type="DOUBLE",
                exact=exact[column],
                bound=WIDE.get(("variance", problem.name), BOUNDS["variance"]),
                answers=answers,
            )
        want = [c for c in names if exact[c] > Fraction(threshold)]
        sk_kept = [c for c, m in zip(names, sk.get_support(), strict=True) if m]
        step = {"step": "variance", "formula": formula}
        for reference, kept in (
            ("sqlearn", pipe.columns_out_),
            ("scikit-learn", sk_kept),
        ):
            out.append(_kept_case(step | head, reference, kept, want, len(names)))
    return out


def _nothing_left_cases(problem: Problem) -> list[dict]:
    """Return the settings that leave no column: each must be refused."""
    head = {"dataset": problem.name, "rows": problem.rows, "type": "DOUBLE"}
    largest = max(float(_exact_variance(v, 1.0)) for v in problem.columns.values())
    settings = [
        ("best", "best, k=0", sq.select.best(k=0)),
        ("percentile", "percentile, percentile=0", sq.select.percentile(percentile=0)),
        ("variance", f"variance, threshold={2 * largest:.6g}",
         sq.select.variance(threshold=2 * largest)),
    ]  # fmt: skip
    return [
        _refused({"step": s, "formula": f"{f}: no column left"} | head,
                 lambda st=st: _learn(problem, st))
        for s, f, st in settings
    ]  # fmt: skip


PROBLEMS = {p.name: p for p in _problems()}


def cases() -> list[dict]:
    """Return the cases of the feature selectors: each dataset and reference."""
    out = []
    for problem in PROBLEMS.values():
        if problem.variance:
            out += _variance_cases(problem)
        for score in problem.scores:
            out += _score_cases(problem, score)
            out += _kept_cases(problem, score)
    out += _nothing_left_cases(PROBLEMS["small"])
    return out
