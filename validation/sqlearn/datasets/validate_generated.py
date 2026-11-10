"""Validate the generators: their values follow the distributions they promise.

A generator's values are sqlearn's own, never scikit-learn's numbers (ADR
0045), so the canonical value of each case is the promised distribution's: a
mean, a variance, a quantile, a centre, a spread, a class share. A sample of
1,000,000 rows from one fixed seed misses it by sampling error, so each bound
is five standard errors of the measured statistic: a correct generator passes
but for a chance of about one in 1.7 million per case, and a wrong
distribution (a shifted mean, a spread off by a percent) fails. The model's own identity
(``regression``'s target without noise) and the repeatability cases have no
sampling error: their bounds are rounding and 0.

Each case records ``value`` (measured), ``canonical`` (promised),
``abs_error`` and its bound ``bound_abs``; ``bound_ulps`` is None, as the
bound is not in ULPs.
"""

import math
from statistics import NormalDist

import numpy as np

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.datasets._random import random_columns
from validation import _cases

ROWS = 1_000_000
SEED = _cases.SEED
SIGMAS = 5
"""Each statistical bound is this many standard errors (see the docstring)."""

QUANTILES = (0.01, 0.1, 0.5, 0.9, 0.99)
CENTRES = ((0.0, 0.0), (5.0, 5.0), (-5.0, 5.0))
SPREADS = (0.5, 1.0, 2.0)
NOISE = 3.0
BIAS = 2.0
WEIGHTS = (0.6, 0.3, 0.1)
FLIP = 0.2
CITIES = ("Oslo", "Lima", "Kyoto", "Cairo")

# The target without noise is a sum of 5 products of size about 100 * 4 and
# a bias: rounding leaves it within a few 1e-13, and least squares in numpy
# recovers the coefficients within about as much. 1e-8 is far above both and
# far below any wrong coefficient's effect (at least 1e-3 on a sample of a
# million standard normals).
IDENTITY_BOUND = 1e-8


def _case(
    *,
    step: str,
    formula: str,
    rows: int,
    value: float,
    canonical: float,
    bound: float,
    note: str,
) -> dict:
    """Record a measurement against its promised value within `bound`."""
    out = _cases._head(
        step=step,
        formula=formula,
        dataset="generated",
        rows=rows,
        type="DOUBLE",
        reference="sqlearn",
        bound=None,
        note=note,
    )
    error = abs(value - canonical)
    out |= {
        "bound_abs": bound,
        "value": value,
        "canonical": canonical,
        "abs_error": error,
        "rel_error": error / abs(canonical) if canonical else None,
        "ulps": None,
        "result": "pass" if error <= bound else "fail",
    }
    return out


def _quantile_se(q: float, density: float) -> float:
    """Return the standard error of the sample `q` quantile: sqrt(q(1-q)/n)/f."""
    return math.sqrt(q * (1 - q) / ROWS) / density


def _random_cases() -> list[dict]:
    """The uniform's and the normal's mean, variance and quantiles."""
    sql = random_columns(SEED, ROWS, {"u": 0}, {"n": 1})
    data = connection().sql(sql).fetchnumpy()
    out = []
    standard = NormalDist()
    for name, values, mean, variance, fourth, quantile, density in (
        # Uniform on [0, 1): central fourth moment 1/80; density 1 everywhere.
        ("uniform", data["u"], 0.5, 1 / 12, 1 / 80, lambda q: q, lambda q: 1.0),
        # Standard normal: fourth moment 3.
        (
            "normal",
            data["n"],
            0.0,
            1.0,
            3.0,
            standard.inv_cdf,
            lambda q: standard.pdf(standard.inv_cdf(q)),
        ),
    ):
        step = f"datasets.random.{name}"
        out.append(
            _case(
                step=step,
                formula="mean",
                rows=ROWS,
                value=float(np.mean(values)),
                canonical=mean,
                bound=SIGMAS * math.sqrt(variance / ROWS),
                note="standard error sqrt(variance / n)",
            )
        )
        out.append(
            _case(
                step=step,
                formula="population variance",
                rows=ROWS,
                value=float(np.var(values)),
                canonical=variance,
                bound=SIGMAS * math.sqrt((fourth - variance**2) / ROWS),
                note="standard error sqrt((m4 - variance**2) / n)",
            )
        )
        for q in QUANTILES:
            out.append(
                _case(
                    step=step,
                    formula=f"quantile {q}",
                    rows=ROWS,
                    value=float(np.quantile(values, q)),
                    canonical=quantile(q),
                    bound=SIGMAS * _quantile_se(q, density(q)),
                    note="standard error sqrt(q(1 - q) / n) / density",
                )
            )
    return out


