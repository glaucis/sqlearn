"""Tests of precision, recall and f1 against scikit-learn's."""

import math
import warnings

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import UndefinedMetricWarning
from sklearn.metrics import f1_score, precision_score, recall_score

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.metrics.classification import _counts

BINARY = pd.DataFrame(
    {"y": [0, 1, 1, 0, 1, 1, 0, 0], "prediction": [0, 1, 0, 0, 1, 1, 1, 0]},
)


def rel(frame):
    """Return a DuckDB relation over `frame`."""
    return connection().from_df(frame)


@pytest.mark.parametrize(
    ("name", "sk"),
    [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)],
)
def test_binary_scores_match_sklearn(name, sk):
    """Under the binary default each score is scikit-learn's, exactly."""
    got = getattr(sq.metrics, name).compute(rel(BINARY), "y")
    assert got == sk(BINARY["y"], BINARY["prediction"])


def test_counts_come_from_one_grouped_query():
    """Each class's rows in the target, in the prediction, and in both."""
    assert _counts(rel(BINARY), "y", "prediction") == [(0, 4, 4, 3), (1, 4, 4, 3)]


def test_odd_column_names_are_quoted():
    """Target and prediction columns with quotes and spaces are read."""
    frame = pd.DataFrame({'my "y"': [0, 1, 1], "pred ict": [0, 1, 0]})
    assert sq.metrics.recall.compute(rel(frame), 'my "y"', "pred ict") == 0.5


def test_the_metrics_read_predict_and_higher_is_better():
    """The three read predict, and a higher score is better."""
    for metric in (sq.metrics.precision, sq.metrics.recall, sq.metrics.f1):
        assert isinstance(metric, sq.metrics.Metric)
        assert metric.needs == "predict"
        assert metric.greater_is_better is True


@pytest.mark.parametrize("column", ["y", "prediction"])
def test_null_is_refused_naming_the_column(column):
    """A NULL label is refused as accuracy refuses it."""
    frame = pd.DataFrame({"y": [1, 0], "prediction": [1, 0]})
    frame[column] = pd.Series([1, None], dtype="Int64")
    with pytest.raises(
        sq.errors.SqlearnError, match=rf"precision cannot .* column '{column}' has 1"
    ):
        sq.metrics.precision.compute(rel(frame), "y")


def test_empty_relation_is_refused():
    """No rows is refused as accuracy refuses it."""
    frame = pd.DataFrame(
        {"y": pd.Series([], dtype="int64"), "prediction": pd.Series([], dtype="int64")}
    )
    with pytest.raises(sq.errors.SqlearnError, match=r"f1 cannot .* no rows"):
        sq.metrics.f1.compute(rel(frame), "y")


@pytest.mark.parametrize("column", ["y", "prediction"])
def test_nan_is_refused_naming_the_column(column):
    """A NaN label is refused as accuracy refuses it."""
    y, p = ("'NaN'::DOUBLE", "1.0") if column == "y" else ("1.0", "'NaN'::DOUBLE")
    sql = f"SELECT * FROM (VALUES (0.0, 0.0), ({y}, {p})) t(y, prediction)"
    with pytest.raises(sq.errors.SqlearnError, match=rf"column '{column}' has 1 NaN"):
        sq.metrics.recall.compute(connection().sql(sql), "y")


def test_missing_column_is_refused():
    """A column not in the relation is refused."""
    with pytest.raises(sq.errors.SqlearnError, match=r"column 'nope' is not in"):
        sq.metrics.f1.compute(rel(BINARY), "nope")


SCORES = {"precision": precision_score, "recall": recall_score, "f1": f1_score}


def three_classes(labels):
    """Return 300 rows of three classes, the prediction right about 60% of the time."""
    rng = np.random.default_rng(3)
    y = rng.choice(labels, 300)
    p = np.where(rng.random(300) < 0.6, y, rng.choice(labels, 300))
    return pd.DataFrame({"y": y, "prediction": p})


@pytest.mark.parametrize("labels", [[0, 1, 2], ["a", "b", "c"]])
@pytest.mark.parametrize("average", ["macro", "micro", "weighted"])
@pytest.mark.parametrize("name", ["precision", "recall", "f1"])
def test_averages_match_sklearn_on_three_classes(name, average, labels):
    """Each average over three classes is scikit-learn's."""
    frame = three_classes(labels)
    metric = getattr(sq.metrics, name)(average=average)
    want = SCORES[name](frame["y"], frame["prediction"], average=average)
    assert metric.compute(rel(frame), "y") == pytest.approx(want, rel=1e-15)


def test_a_label_only_in_the_prediction_is_a_class():
    """A label the model predicts but the target lacks counts in macro's mean."""
    frame = pd.DataFrame({"y": [0, 0, 1, 1], "prediction": [0, 2, 1, 1]})
    metric = sq.metrics.f1(average="macro", zero_division=0.0)
    want = f1_score(frame["y"], frame["prediction"], average="macro", zero_division=0.0)
    assert metric.compute(rel(frame), "y") == pytest.approx(want, rel=1e-15)


def test_calling_returns_a_copy_and_leaves_the_default():
    """A call gives a new metric; the one called is unchanged."""
    macro = sq.metrics.f1(average="macro")
    assert macro.average == "macro"
    assert sq.metrics.f1.average == "binary"
    assert macro(zero_division=1.0).average == "macro"
    assert macro(zero_division=1.0).zero_division == 1.0


