"""Tests of the curves: the ROC curve against scikit-learn's."""

import math
import warnings

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import precision_recall_curve as sk_pr_curve
from sklearn.metrics import roc_curve as sk_roc_curve

import sqlearn as sq
from sqlearn._config import connection


def rel(frame):
    """Return a DuckDB relation over `frame`."""
    return connection().from_df(frame)


def same(got, expected):
    """Say whether two arrays are equal, NaN equal to NaN."""
    return np.array_equal(
        np.asarray(got, float), np.asarray(expected, float), equal_nan=True
    )


@pytest.mark.parametrize("drop_intermediate", [True, False])
def test_roc_curve_matches_sklearn(drop_intermediate):
    """Every column is scikit-learn's, the first threshold infinite."""
    y = [0, 0, 1, 1, 0, 1, 1, 0]
    s = [0.1, 0.4, 0.35, 0.8, 0.4, 0.8, 0.9, 0.2]
    out = sq.metrics.roc_curve(
        rel(pd.DataFrame({"y": y, "s": s})),
        "y",
        "s",
        drop_intermediate=drop_intermediate,
        out="numpy",
    )
    fpr, tpr, threshold = sk_roc_curve(y, s, drop_intermediate=drop_intermediate)
    assert list(out) == ["fpr", "tpr", "threshold"]
    assert same(out["fpr"], fpr)
    assert same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)
    assert math.isinf(out["threshold"][0])


def test_roc_curve_drops_only_equal_steps():
    """Only a point with equal steps on both sides goes, as 1.9.1."""
    y = [1, 1, 1, 1, 0, 0]
    s = [0.9, 0.8, 0.8, 0.7, 0.2, 0.1]
    out = sq.metrics.roc_curve(
        rel(pd.DataFrame({"y": y, "s": s})), "y", "s", out="numpy"
    )
    assert out["tpr"].tolist() == [0.0, 0.25, 0.75, 1.0, 1.0]
    assert out["fpr"].tolist() == [0.0, 0.0, 0.0, 0.0, 1.0]


def test_every_score_tied_gives_two_points():
    """One distinct score gives the point at infinity and one more."""
    y, s = [1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]
    out = sq.metrics.roc_curve(
        rel(pd.DataFrame({"y": y, "s": s})), "y", "s", out="numpy"
    )
    fpr, tpr, threshold = sk_roc_curve(y, s)
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)
    assert len(out["fpr"]) == 2


def test_integer_and_negative_scores_are_thresholds():
    """An integer score is a threshold as a double; a negative one is kept."""
    y, s = [0, 1, 1, 0, 1], [-3, 2, -1, -3, 7]
    out = sq.metrics.roc_curve(
        rel(pd.DataFrame({"y": y, "s": s})),
        "y",
        "s",
        drop_intermediate=False,
        out="numpy",
    )
    fpr, tpr, threshold = sk_roc_curve(y, s, drop_intermediate=False)
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)
    assert out["threshold"].dtype == np.float64


@pytest.mark.parametrize(
    "labels", [[0, 1], [-1, 1], [0], [1], [-1], [False, True], [0.0, 1.0]]
)
def test_pos_label_left_out_takes_sklearns_labels(labels):
    """The labels scikit-learn accepts without pos_label are accepted."""
    y = [labels[i % len(labels)] for i in range(6)]
    s = [0.1, 0.9, 0.4, 0.35, 0.8, 0.2]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fpr, tpr, threshold = sk_roc_curve(y, s)
        out = sq.metrics.roc_curve(
            rel(pd.DataFrame({"y": y, "s": s})), "y", "s", out="numpy"
        )
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)


def test_other_labels_need_pos_label():
    """Text labels refuse without pos_label, and work with it."""
    y, s = ["a", "b", "b", "a"], [0.1, 0.8, 0.4, 0.5]
    frame = rel(pd.DataFrame({"y": y, "s": s}))
    with pytest.raises(sq.errors.SqlearnError, match=r"pos_label") as info:
        sq.metrics.roc_curve(frame, "y", "s")
    assert "Fix:" in str(info.value)
    out = sq.metrics.roc_curve(frame, "y", "s", pos_label="b", out="numpy")
    fpr, tpr, threshold = sk_roc_curve(y, s, pos_label="b")
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)


