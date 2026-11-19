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
    mean_gamma_deviance,
    mean_pinball_loss,
    mean_poisson_deviance,
    mean_squared_error,
    mean_squared_log_error,
    mean_tweedie_deviance,
    median_absolute_error,
    r2_score,
    root_mean_squared_error,
    root_mean_squared_log_error,
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
        (sq.metrics.msle, mean_squared_log_error),
        (sq.metrics.rmsle, root_mean_squared_log_error),
    ],
)
def test_regression_metrics_match_scikit_learn(metric, sk):
    """Each metric matches scikit-learn's to 12 digits."""
    if metric in (sq.metrics.msle, sq.metrics.rmsle):
        y, p = RNG.uniform(0, 5, size=500), RNG.uniform(0, 5, size=500)
    else:
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
    assert not sq.metrics.msle.greater_is_better
    assert not sq.metrics.rmsle.greater_is_better


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
        sq.metrics.msle,
        sq.metrics.rmsle,
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


@pytest.mark.parametrize("metric", [sq.metrics.msle, sq.metrics.rmsle])
def test_msle_refuses_a_value_at_or_below_minus_one(metric):
    """A target or a prediction at or below -1 has no logarithm of 1 + it."""
    cases = [
        ([-1.0, 1.0], [1.0, 1.0], "target"),
        ([1.0, 1.0], [1.0, -2.0], "prediction"),
    ]
    for y, p, word in cases:
        frame = pd.DataFrame({"y": y, "prediction": p})
        with pytest.raises(SqlearnError, match="1 of 2 rows") as info:
            metric.compute(rel(frame), "y")
        message = str(info.value)
        assert "Fix:" in message
        assert metric.name in message
        assert f"a {word} at or below -1" in message
    ok = pd.DataFrame({"y": [-0.5, 1.0], "prediction": [1.0, 1.0]})
    expected = 0.9609060278364028 ** (0.5 if metric is sq.metrics.rmsle else 1)
    assert metric.compute(rel(ok), "y") == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize(
    ("metric", "sk"),
    [
        (sq.metrics.msle, mean_squared_log_error),
        (sq.metrics.rmsle, root_mean_squared_log_error),
    ],
)
def test_msle_keeps_its_digits_for_values_near_zero(metric, sk):
    """log1p, not ln(1 + x): values near 1e-9 match scikit-learn."""
    y = [1e-9, 2e-9, 3e-10]
    p = [2e-9, 1e-9, 5e-10]
    frame = pd.DataFrame({"y": y, "prediction": p})
    assert metric.compute(rel(frame), "y") == pytest.approx(sk(y, p), rel=1e-12)


def test_msle_takes_an_integer_target():
    """An INTEGER target is read as a number, as scikit-learn reads it."""
    p = [1.5, 2.5, 2.0]
    frame = pd.DataFrame({"y": [1, 2, 3], "prediction": p})
    got = sq.metrics.msle.compute(rel(frame), "y")
    assert got == pytest.approx(mean_squared_log_error([1, 2, 3], p), rel=1e-12)


def test_a_gap_is_refused_before_a_range():
    """A NULL is reported, not the range of the row beside it."""
    frame = pd.DataFrame(
        {"y": [-3.0, None], "prediction": [1.0, 1.0]},
    )
    with pytest.raises(SqlearnError, match="NULL"):
        sq.metrics.msle.compute(rel(frame), "y")


Y4 = [1, 2, 3, 4]
P4 = [1.5, 2, 2, 5]


@pytest.mark.parametrize(
    ("power", "expected"),
    [
        (-1, 1.8333333333333306),
        (0, 0.5625),
        (1, 0.20917800547974497),
        (1.5, 0.13759610261391986),
        (2, 0.09490510899043825),
        (3, 0.05111111111111111),
    ],
)
def test_tweedie_deviance_matches_scikit_learn(power, expected):
    """Each power scores as scikit-learn's mean Tweedie deviance."""
    frame = pd.DataFrame({"y": Y4, "prediction": P4})
    metric = sq.metrics.tweedie_deviance(power=power)
    got = metric.compute(rel(frame), "y")
    assert got == pytest.approx(expected, rel=1e-12)
    assert got == pytest.approx(mean_tweedie_deviance(Y4, P4, power=power), rel=1e-12)


def test_poisson_and_gamma_match_scikit_learn():
    """Poisson and gamma score as their scikit-learn functions."""
    y = RNG.uniform(0.5, 5.0, size=200)
    p = RNG.uniform(0.5, 5.0, size=200)
    frame = pd.DataFrame({"y": y, "prediction": p})
    poisson = sq.metrics.poisson_deviance.compute(rel(frame), "y")
    gamma = sq.metrics.gamma_deviance.compute(rel(frame), "y")
    assert poisson == pytest.approx(mean_poisson_deviance(y, p), rel=1e-12)
    assert gamma == pytest.approx(mean_gamma_deviance(y, p), rel=1e-12)
    assert not sq.metrics.poisson_deviance.greater_is_better