def test_repr_names_the_settings_changed():
    """The repr shows the settings away from scikit-learn's defaults."""
    assert repr(sq.metrics.f1) == "f1"
    assert repr(sq.metrics.f1(average="macro")) == "f1(average='macro')"


def test_unknown_average_is_refused():
    """An average scikit-learn does not take here is refused, listing those it does."""
    with pytest.raises(
        sq.errors.SqlearnError, match="'binary', 'macro', 'micro', 'weighted'"
    ):
        sq.metrics.f1(average="samples")


def test_unknown_zero_division_is_refused():
    """A zero_division other than warn, 0, 1 or nan is refused."""
    with pytest.raises(sq.errors.SqlearnError, match="zero_division"):
        sq.metrics.recall(zero_division=0.5)


def test_a_metric_without_settings_refuses_a_call():
    """Accuracy takes no settings, and says so."""
    with pytest.raises(sq.errors.SqlearnError, match="accuracy takes no settings"):
        sq.metrics.accuracy(average="macro")


def test_an_unknown_setting_is_refused():
    """A setting none of the three is refused, naming them."""
    with pytest.raises(
        sq.errors.SqlearnError, match="average, pos_label, zero_division"
    ):
        sq.metrics.precision(beta=2)


def test_binary_on_three_classes_is_refused_naming_the_averages():
    """The binary default refuses three classes, as scikit-learn, naming the others."""
    with pytest.raises(sq.errors.SqlearnError, match=r"average=.*'macro'"):
        sq.metrics.f1.compute(rel(three_classes([0, 1, 2])), "y")


def test_text_labels_with_the_default_pos_label_are_refused():
    """Two text labels and pos_label=1: refused, naming pos_label= and the labels."""
    frame = pd.DataFrame({"y": ["a", "b"], "prediction": ["a", "b"]})
    with pytest.raises(sq.errors.SqlearnError, match=r"pos_label=.*'a', 'b'"):
        sq.metrics.precision.compute(rel(frame), "y")


def test_text_labels_with_their_pos_label_are_scored():
    """Naming the positive text label scores it, as scikit-learn."""
    frame = pd.DataFrame({"y": ["a", "b", "b"], "prediction": ["a", "b", "a"]})
    got = sq.metrics.recall(pos_label="b").compute(rel(frame), "y")
    assert got == recall_score(frame["y"], frame["prediction"], pos_label="b")


def test_one_label_only_scores_pos_label_as_absent():
    """One label, pos_label absent: no refusal; 0 with a warning, as scikit-learn."""
    frame = pd.DataFrame({"y": [0, 0], "prediction": [0, 0]})
    with pytest.warns(sq.errors.UndefinedMetricWarning):
        got = sq.metrics.f1.compute(rel(frame), "y")
    assert got == 0.0


def test_int_target_and_float_prediction_are_the_same_classes():
    """An INTEGER target and a DOUBLE prediction of whole numbers share classes."""
    sql = "SELECT * FROM (VALUES (0, 0.0), (1, 1.0), (1, 0.0)) t(y, prediction)"
    got = sq.metrics.recall.compute(connection().sql(sql), "y")
    assert got == recall_score([0, 1, 1], [0.0, 1.0, 0.0])


def test_a_non_whole_number_label_is_refused_as_continuous():
    """A prediction of 1.5 is a continuous value, not a label: refused."""
    sql = "SELECT * FROM (VALUES (0, 0.0), (1, 1.5)) t(y, prediction)"
    with pytest.raises(sq.errors.SqlearnError, match=r"'prediction'.*continuous"):
        sq.metrics.precision.compute(connection().sql(sql), "y")


def test_text_against_numbers_is_refused():
    """A text target against a number prediction is refused, naming both types."""
    frame = pd.DataFrame({"y": ["a", "b"], "prediction": [0, 1]})
    with pytest.raises(sq.errors.SqlearnError, match=r"VARCHAR.*BIGINT"):
        sq.metrics.f1.compute(rel(frame), "y")


ZERO_DIVISION_CASES = {
    "never predicted": ([0, 0, 1, 1], [0, 0, 0, 0]),
    "one label": ([0, 0], [0, 0]),
    "only predicted": ([0, 0, 1, 1], [0, 2, 1, 1]),
}


@pytest.mark.parametrize("case", list(ZERO_DIVISION_CASES))
@pytest.mark.parametrize("zero_division", ["warn", 0.0, 1.0, math.nan])
@pytest.mark.parametrize("average", ["binary", "macro", "micro", "weighted"])
@pytest.mark.parametrize("name", ["precision", "recall", "f1"])
def test_zero_division_matches_sklearn(name, average, zero_division, case):
    """Each undefined score takes scikit-learn's value, warning when it warns."""
    y, p = ZERO_DIVISION_CASES[case]
    if average == "binary" and len(set(y) | set(p)) > 2:
        pytest.skip("binary refuses three classes")
    with warnings.catch_warnings(record=True) as sk_warned:
        warnings.simplefilter("always")
        want = SCORES[name](y, p, average=average, zero_division=zero_division)
    metric = getattr(sq.metrics, name)(average=average, zero_division=zero_division)
    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        got = metric.compute(rel(pd.DataFrame({"y": y, "prediction": p})), "y")
    assert got == pytest.approx(want, nan_ok=True, rel=1e-15)
    sk_undefined = any(w.category is UndefinedMetricWarning for w in sk_warned)
    ours = any(w.category is sq.errors.UndefinedMetricWarning for w in warned)
    assert ours == sk_undefined