def test_pos_label_picks_one_class_of_many():
    """Three classes work with a pos_label, as 1.9.1: that class against the rest."""
    y, s = [0, 1, 2, 1, 2, 0], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    out = sq.metrics.roc_curve(
        rel(pd.DataFrame({"y": y, "s": s})), "y", "s", pos_label=2, out="numpy"
    )
    fpr, tpr, threshold = sk_roc_curve(y, s, pos_label=2)
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)


def test_more_than_two_classes_need_pos_label():
    """Three classes without pos_label refuse."""
    frame = rel(pd.DataFrame({"y": [0, 1, 2], "s": [0.1, 0.2, 0.3]}))
    with pytest.raises(sq.errors.SqlearnError, match=r"pos_label"):
        sq.metrics.roc_curve(frame, "y", "s")


def test_no_negative_rows_warn_and_give_nan_fpr():
    """With no negative row, fpr is NaN and a warning says so."""
    frame = rel(pd.DataFrame({"y": [1, 1], "s": [0.5, 0.4]}))
    with pytest.warns(sq.errors.UndefinedMetricWarning, match="negative"):
        out = sq.metrics.roc_curve(frame, "y", "s", out="numpy")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fpr, tpr, threshold = sk_roc_curve([1, 1], [0.5, 0.4])
    assert same(out["fpr"], fpr) and same(out["tpr"], tpr)
    assert same(out["threshold"], threshold)


def test_no_positive_rows_warn_and_give_nan_tpr():
    """With no positive row, tpr is NaN and a warning says so."""
    frame = rel(pd.DataFrame({"y": [0, 0], "s": [0.5, 0.4]}))
    with pytest.warns(sq.errors.UndefinedMetricWarning, match="positive"):
        out = sq.metrics.roc_curve(frame, "y", "s", out="numpy")
    assert np.isnan(out["tpr"]).all()
    assert out["fpr"].tolist() == [0.0, 0.5, 1.0]


@pytest.mark.parametrize("bad", ["NULL", "'NaN'::DOUBLE", "'inf'::DOUBLE"])
def test_a_curve_refuses_a_missing_or_infinite_score(bad):
    """A NULL, NaN or infinite score refuses, with a Fix line."""
    frame = connection().sql(
        f"SELECT * FROM (VALUES (0, 0.1::DOUBLE), (1, {bad})) t(y, s)"
    )
    with pytest.raises(sq.errors.SqlearnError, match=r"column 's'") as info:
        sq.metrics.roc_curve(frame, "y", "s")
    assert "Fix:" in str(info.value)


def test_a_curve_refuses_a_text_score():
    """A score that is not a number refuses."""
    frame = connection().sql("SELECT * FROM (VALUES (0, 'a'), (1, 'b')) t(y, s)")
    with pytest.raises(sq.errors.SqlearnError, match=r"column 's'"):
        sq.metrics.roc_curve(frame, "y", "s")


def test_a_curve_refuses_a_missing_column_and_no_rows():
    """A column not in the relation, and no rows, refuse."""
    frame = connection().sql("SELECT * FROM (VALUES (0, 0.1)) t(y, s)")
    with pytest.raises(sq.errors.SqlearnError, match=r"'z'"):
        sq.metrics.roc_curve(frame, "y", "z")
    with pytest.raises(sq.errors.SqlearnError, match=r"no rows"):
        sq.metrics.roc_curve(frame.filter("y > 5"), "y", "s")


def test_a_pos_label_of_another_kind_refuses():
    """A pos_label DuckDB cannot compare with the labels refuses."""
    frame = connection().sql("SELECT * FROM (VALUES (0, 0.1), (1, 0.2)) t(y, s)")
    with pytest.raises(sq.errors.SqlearnError, match=r"pos_label"):
        sq.metrics.roc_curve(frame, "y", "s", pos_label="b")


def test_a_curve_over_many_rows_is_a_relation():
    """Two million rows give a lazy relation of at most 1,001 points."""
    big = connection().sql(
        "SELECT i % 2 AS y, hash(i) % 1000 AS s FROM range(2000000) t(i)"
    )
    curve = sq.metrics.roc_curve(big, "y", "s")
    assert isinstance(curve, duckdb.DuckDBPyRelation)
    assert curve.count("*").fetchall()[0][0] <= 1001


