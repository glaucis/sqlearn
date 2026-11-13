"""Tests of the table metrics: the confusion matrix against scikit-learn's."""

import datetime
import math
import warnings

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


CASED = pd.DataFrame({"y": ["a", "A"], "prediction": ["A", "a"]})


@pytest.mark.parametrize("normalize", [None, "true", "pred", "all"])
def test_labels_that_differ_only_by_case_refuse(normalize):
    """DuckDB renames the second of two columns named alike ("a_1"), so refuse."""
    with pytest.raises(
        sq.errors.SqlearnError,
        match=r"confusion_matrix .*'A' and 'a'.*differ only by case.*Why:.*Fix:",
    ):
        sq.metrics.confusion_matrix(rel(CASED), "y", normalize=normalize)


def test_labels_with_other_text_keep_their_case_in_pandas():
    """Labels of mixed case, none alike ignoring case, keep their names."""
    frame = pd.DataFrame({"y": ["a", "B"], "prediction": ["B", "a"]})
    got = sq.metrics.confusion_matrix(rel(frame), "y", normalize="true", out="pandas")
    assert list(got.columns) == ["y", "B", "a"]
    assert got["B"].tolist() == [0.0, 1.0]
    assert got["a"].tolist() == [1.0, 0.0]


def test_a_label_named_as_the_target_ignoring_case_refuses():
    """DuckDB names are case-insensitive: label 'Y' clashes with target 'y'."""
    frame = pd.DataFrame({"y": ["Y", "n"], "prediction": ["Y", "Y"]})
    with pytest.raises(
        sq.errors.SqlearnError, match=r"confusion_matrix .*label 'Y'.*Fix:"
    ):
        sq.metrics.confusion_matrix(rel(frame), "y")


def _sk_report(y, p, **kwargs):
    """Return scikit-learn's report as a dict, its warnings set aside."""
    from sklearn.metrics import classification_report

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return classification_report(y, p, output_dict=True, **kwargs)


def _report_rows(got):
    """Return a report's rows by label, each as a dict of its columns."""
    names = got.columns
    return {r[0]: dict(zip(names[1:], r[1:], strict=True)) for r in got.fetchall()}


def _same(a, b):
    """Say whether two cells agree: both NULL, both NaN, or equal to 14 digits."""
    return (
        (a is None and b is None)
        or (a == pytest.approx(b, rel=1e-14))
        or (a != a and b != b)
    )


def test_classification_report_matches_sklearns_output_dict():
    """A row per class, then accuracy, macro avg and weighted avg."""
    got = sq.metrics.classification_report(
        rel(pd.DataFrame({"y": Y, "prediction": P})), "y"
    )
    assert got.columns == ["label", "precision", "recall", "f1_score", "support"]
    assert list(got.types) == ["VARCHAR", "DOUBLE", "DOUBLE", "DOUBLE", "BIGINT"]
    rows = _report_rows(got)
    want = _sk_report(Y, P)
    assert list(rows) == ["0", "1", "2", "accuracy", "macro avg", "weighted avg"]
    for label in ("0", "1", "2", "macro avg", "weighted avg"):
        # scikit-learn averages in floats, sqlearn exactly: within 1e-14
        for ours, theirs in (
            ("precision", "precision"),
            ("recall", "recall"),
            ("f1_score", "f1-score"),
            ("support", "support"),
        ):
            assert rows[label][ours] == pytest.approx(want[label][theirs], rel=1e-14)
    assert rows["accuracy"] == {
        "precision": None,
        "recall": None,
        "f1_score": want["accuracy"],
        "support": len(Y),
    }