@pytest.mark.parametrize(
    "power", [0.5, True, "1", float("nan"), float("inf"), -float("inf")]
)
def test_tweedie_deviance_refuses_a_power_between_zero_and_one(power):
    """A power scikit-learn's parameter check refuses is refused at the call."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.metrics.tweedie_deviance(power=power)


def test_tweedie_deviance_repr_shows_a_power():
    """The default shows its name; a changed power shows in the call form."""
    assert repr(sq.metrics.tweedie_deviance) == "tweedie_deviance"
    assert repr(sq.metrics.tweedie_deviance(power=1.5)) == "tweedie_deviance(power=1.5)"


@pytest.mark.parametrize(
    ("metric", "y", "p"),
    [
        (sq.metrics.poisson_deviance, [-1.0, 1.0], [1.0, 1.0]),
        (sq.metrics.poisson_deviance, [1.0, 1.0], [0.0, 1.0]),
        (sq.metrics.gamma_deviance, [0.0, 1.0], [1.0, 1.0]),
        (sq.metrics.gamma_deviance, [1.0, 1.0], [0.0, 1.0]),
        (sq.metrics.tweedie_deviance(power=-1), [1.0, 1.0], [0.0, 1.0]),
        (sq.metrics.tweedie_deviance(power=1.5), [-1.0, 1.0], [1.0, 1.0]),
        (sq.metrics.tweedie_deviance(power=3), [0.0, 1.0], [1.0, 1.0]),
    ],
)
def test_each_deviance_refuses_its_range(metric, y, p):
    """A row outside the power's range is refused, as scikit-learn refuses it."""
    frame = pd.DataFrame({"y": y, "prediction": p})
    with pytest.raises(SqlearnError, match="1 of 2 rows") as info:
        metric.compute(rel(frame), "y")
    assert "Fix:" in str(info.value)


def test_the_deviances_accept_what_scikit_learn_accepts():
    """Poisson takes a zero target; power 0 and -1 take a negative target."""
    zero = pd.DataFrame({"y": [0.0, 1.0], "prediction": [1.0, 1.0]})
    assert sq.metrics.poisson_deviance.compute(rel(zero), "y") == 1.0
    neg = pd.DataFrame({"y": [-1.0, 1.0], "prediction": [1.0, 1.0]})
    assert sq.metrics.tweedie_deviance.compute(rel(neg), "y") == 2.0
    got = sq.metrics.tweedie_deviance(power=-1).compute(rel(neg), "y")
    assert got == pytest.approx(0.8333333333333333, rel=1e-12)
    # No range at power 0: a prediction of 0 or less is fine.
    low = pd.DataFrame({"y": [1.0, 1.0], "prediction": [0.0, -1.0]})
    assert sq.metrics.tweedie_deviance.compute(rel(low), "y") == 2.5


def test_poisson_takes_no_power():
    """The named deviances are fixed at their power."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.metrics.poisson_deviance(power=1)
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.metrics.gamma_deviance(power=2)


def test_tweedie_deviance_takes_no_other_setting():
    """Only power is a setting."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.metrics.tweedie_deviance(alpha=0.5)


def test_a_search_by_a_deviance_with_a_power():
    """Lower deviance wins: a search runs with a power and picks by min."""
    x = RNG.uniform(1, 3, size=(120, 2))
    data = pd.DataFrame(
        {
            "a": x[:, 0],
            "b": x[:, 1],
            "y": 3 * x[:, 0] + 2 * x[:, 1] + RNG.uniform(0.1, 0.5, size=120),
        }
    )
    pipe = sq.Pipeline([("model", Ridge())])
    search = sq.search(
        pipe,
        params={"model__alpha": [0.01, 1000.0]},
        metric=sq.metrics.tweedie_deviance(power=1.5),
        folds=sq.folds.kfold(3),
    )
    assert search.train(data, target="y").best_params_ == {"model__alpha": 0.01}


@pytest.mark.parametrize("alpha", [0, 0.1, 0.5, 0.9, 1])
def test_pinball_loss_matches_scikit_learn(alpha):
    """Each alpha scores as scikit-learn's mean pinball loss."""
    y, p = RNG.normal(size=300), RNG.normal(size=300)
    frame = pd.DataFrame({"y": y, "prediction": p})
    got = sq.metrics.pinball_loss(alpha=alpha).compute(rel(frame), "y")
    assert got == pytest.approx(mean_pinball_loss(y, p, alpha=alpha), rel=1e-12)


def test_pinball_loss_on_the_probe_data():
    """Alpha 0.9 on the fixed data gives the probed value."""
    frame = pd.DataFrame({"y": Y4, "prediction": P4})
    got = sq.metrics.pinball_loss(alpha=0.9).compute(rel(frame), "y")
    assert got == pytest.approx(0.26249999999999996, rel=1e-12)
    assert got == pytest.approx(mean_pinball_loss(Y4, P4, alpha=0.9), rel=1e-12)


@pytest.mark.parametrize(
    "settings",
    [
        {"alpha": 1.5},
        {"alpha": -0.1},
        {"alpha": True},
        {"alpha": "0.5"},
        {"alpha": float("nan")},
        {"alpha": float("inf")},
        {"power": 1},
    ],
)
def test_pinball_loss_takes_only_alpha_in_zero_to_one(settings):
    """A bad alpha, or another setting, is refused at the call."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.metrics.pinball_loss(**settings)


def test_pinball_loss_repr_shows_an_alpha():
    """The repr names the alpha once it is set."""
    assert repr(sq.metrics.pinball_loss) == "pinball_loss"
    assert repr(sq.metrics.pinball_loss(alpha=0.9)) == "pinball_loss(alpha=0.9)"


def test_a_search_by_a_pinball_loss():
    """Lower loss wins: a search runs with an alpha and picks by min."""
    x = RNG.uniform(1, 3, size=(120, 2))
    data = pd.DataFrame(
        {
            "a": x[:, 0],
            "b": x[:, 1],
            "y": 3 * x[:, 0] + 2 * x[:, 1] + RNG.uniform(0.1, 0.5, size=120),
        }
    )
    search = sq.search(
        sq.Pipeline([("model", Ridge())]),
        params={"model__alpha": [0.01, 1000.0]},
        metric=sq.metrics.pinball_loss(alpha=0.9),
        folds=sq.folds.kfold(3),
    )
    assert search.train(data, target="y").best_params_ == {"model__alpha": 0.01}
