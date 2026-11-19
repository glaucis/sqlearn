"""Tests of the regression metrics against scikit-learn."""

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    explained_variance_score,
    max_error,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
    root_mean_squared_error,
)

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError

RNG = np.random.default_rng(0)


def rel(frame):
    """Return a DuckDB relation over `frame`."""
    return connection().from_df(frame)


@pytest.mark.parametrize(
    ("metric", "sk"),
    [
        (sq.metrics.rmse, root_mean_squared_error),
        (sq.metrics.mae, mean_absolute_error),
        (sq.metrics.r2, r2_score),
        (sq.metrics.mse, mean_squared_error),
        (sq.metrics.max_error, max_error),
        (sq.metrics.median_absolute_error, median_absolute_error),
        (sq.metrics.mape, mean_absolute_percentage_error),
        (sq.metrics.explained_variance, explained_variance_score),
    ],
)
def test_regression_metrics_match_scikit_learn(metric, sk):
    """Each metric matches scikit-learn's to 12 digits."""
    y, p = RNG.normal(size=500), RNG.normal(size=500)
    frame = pd.DataFrame({"y": y, "prediction": p})
    assert metric.compute(rel(frame), "y") == pytest.approx(sk(y, p), rel=1e-12)


def test_the_direction_of_each_metric():
    """Errors are better lower, r2 higher."""
    assert not sq.metrics.rmse.greater_is_better
    assert not sq.metrics.mae.greater_is_better
    assert not sq.metrics.mse.greater_is_better
    assert not sq.metrics.max_error.greater_is_better
    assert not sq.metrics.median_absolute_error.greater_is_better
    assert not sq.metrics.mape.greater_is_better
    assert sq.metrics.r2.greater_is_better
    assert sq.metrics.explained_variance.greater_is_better


def test_r2_of_a_constant_target_follows_scikit_learn():
    """A constant target scores 1 when predicted exactly, else 0."""
    exact = pd.DataFrame({"y": [2.0, 2.0, 2.0], "prediction": [2.0, 2.0, 2.0]})
    off = pd.DataFrame({"y": [2.0, 2.0, 2.0], "prediction": [1.0, 2.0, 3.0]})
    assert sq.metrics.r2.compute(rel(exact), "y") == r2_score(
        exact["y"], exact["prediction"]
    )
    assert sq.metrics.r2.compute(rel(off), "y") == r2_score(off["y"], off["prediction"])


def test_r2_survives_a_large_offset():
    """The target's mean far above its spread does not cost r2 its digits."""
    y = 1e6 + RNG.normal(size=500)
    p = y + RNG.normal(scale=0.5, size=500)
    got = sq.metrics.r2.compute(rel(pd.DataFrame({"y": y, "prediction": p})), "y")
    assert got == pytest.approx(r2_score(y, p), rel=1e-10)


@pytest.mark.parametrize(
    "prediction", [[2.0, 2.0, 2.0], [3.0, 3.0, 3.0], [1.0, 2.0, 3.0]]
)
def test_explained_variance_of_a_constant_target_follows_scikit_learn(prediction):
    """A constant target scores 1 when the error's variance is 0, else 0."""
    frame = pd.DataFrame({"y": [2.0, 2.0, 2.0], "prediction": prediction})
    got = sq.metrics.explained_variance.compute(rel(frame), "y")
    assert got == explained_variance_score(frame["y"], frame["prediction"])


def test_explained_variance_survives_a_large_offset():
    """The target's mean far above its spread does not cost it its digits."""
    y = 1e6 + RNG.normal(size=500)
    p = y + RNG.normal(scale=0.5, size=500)
    frame = pd.DataFrame({"y": y, "prediction": p})
    got = sq.metrics.explained_variance.compute(rel(frame), "y")
    assert got == pytest.approx(explained_variance_score(y, p), rel=1e-9)


@pytest.mark.parametrize(
    "metric",
    [
        sq.metrics.rmse,
        sq.metrics.mae,
        sq.metrics.r2,
        sq.metrics.mse,
        sq.metrics.max_error,
        sq.metrics.median_absolute_error,
        sq.metrics.mape,
        sq.metrics.explained_variance,
    ],
)
def test_regression_metrics_refuse_missing_values_and_no_rows(metric):
    """NULL, NaN and an empty relation have no score."""
    good = pd.DataFrame({"y": [1.0, 2.0], "prediction": [1.0, 2.0]})
    with pytest.raises(SqlearnError, match="no rows"):
        metric.compute(rel(good.iloc[:0]), "y")
    with pytest.raises(SqlearnError, match="NaN"):
        metric.compute(
            connection().sql(
                "SELECT * FROM (VALUES (1.0, 1.0), (2.0, 'NaN'::DOUBLE)) "
                "t(y, prediction)"
            ),
            "y",
        )
    with pytest.raises(SqlearnError, match="NULL"):
        metric.compute(
            rel(
                pd.DataFrame(
                    {"y": [1, 2], "prediction": pd.array([1, None], dtype="Int64")}
                )
            ),
            "y",
        )


def test_mape_of_a_zero_target_is_scikit_learns_large_number():
    """A zero target divides by machine epsilon, as scikit-learn does."""
    frame = pd.DataFrame({"y": [0.0, 1.0], "prediction": [1.0, 1.0]})
    assert sq.metrics.mape.compute(rel(frame), "y") == 2251799813685248.0


def test_median_absolute_error_of_an_even_count_is_the_middle_mean():
    """Four errors have the mean of the middle two as their median."""
    frame = pd.DataFrame({"y": [1, 2, 3, 4], "prediction": [1.5, 2, 2, 5]})
    assert sq.metrics.median_absolute_error.compute(rel(frame), "y") == 0.75


def test_a_search_minimises_rmse():
    """Lower rmse wins: a search picks the weaker penalty on a linear target."""
    x = RNG.normal(size=(120, 2))
    data = pd.DataFrame(
        {
            "a": x[:, 0],
            "b": x[:, 1],
            "y": 3 * x[:, 0] - 2 * x[:, 1] + RNG.normal(scale=0.1, size=120),
        }
    )
    pipe = sq.Pipeline([("model", Ridge())])
    search = sq.search(
        pipe,
        params={"model__alpha": [0.01, 100.0]},
        metric=sq.metrics.rmse,
        folds=sq.folds.kfold(3),
    )
    assert search.train(data, target="y").best_params_ == {"model__alpha": 0.01}
