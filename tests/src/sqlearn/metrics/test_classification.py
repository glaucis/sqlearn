"""Tests of precision, recall and f1 against scikit-learn's."""

import pandas as pd
import pytest
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
