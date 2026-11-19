"""Tests of the scores of sq.select.best against scikit-learn's."""

import sys
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_selection import chi2, f_classif, f_regression

import sqlearn as sq

SCIKIT = {"f_classif": f_classif, "f_regression": f_regression, "chi2": chi2}


def data(score, seed=3, rows=200):
    """Return 6 non-negative columns, some related to the target, and the target."""
    rng = np.random.default_rng(seed)
    if score == "f_regression":
        y = rng.normal(0, 2, rows)
        signal = np.abs(y)
    else:
        y = rng.integers(0, 3, rows)
        signal = y.astype(float)
    frame = pd.DataFrame(
        {
            "a": rng.uniform(0, 1, rows) + 0.3 * signal,
            "b": rng.poisson(3, rows).astype("int64"),
            "c": rng.exponential(2, rows) + signal,
            "d": rng.uniform(0, 100, rows),
            "e": rng.gamma(2, 1, rows) + 0.05 * signal,
            "f": rng.integers(0, 5, rows).astype("int64") + (signal > 1),
        }
    )
    return frame, y


def scores(frame, y, score):
    """Return sqlearn's scores_ for every column of `frame`."""
    pipe = sq.Pipeline([sq.select.best(k="all", score=score)])
    pipe.learn(frame.assign(y=y), target="y")
    return pipe["best"].scores_


@pytest.mark.parametrize("score", ["f_classif", "f_regression", "chi2"])
def test_each_score_matches_scikit_learn(score):
    """200 rows, 6 columns: each column's score is scikit-learn's."""
    frame, y = data(score)
    expected, _ = SCIKIT[score](frame.to_numpy(dtype=float), y)
    got = scores(frame, y, score)
    assert list(got) == list(frame.columns)
    assert list(got.values()) == pytest.approx(list(expected), rel=1e-9)


@pytest.mark.parametrize("score", ["f_classif", "chi2"])
def test_scores_of_text_classes_match_scikit_learn(score):
    """Classes 'no', 'yes', 'maybe' are scored as scikit-learn scores labels."""
    frame, y = data(score)
    labels = np.array(["no", "yes", "maybe"], dtype=object)[y]
    expected, _ = SCIKIT[score](frame.to_numpy(dtype=float), labels)
    got = scores(frame, labels, score)
    assert list(got.values()) == pytest.approx(list(expected), rel=1e-9)


def test_columns_differing_only_by_case_are_scored_apart():
    """``a`` and ``A`` are both scored, under the names ADR 0035 gives them."""
    frame, y = data("f_classif")
    two = pd.DataFrame(
        np.column_stack([frame["a"], frame["c"]]), columns=pd.Index(["a", "A"])
    )
    expected, _ = f_classif(two.to_numpy(), y)
    got = scores(two, y, "f_classif")
    assert list(got) == ["a", "A_1"]
    assert list(got.values()) == pytest.approx(list(expected), rel=1e-9)
    assert got["a"] != got["A_1"]


def exact_f_classif(x, y):
    """Return the ANOVA F of `x` across the classes of `y`, exactly."""
    values = [Fraction(v) for v in x]
    n, classes = len(values), sorted(set(y))
    mean = sum(values) / n
    groups = [[v for v, c in zip(values, y, strict=True) if c == k] for k in classes]
    between = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in groups)
    within = sum((v - sum(g) / len(g)) ** 2 for g in groups for v in g)
    return float(between / (len(classes) - 1) / (within / (n - len(classes))))


def exact_f_regression(x, y):
    """Return the F of the correlation of `x` and `y`, exactly."""
    xs, ys = [Fraction(v) for v in x], [Fraction(v) for v in y]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    return float(cov**2 * (n - 2) / (vx * vy - cov**2))


def test_a_column_far_from_zero_scores_its_exact_value():
    """1e6 plus noise: sqlearn's score is the exact one, scikit-learn's is not.

    scikit-learn sums the squares of the raw values, and the cancellation
    costs it digits; sqlearn's sums are of the column less its minimum
    (f_classif) or about the mean (f_regression). Spec section 4.4.
    """
    rng = np.random.default_rng(11)
    classes = rng.integers(0, 3, 60)
    number = rng.normal(0, 1, 60)
    column = pd.DataFrame({"far": 1e6 + rng.normal(0, 1, 60) + 0.2 * classes})
    for score, y, exact in [
        ("f_classif", classes, exact_f_classif),
        ("f_regression", number, exact_f_regression),
    ]:
        expected = exact(column["far"].to_numpy(), y)
        got = scores(column, y, score)["far"]
        assert got == pytest.approx(expected, rel=1e-9)
        sk, _ = SCIKIT[score](column.to_numpy(), y)
        assert sk[0] != pytest.approx(expected, rel=1e-6)


def test_an_exactly_linear_column_scores_far_above_the_others():
    """-y and 2y + 1: |r| = 1, so F is infinite, forced to the largest double.

    The F combines DuckDB's variances and covariance exactly, so it is the
    largest double when they come out consistent (-y) and a large finite F
    when their rounding leaves r² just below 1 (2y + 1); either ranks above
    every column that is not linear. Spec section 4.4.
    """
    y = np.arange(60.0) % 17
    noise = np.random.default_rng(2).normal(0, 1, 60)
    frame = pd.DataFrame({"up": 2 * y + 1, "down": -y, "near": y + noise})
    got = scores(frame, y, "f_regression")
    assert got["down"] == sys.float_info.max
    assert got["up"] > 1e15 > 1e6 * got["near"]


def test_f_regression_forces_a_finite_score():
    """A constant target scores every column 0, and so do two rows."""
    frame, _ = data("f_regression")
    constant = scores(frame, np.full(len(frame), 3.0), "f_regression")
    assert set(constant.values()) == {0.0}
    two = scores(frame.head(2), np.array([0.5, 2.0]), "f_regression")
    assert set(two.values()) == {0.0}
