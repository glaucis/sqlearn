"""Tests of the table metrics: the confusion matrix against scikit-learn's."""

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import confusion_matrix as sk_confusion_matrix

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.metrics.tables import _labels_of

Y = [0, 1, 2, 2, 1, 0, 2]
P = [0, 2, 2, 1, 1, 0, 0]


def rel(frame):
    """Return a DuckDB relation over `frame`."""
    return connection().from_df(frame)


def matrix(out):
    """Return the label columns of a numpy-handed matrix, stacked."""
    return np.column_stack(list(out.values())[1:])


def test_confusion_matrix_matches_sklearn_on_three_classes():
    """Rows of true label, columns of predicted label, as scikit-learn's."""
    out = sq.metrics.confusion_matrix(
        rel(pd.DataFrame({"y": Y, "prediction": P})), "y", out="numpy"
    )
    assert list(out) == ["y", "0", "1", "2"]
    assert out["y"].tolist() == [0, 1, 2]
    assert (matrix(out) == sk_confusion_matrix(Y, P)).all()


@pytest.mark.parametrize("normalize", ["true", "pred", "all"])
def test_a_normalised_confusion_matrix_matches_sklearn(normalize):
    """Each normalisation is scikit-learn's, with 0 for a total of 0."""
    y, p = [0, 1, 1, 0], [0, 2, 1, 2]  # label 2 is predicted, never true
    out = sq.metrics.confusion_matrix(
        rel(pd.DataFrame({"y": y, "prediction": p})),
        "y",
        normalize=normalize,
        out="numpy",
    )
    expected = sk_confusion_matrix(y, p, normalize=normalize)
    assert (matrix(out) == expected).all()
    assert matrix(out)[2].tolist() == [0.0, 0.0, 0.0]  # no target rows: 0s


def test_confusion_matrix_names_columns_by_the_labels_text():
    """A label is a column named by its text, whatever characters it holds."""
    labels = ["it's", "a b", 'say "hi"', "z"]
    frame = pd.DataFrame({"y": labels, "prediction": labels[::-1]})
    got = sq.metrics.confusion_matrix(rel(frame), "y")
    assert got.columns == ["y", "a b", "it's", 'say "hi"', "z"]
    flags = pd.DataFrame({"y": [True, False], "prediction": [True, True]})
    assert sq.metrics.confusion_matrix(rel(flags), "y").columns == [
        "y",
        "false",
        "true",
    ]


def test_an_empty_label_refuses():
    """DuckDB cannot name a column with no text, so such a label is refused."""
    frame = pd.DataFrame({"y": ["", "a"], "prediction": ["a", "a"]})
    with pytest.raises(sq.errors.SqlearnError, match=r"empty.*Why:.*Fix:"):
        sq.metrics.confusion_matrix(rel(frame), "y")


def test_integer_and_float_labels_are_one_class():
    """An INTEGER target meeting a DOUBLE prediction shares its classes."""
    frame = pd.DataFrame({"y": [1, 0], "prediction": [1.0, 0.0]})
    out = sq.metrics.confusion_matrix(rel(frame), "y", out="numpy")
    assert len(out) == 3
    assert (matrix(out) == np.eye(2)).all()


def test_a_label_named_as_the_target_refuses():
    """A column per label cannot share the first column's name."""
    frame = pd.DataFrame({"y": ["y", "n"], "prediction": ["y", "y"]})
    with pytest.raises(
        sq.errors.SqlearnError, match=r"confusion_matrix .*label 'y'.*Fix:"
    ):
        sq.metrics.confusion_matrix(rel(frame), "y")


def test_one_label_warns_as_sklearn():
    """One label in all rows warns and gives a 1 by 1 matrix."""
    frame = pd.DataFrame({"y": [3, 3], "prediction": [3, 3]})
    with pytest.warns(UserWarning, match="A single label was found"):
        out = sq.metrics.confusion_matrix(rel(frame), "y", out="numpy")
    assert out["3"].tolist() == [2]


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (pd.DataFrame({"y": [], "prediction": []}, dtype="int64"), r"no rows"),
        (pd.DataFrame({"y": [0, 1], "prediction": [0, None]}), r"1 NULL of 2"),
        (pd.DataFrame({"y": [0.5, 1.0], "prediction": [0.0, 1.0]}), r"not whole"),
    ],
)
def test_confusion_matrix_refuses_what_precision_refuses(frame, match):
    """The label checks are precision's, with the metric's own name."""
    with pytest.raises(sq.errors.SqlearnError, match=rf"confusion_matrix .*{match}"):
        sq.metrics.confusion_matrix(rel(frame), "y")
    with pytest.raises(sq.errors.SqlearnError, match=match):
        sq.metrics.precision.compute(rel(frame), "y")


def test_confusion_matrix_refuses_a_nan_label():
    """A NaN label is refused as precision refuses it."""
    nan = connection().sql(
        "SELECT * FROM (VALUES (0.0, 0.0), (1.0, 'NaN'::DOUBLE)) t(y, prediction)"
    )
    with pytest.raises(sq.errors.SqlearnError, match=r"confusion_matrix .*1 NaN"):
        sq.metrics.confusion_matrix(nan, "y")


def test_confusion_matrix_is_a_relation_unless_out_is_given():
    """A lazy relation by default, and what `out=` names otherwise."""
    frame = pd.DataFrame({"y": Y, "prediction": P})
    assert isinstance(
        sq.metrics.confusion_matrix(rel(frame), "y"), duckdb.DuckDBPyRelation
    )
    assert isinstance(
        sq.metrics.confusion_matrix(rel(frame), "y", out="pandas"), pd.DataFrame
    )


def test_an_unknown_normalize_refuses():
    """Only None, "true", "pred" and "all" are normalisations."""
    frame = pd.DataFrame({"y": Y, "prediction": P})
    with pytest.raises(sq.errors.SqlearnError, match=r"normalize.*'rows'.*Fix:"):
        sq.metrics.confusion_matrix(rel(frame), "y", normalize="rows")


def test_odd_column_names_are_quoted():
    """Target and prediction columns with quotes and spaces are read."""
    frame = pd.DataFrame({'my "y"': [0, 1, 1], "pred ict": [0, 1, 0]})
    got = sq.metrics.confusion_matrix(rel(frame), 'my "y"', "pred ict", out="numpy")
    assert (matrix(got) == sk_confusion_matrix([0, 1, 1], [0, 1, 0])).all()


def test_the_labels_are_those_of_the_target_and_the_prediction_sorted():
    """One list of the labels in either column, as one type."""
    frame = pd.DataFrame({"y": [2, 0], "prediction": [1.0, 0.0]})
    assert _labels_of(rel(frame), "y", "prediction") == [0.0, 1.0, 2.0]


def test_a_table_cannot_rank_a_search():
    """A table function is not a Metric, so a search refuses it."""
    with pytest.raises(sq.errors.SqlearnError, match="confusion_matrix"):
        sq.search(
            sq.Pipeline([sq.preprocessing.Scale()]),
            {},
            metric=sq.metrics.confusion_matrix,  # ty: ignore[invalid-argument-type]
        )
