"""Tests of accuracy against scikit-learn's accuracy_score."""

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import accuracy_score

import sqlearn as sq
from sqlearn._config import connection


def rel(frame):
    """Return a DuckDB relation over `frame`."""
    return connection().from_df(frame)


def test_accuracy_matches_sklearn_ints():
    """Accuracy matches sklearn ints."""
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {"y": rng.integers(0, 3, 200), "prediction": rng.integers(0, 3, 200)},
    )
    got = sq.metrics.accuracy.compute(rel(frame), "y")
    assert got == pytest.approx(accuracy_score(frame["y"], frame["prediction"]))


def test_accuracy_matches_sklearn_strings():
    """Accuracy matches sklearn strings."""
    rng = np.random.default_rng(2)
    labels = ["a", "b", "c"]
    frame = pd.DataFrame(
        {"y": rng.choice(labels, 200), "prediction": rng.choice(labels, 200)},
    )
    got = sq.metrics.accuracy.compute(rel(frame), "y")
    assert got == pytest.approx(accuracy_score(frame["y"], frame["prediction"]))


def test_int_labels_equal_float_predictions():
    """Int labels equal float predictions."""
    frame = pd.DataFrame({"y": [1, 2, 3], "prediction": [1.0, 2.0, 4.0]})
    assert sq.metrics.accuracy.compute(rel(frame), "y") == pytest.approx(2 / 3)


def test_odd_column_names_are_quoted():
    """Odd column names are quoted."""
    frame = pd.DataFrame({'my "y"': [1, 2], "pred ict": [1, 3]})
    assert sq.metrics.accuracy.compute(rel(frame), 'my "y"', "pred ict") == 0.5


def test_sql_is_avg_case():
    """Sql is avg case."""
    y = duckdb.ColumnExpression("y")
    p = duckdb.ColumnExpression("p")
    text = str(sq.metrics.accuracy.expression(y, p))
    assert text.startswith("favg((CASE WHEN")
    assert "ELSE" in text


def test_metric_fields():
    """Metric fields."""
    assert sq.metrics.accuracy.name == "accuracy"
    assert sq.metrics.accuracy.greater_is_better is True
    assert sq.metrics.Metric is type(sq.metrics.accuracy)


@pytest.mark.parametrize("column", ["y", "prediction"])
def test_null_is_refused_naming_the_column(column):
    """Null is refused naming the column."""
    frame = pd.DataFrame({"y": [1, 2], "prediction": [1, 2]})
    frame[column] = pd.Series([1, None], dtype="Int64")
    with pytest.raises(sq.errors.SqlearnError, match=rf"column '{column}'"):
        sq.metrics.accuracy.compute(rel(frame), "y")


def test_empty_relation_is_refused():
    """Empty relation is refused."""
    frame = pd.DataFrame(
        {
            "y": pd.Series([], dtype="int64"),
            "prediction": pd.Series([], dtype="int64"),
        },
    )
    with pytest.raises(sq.errors.SqlearnError, match="no rows"):
        sq.metrics.accuracy.compute(rel(frame), "y")


@pytest.mark.parametrize("column", ["y", "prediction"])
def test_nan_is_refused_naming_the_column(column):
    """Nan is refused naming the column."""
    y, p = ("'NaN'::DOUBLE", "2.0") if column == "y" else ("2.0", "'NaN'::DOUBLE")
    sql = f"SELECT * FROM (VALUES (1.0, 1.0), ({y}, {p})) t(y, prediction)"
    with pytest.raises(sq.errors.SqlearnError, match=rf"column '{column}' has 1 NaN"):
        sq.metrics.accuracy.compute(connection().sql(sql), "y")


def test_missing_column_is_refused():
    """Missing column is refused."""
    frame = pd.DataFrame({"y": [1], "prediction": [1]})
    with pytest.raises(sq.errors.SqlearnError, match=r"column 'nope' is not in"):
        sq.metrics.accuracy.compute(rel(frame), "nope")


def test_incomparable_types_are_refused():
    """Incomparable types are refused."""
    frame = pd.DataFrame({"y": ["a", "b"], "prediction": [1, 2]})
    with pytest.raises(sq.errors.SqlearnError, match=r"column 'y' \(VARCHAR\)"):
        sq.metrics.accuracy.compute(rel(frame), "y")
