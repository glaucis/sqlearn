"""Tests of balanced_accuracy and mcc against scikit-learn's."""

import math
import warnings
from fractions import Fraction

import pandas as pd
import pytest
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError, SqlearnWarning

RARE = ([0] * 95 + [1] * 5, [0] * 100)


def rel(y, prediction):
    """Return a DuckDB relation of a target column and a prediction column."""
    return connection().from_df(pd.DataFrame({"y": y, "prediction": prediction}))


@pytest.mark.parametrize(
    ("y", "prediction", "adjusted"),
    [
        (*RARE, False),
        (*RARE, True),
        (["a", "b", "b"], ["a", "a", "b"], False),
        ([0, 1, 2, 2, 1, 0, 2], [0, 2, 2, 1, 1, 0, 0], False),
        ([0, 1, 2, 2, 1, 0, 2], [0, 2, 2, 1, 1, 0, 0], True),
    ],
)
def test_balanced_accuracy_matches_scikit_learn(y, prediction, adjusted):
    """The mean recall over the target's classes, adjusted or not.

    scikit-learn averages in doubles and rescales the rounded mean; sqlearn
    rounds the exact score once (ADR 0016), so they may differ by two doubles
    (5/12 adjusted: two).
    """
    metric = sq.metrics.balanced_accuracy(adjusted=adjusted)
    got = metric.compute(rel(y, prediction), "y")
    expected = balanced_accuracy_score(y, prediction, adjusted=adjusted)
    assert abs(got - expected) <= 2 * math.ulp(expected)


def test_balanced_accuracy_is_the_double_nearest_the_exact_score():
    """Recalls 1, 1/2 and 1/3: the mean 11/18, adjusted 5/12, rounded once."""
    y, prediction = [0, 1, 2, 2, 1, 0, 2], [0, 2, 2, 1, 1, 0, 0]
    plain = sq.metrics.balanced_accuracy.compute(rel(y, prediction), "y")
    adjusted = sq.metrics.balanced_accuracy(adjusted=True)
    assert plain == float(Fraction(11, 18))
    assert adjusted.compute(rel(y, prediction), "y") == float(Fraction(5, 12))


def test_a_predicted_class_outside_the_target_is_warned():
    """A class only in the prediction counts for nothing, and is warned about."""
    with pytest.warns(SqlearnWarning, match="Fix:") as caught:
        got = sq.metrics.balanced_accuracy.compute(rel([0, 0, 1, 1], [0, 2, 1, 1]), "y")
    assert got == 0.75
    assert len(caught) == 1


def test_adjusted_on_one_class_is_minus_infinity_with_a_warning():
    """One target class leaves chance at 1: scikit-learn's minus infinity."""
    metric = sq.metrics.balanced_accuracy(adjusted=True)
    with pytest.warns(SqlearnWarning, match="Fix:"):
        got = metric.compute(rel([1, 1, 1], [1, 1, 1]), "y")
    assert got == -math.inf or math.isnan(got)
    with pytest.warns(SqlearnWarning, match="Fix:"):
        got = metric.compute(rel([1, 1, 1], [1, 0, 1]), "y")
    assert got == -math.inf


def test_balanced_accuracy_takes_only_adjusted():
    """adjusted= is its one setting, shown in its name when set."""
    with pytest.raises(SqlearnError, match="adjusted"):
        sq.metrics.balanced_accuracy(beta=1)
    assert repr(sq.metrics.balanced_accuracy(adjusted=True)) == (
        "balanced_accuracy(adjusted=True)"
    )
    assert repr(sq.metrics.balanced_accuracy) == "balanced_accuracy"


def test_balanced_accuracy_reads_predict_and_higher_is_better():
    """It reads predict, a higher score is better, and nothing else warns."""
    metric = sq.metrics.balanced_accuracy
    assert isinstance(metric, sq.metrics.Metric)
    assert (metric.needs, metric.greater_is_better) == ("predict", True)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        metric.compute(rel([0, 1, 1], [0, 1, 0]), "y")


def test_counts_scores_refuse_no_rows_and_missing_values():
    """No rows and a NULL label are refused, as accuracy refuses them."""
    empty = connection().sql("SELECT 1 AS y, 1 AS prediction WHERE false")
    with pytest.raises(SqlearnError):
        sq.metrics.balanced_accuracy.compute(empty, "y")
    frame = pd.DataFrame(
        {"y": [1, 0], "prediction": pd.Series([1, None], dtype="Int64")}
    )
    with pytest.raises(SqlearnError, match="prediction"):
        sq.metrics.balanced_accuracy.compute(connection().from_df(frame), "y")


@pytest.mark.parametrize(
    ("y", "prediction"),
    [
        RARE,
        ([0, 1], [0, 1]),
        ([0, 1, 2, 2, 1], [0, 2, 2, 1, 1]),
        (["no", "yes", "yes", "no", "yes"], ["no", "yes", "no", "no", "no"]),
        ([0, 1, 1, 0, 1, 0, 1, 1], [1, 1, 0, 0, 1, 1, 0, 1]),
    ],
)
def test_mcc_matches_scikit_learn(y, prediction):
    """The Matthews correlation of two classes or more, within two doubles."""
    got = sq.metrics.mcc.compute(rel(y, prediction), "y")
    expected = matthews_corrcoef(y, prediction)
    assert abs(got - expected) <= 2 * math.ulp(expected)


def test_mcc_of_one_label_is_zero():
    """One label everywhere has no correlation: 0.0, and no warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert sq.metrics.mcc.compute(rel([1, 1], [1, 1]), "y") == 0.0


def test_mcc_counts_an_integer_and_a_double_one_as_one_class():
    """An INTEGER target and a DOUBLE prediction agree where 1 meets 1.0."""
    frame = pd.DataFrame({"y": [0, 1, 1, 0], "prediction": [0.0, 1.0, 1.0, 0.0]})
    assert sq.metrics.mcc.compute(connection().from_df(frame), "y") == 1.0


def test_mcc_takes_no_settings():
    """The MCC has no settings to set; it reads predict, higher is better."""
    with pytest.raises(SqlearnError, match="takes no settings"):
        sq.metrics.mcc(adjusted=True)
    assert (sq.metrics.mcc.needs, sq.metrics.mcc.greater_is_better) == (
        "predict",
        True,
    )
    assert repr(sq.metrics.mcc) == "mcc"