@pytest.mark.parametrize("zero_division", ["warn", 0.0, 1.0, math.nan])
def test_the_reports_zero_division_matches_sklearn(zero_division):
    """A class never predicted takes zero_division; nan leaves it out of macro."""
    y, p = [0, 1, 2, 2], [0, 0, 2, 2]  # class 1 is never predicted
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rows = _report_rows(
            sq.metrics.classification_report(
                rel(pd.DataFrame({"y": y, "prediction": p})),
                "y",
                zero_division=zero_division,
            )
        )
    want = _sk_report(y, p, zero_division=zero_division)
    for label in ("0", "1", "2", "macro avg", "weighted avg"):
        for ours, theirs in (
            ("precision", "precision"),
            ("recall", "recall"),
            ("f1_score", "f1-score"),
        ):
            assert _same(rows[label][ours], want[label][theirs]), (label, ours)


def test_the_report_warns_once_naming_the_classes():
    """One warning per undefined score kind, with the labels, as precision's."""
    y, p = [0, 1, 2, 2], [0, 0, 2, 2]
    with pytest.warns(sq.errors.UndefinedMetricWarning) as caught:
        sq.metrics.classification_report(
            rel(pd.DataFrame({"y": y, "prediction": p})), "y"
        )
    assert len(caught) == 1
    assert "Precision is ill-defined" in str(caught[0].message)
    assert "[1]" in str(caught[0].message)
    assert "Fix: pass zero_division=" in str(caught[0].message)


def test_the_report_does_not_warn_when_zero_division_is_given():
    """Choosing zero_division silences the warning."""
    y, p = [0, 1, 2, 2], [0, 0, 2, 2]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sq.metrics.classification_report(
            rel(pd.DataFrame({"y": y, "prediction": p})), "y", zero_division=0.0
        )


def test_the_report_takes_text_labels():
    """Labels are text in the label column, booleans as DuckDB renders them."""
    y, p = ["a", "b", "b", "a"], ["a", "b", "a", "a"]
    rows = _report_rows(
        sq.metrics.classification_report(
            rel(pd.DataFrame({"y": y, "prediction": p})), "y"
        )
    )
    want = _sk_report(y, p)
    assert rows["b"]["recall"] == want["b"]["recall"]
    flags = pd.DataFrame({"y": [True, False, True], "prediction": [True, True, True]})
    got = sq.metrics.classification_report(rel(flags), "y", zero_division=0.0)
    assert [r[0] for r in got.fetchall()][:2] == ["false", "true"]


def test_the_report_is_a_relation_unless_out_is_given():
    """The report is a relation, or what out names."""
    frame = rel(pd.DataFrame({"y": Y, "prediction": P}))
    assert isinstance(
        sq.metrics.classification_report(frame, "y"), duckdb.DuckDBPyRelation
    )
    out = sq.metrics.classification_report(frame, "y", out="pandas")
    assert isinstance(out, pd.DataFrame)


def test_the_report_refuses_what_precision_refuses():
    """A NULL label refuses, naming the report."""
    with pytest.raises(sq.errors.SqlearnError, match="classification_report"):
        sq.metrics.classification_report(
            rel(pd.DataFrame({"y": [0, None], "prediction": [0, 1]})), "y"
        )


def test_an_unknown_zero_division_refuses():
    """A zero_division scikit-learn does not take refuses."""
    with pytest.raises(sq.errors.SqlearnError, match="zero_division"):
        sq.metrics.classification_report(
            rel(pd.DataFrame({"y": Y, "prediction": P})), "y", zero_division=2
        )


@pytest.mark.parametrize(
    "labels",
    [
        [False, True],
        [0, 1, 2],
        [0.0, 1.0],
        [datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)],
        [datetime.datetime(2024, 1, 1, 12), datetime.datetime(2024, 2, 1, 13, 30)],
    ],
    ids=["bool", "int", "whole float", "date", "timestamp"],
)
def test_the_reports_label_text_is_the_confusion_matrixs_column_name(labels):
    """A label reads the same in both tables: the report's text, the matrix's name."""
    y = labels * 2
    p = labels[::-1] + labels
    frame = pd.DataFrame({"y": y, "prediction": p})
    matrix_columns = sq.metrics.confusion_matrix(rel(frame), "y").columns[1:]
    report = sq.metrics.classification_report(rel(frame), "y")
    texts = [r[0] for r in report.fetchall()][: len(labels)]
    assert texts == matrix_columns