@pytest.mark.parametrize("drop_intermediate", [False, True])
def test_precision_recall_curve_matches_sklearn(drop_intermediate):
    """Every column is scikit-learn's; the last threshold is NULL."""
    y = [0, 0, 1, 1, 0, 1, 1, 0, 1, 1]
    s = [0.1, 0.4, 0.35, 0.8, 0.4, 0.8, 0.9, 0.2, 0.7, 0.6]
    out = sq.metrics.precision_recall_curve(
        rel(pd.DataFrame({"y": y, "s": s})),
        "y",
        "s",
        drop_intermediate=drop_intermediate,
        out="numpy",
    )
    precision, recall, threshold = sk_pr_curve(
        y, s, drop_intermediate=drop_intermediate
    )
    assert list(out) == ["precision", "recall", "threshold"]
    assert same(out["precision"], precision)
    assert same(out["recall"], recall)
    assert same(out["threshold"][:-1], threshold)
    assert out["threshold"][-1] is np.ma.masked


def test_precision_recall_curve_rows_keep_sklearns_order():
    """Fetched rows run thresholds increasing, then (1, 0, NULL)."""
    frame = rel(pd.DataFrame({"y": [0, 1, 1, 0], "s": [0.1, 0.8, 0.4, 0.4]}))
    rows = sq.metrics.precision_recall_curve(frame, "y", "s").fetchall()
    assert [r[2] for r in rows] == [0.1, 0.4, 0.8, None]
    assert rows[-1] == (1.0, 0.0, None)


def test_precision_recall_curve_drops_points_with_equal_tps_either_side():
    """Only a point whose true positives equal both neighbours' goes."""
    y = [1, 1, 0, 0, 0, 1]
    s = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]
    out = sq.metrics.precision_recall_curve(
        rel(pd.DataFrame({"y": y, "s": s})),
        "y",
        "s",
        drop_intermediate=True,
        out="numpy",
    )
    precision, recall, threshold = sk_pr_curve(y, s, drop_intermediate=True)
    assert len(threshold) < 6
    assert same(out["precision"], precision) and same(out["recall"], recall)


def test_no_positive_rows_warn_and_give_recall_one():
    """With no positive row recall is 1 and precision 0, then (1, 0)."""
    frame = rel(pd.DataFrame({"y": [0, 0], "s": [0.5, 0.4]}))
    with pytest.warns(UserWarning, match="No positive class found in y_true"):
        out = sq.metrics.precision_recall_curve(frame, "y", "s", out="numpy")
    assert out["recall"].tolist() == [1.0, 1.0, 0.0]
    assert out["precision"].tolist() == [0.0, 0.0, 1.0]


def test_no_negative_rows_give_precision_one_without_a_warning():
    """With no negative row precision is 1, and nothing is raised."""
    frame = rel(pd.DataFrame({"y": [1, 1], "s": [0.5, 0.4]}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = sq.metrics.precision_recall_curve(frame, "y", "s", out="numpy")
    precision, recall, _ = sk_pr_curve([1, 1], [0.5, 0.4])
    assert same(out["precision"], precision) and same(out["recall"], recall)


def test_the_precision_recall_curve_takes_text_labels_with_pos_label():
    """A text label and one class of three, each against the rest."""
    y = ["no", "yes", "yes", "maybe", "no"]
    s = [0.1, 0.9, 0.5, 0.5, 0.3]
    out = sq.metrics.precision_recall_curve(
        rel(pd.DataFrame({"y": y, "s": s})), "y", "s", pos_label="yes", out="numpy"
    )
    precision, recall, _ = sk_pr_curve(y, s, pos_label="yes")
    assert same(out["precision"], precision) and same(out["recall"], recall)
    with pytest.raises(sq.errors.SqlearnError, match=r"pos_label"):
        sq.metrics.precision_recall_curve(rel(pd.DataFrame({"y": y, "s": s})), "y", "s")


@pytest.mark.parametrize("labels", [[0, 1, 1, 0], [0, 0, 0, 0], [1, 1, 1, 1]])
def test_the_curves_columns_are_double_in_every_case(labels):
    """Both curves' columns are DOUBLE with both, no positive or no negative."""
    frame = rel(pd.DataFrame({"y": labels, "s": [0.1, 0.4, 0.35, 0.8]}))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for curve in (sq.metrics.roc_curve, sq.metrics.precision_recall_curve):
            got = curve(frame, "y", "s")
            assert [str(t) for t in got.types] == ["DOUBLE"] * 3
            assert all(
                type(v) is float for row in got.fetchall() for v in row if v is not None
            )