def _blobs_cases() -> list[dict]:
    """Blobs' share, mean and spread per centre, each of a spread of its own."""
    data = sq.datasets.blobs(
        rows=ROWS, centers=CENTRES, cluster_std=SPREADS, seed=SEED
    ).fetchnumpy()
    out = []
    p = 1 / len(CENTRES)
    for c, (centre, spread) in enumerate(zip(CENTRES, SPREADS, strict=True)):
        mine = data["target"] == c
        n = int(mine.sum())
        out.append(
            _case(
                step="datasets.blobs",
                formula=f"share of centre {c}",
                rows=ROWS,
                value=n / ROWS,
                canonical=p,
                bound=SIGMAS * math.sqrt(p * (1 - p) / ROWS),
                note="each row picks its centre uniformly; sqrt(p(1 - p) / n)",
            )
        )
        for j, at in enumerate(centre):
            values = data[f"x{j}"][mine]
            out.append(
                _case(
                    step="datasets.blobs",
                    formula=f"mean of x{j} round centre {c}",
                    rows=n,
                    value=float(np.mean(values)),
                    canonical=at,
                    bound=SIGMAS * spread / math.sqrt(n),
                    note="standard error spread / sqrt(rows of the centre)",
                )
            )
            out.append(
                _case(
                    step="datasets.blobs",
                    formula=f"spread of x{j} round centre {c}",
                    rows=n,
                    value=float(np.std(values)),
                    canonical=spread,
                    bound=SIGMAS * spread / math.sqrt(2 * n),
                    note="a normal's sample spread: spread / sqrt(2 n)",
                )
            )
    return out


