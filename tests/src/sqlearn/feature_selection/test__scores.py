"""Tests of the scores of sq.select.best against scikit-learn's."""

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