def _fit(data: dict, n_features: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the least-squares coefficients (bias last) and the residuals."""
    x = np.column_stack(
        [data[f"x{j}"] for j in range(n_features)] + [np.ones(len(data["target"]))]
    )
    coef, *_ = np.linalg.lstsq(x, data["target"], rcond=None)
    return coef, data["target"] - x @ coef


def _regression_cases() -> list[dict]:
    """Regression's target is the linear model, and its noise spread `noise`."""
    out = []
    settings = {"rows": ROWS, "n_features": 10, "n_informative": 5, "bias": BIAS}
    data = sq.datasets.regression(**settings, seed=SEED).fetchnumpy()
    coef, residual = _fit(data, 10)
    out.append(
        _case(
            step="datasets.regression",
            formula="largest |target - (x @ coef + bias)|, noise=0",
            rows=ROWS,
            value=float(np.max(np.abs(residual))),
            canonical=0.0,
            bound=IDENTITY_BOUND,
            note=(
                f"coef by least squares; {int(np.sum(np.abs(coef[:10]) > 1e-6))} "
                f"of 10 non-zero, bias {float(coef[10])!r}; rounding only"
            ),
        )
    )
    noisy = sq.datasets.regression(**settings, noise=NOISE, seed=SEED).fetchnumpy()
    _, residual = _fit(noisy, 10)
    out.append(
        _case(
            step="datasets.regression",
            formula=f"spread of the residual, noise={NOISE}",
            rows=ROWS,
            value=float(np.std(residual)),
            canonical=NOISE,
            bound=SIGMAS * NOISE / math.sqrt(2 * ROWS),
            note="a normal's sample spread: noise / sqrt(2 n)",
        )
    )
    return out


def _classification_cases() -> list[dict]:
    """Classification's class shares follow `weights`; flip_y redraws its share.

    The same seed with and without flips gives the same rows but for the
    redrawn labels; a redrawn label lands on another class with probability
    ``(n_classes - 1) / n_classes``, so the labels differ in that share of
    ``flip_y``.
    """
    settings = {
        "rows": ROWS,
        "n_features": 5,
        "n_informative": 3,
        "n_redundant": 1,
        "n_classes": len(WEIGHTS),
        "weights": list(WEIGHTS),
        "seed": SEED,
    }
    kept = sq.datasets.classification(**settings, flip_y=0.0)
    kept = kept.project("target").fetchnumpy()["target"]
    flipped = sq.datasets.classification(**settings, flip_y=FLIP)
    flipped = flipped.project("target").fetchnumpy()["target"]
    out = []
    for c, weight in enumerate(WEIGHTS):
        out.append(
            _case(
                step="datasets.classification",
                formula=f"share of class {c}, flip_y=0",
                rows=ROWS,
                value=float(np.mean(kept == c)),
                canonical=weight,
                bound=SIGMAS * math.sqrt(weight * (1 - weight) / ROWS),
                note="each row picks its cluster by weight; sqrt(p(1 - p) / n)",
            )
        )
    changed = FLIP * (len(WEIGHTS) - 1) / len(WEIGHTS)
    out.append(
        _case(
            step="datasets.classification",
            formula=f"share of labels changed by flip_y={FLIP}",
            rows=ROWS,
            value=float(np.mean(kept != flipped)),
            canonical=changed,
            bound=SIGMAS * math.sqrt(changed * (1 - changed) / ROWS),
            note="flip_y * (n_classes - 1) / n_classes; sqrt(p(1 - p) / n)",
        )
    )
    return out


def _customers_cases() -> list[dict]:
    """Customers' missing shares and category shares are the promised ones.

    A share of ``n`` independent rows has the standard error
    ``sqrt(p(1 - p) / n)``.
    """
    shares = (
        ("age is NULL", "(age IS NULL)", 0.1),
        ("income is NULL", "(income IS NULL)", 0.05),
        ("plan is basic", "(plan = 'basic')", 0.5),
        ("plan is plus", "(plan = 'plus')", 0.3),
        ("plan is pro", "(plan = 'pro')", 0.2),
        *((f"city is {c}", f"(city = '{c}')", 0.25) for c in CITIES),
    )
    rel = sq.datasets.customers(rows=ROWS, seed=SEED)
    measured = rel.aggregate(
        ", ".join(f"avg({test}::DOUBLE)" for _, test, _ in shares)
    ).fetchall()[0]
    return [
        _case(
            step="datasets.customers",
            formula=f"share where {formula}",
            rows=ROWS,
            value=float(value),
            canonical=promised,
            bound=SIGMAS * math.sqrt(promised * (1 - promised) / ROWS),
            note="each value picked by its own uniform; sqrt(p(1 - p) / n)",
        )
        for (formula, _, promised), value in zip(shares, measured, strict=True)
    ]


def _repeat_cases() -> list[dict]:
    """The same seed gives the same rows on 1 and 8 threads, and in a slice."""
    con = connection()
    before = con.sql("SELECT current_setting('threads')").fetchall()[0][0]
    try:
        con.execute("SET threads = 1")
        one = sq.datasets.blobs(rows=ROWS, seed=SEED).fetchall()
        con.execute("SET threads = 8")
        eight = sq.datasets.blobs(rows=ROWS, seed=SEED).fetchall()
    finally:
        con.execute(f"SET threads = {before}")
    head = sq.datasets.blobs(rows=1_000, seed=SEED).fetchall()
    pairs = (
        ("1 thread against 8", one, eight),
        ("first 1,000 of 1,000,000 against 1,000 rows", one[:1_000], head),
    )
    out = []
    for formula, a, b in pairs:
        mismatches = sum(x != y for x, y in zip(a, b, strict=True))
        out.append(
            _cases.exact_case(
                step="datasets.blobs",
                formula=f"repeatable: {formula}",
                dataset="generated",
                rows=len(a),
                type="DOUBLE, BIGINT",
                mismatches=mismatches,
                cells=len(a),
                compared_with="sqlearn",
                note="rows compared bit for bit on one machine",
            )
        )
    return out


def cases() -> list[dict]:
    """Return the generators' cases: random values, the generators, repeats."""
    return (
        _random_cases()
        + _blobs_cases()
        + _regression_cases()
        + _classification_cases()
        + _customers_cases()
        + _repeat_cases()
    )
