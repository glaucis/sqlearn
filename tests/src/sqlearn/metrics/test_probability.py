"""Tests of log_loss and roc_auc against scikit-learn."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import log_loss, roc_auc_score

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError

PROBA = "__sqlearn_proba_"


@pytest.fixture
def con():
    """Return sqlearn's connection."""
    return connection()


def random_labels_and_probabilities(classes, rows, *, ties):
    """Return labels 0..classes-1 and rows of class probabilities summing to 1.

    With `ties`, each row's probabilities are small whole weights over their
    sum, so many rows share a score.
    """
    rng = np.random.default_rng(classes)
    y = np.concatenate([np.arange(classes), rng.integers(classes, size=rows - classes)])
    if ties:
        weights = rng.integers(1, 5, size=(rows, classes)).astype(float)
    else:
        weights = rng.random(size=(rows, classes))
    return y, weights / weights.sum(axis=1, keepdims=True)


def proba_relation(con, y, proba, target="y"):
    """Return a relation of the labels and one column per class's probability."""
    frame = pd.DataFrame({target: y})
    for j in range(proba.shape[1]):
        frame[f"{PROBA}{j}"] = proba[:, j]
    return con.from_df(frame)


def test_log_loss_and_roc_auc_match_scikit_learn_binary_and_multiclass(con):
    """Both metrics match scikit-learn to 12 digits, for 2 and 4 classes, with ties."""
    for classes in (2, 4):
        y, proba = random_labels_and_probabilities(classes, rows=400, ties=True)
        rel = proba_relation(con, y, proba)
        assert sq.metrics.log_loss.compute(
            rel, "y", classes=list(range(classes))
        ) == pytest.approx(log_loss(y, proba), rel=1e-12)
        sk_auc = roc_auc_score(
            y,
            proba[:, 1] if classes == 2 else proba,
            multi_class="ovr",
            average="macro",
        )
        assert sq.metrics.roc_auc.compute(
            rel, "y", classes=list(range(classes))
        ) == pytest.approx(sk_auc, rel=1e-12)


def test_the_direction_and_method_of_each_metric():
    """log_loss is better lower, roc_auc higher; both read predict_proba."""
    assert not sq.metrics.log_loss.greater_is_better
    assert sq.metrics.roc_auc.greater_is_better
    assert sq.metrics.log_loss.needs == "predict_proba"
    assert sq.metrics.roc_auc.needs == "predict_proba"
    assert sq.metrics.accuracy.needs == "predict"


def test_log_loss_clips_certain_probabilities_as_scikit_learn(con):
    """A probability of 0 or 1 is clipped to [eps, 1 - eps], so no loss is infinite."""
    y = np.array([0, 1, 1, 0])
    proba = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])
    got = sq.metrics.log_loss.compute(
        proba_relation(con, y, proba), "y", classes=[0, 1]
    )
    assert got == pytest.approx(log_loss(y, proba), rel=1e-12)


def test_text_classes_follow_the_order_given(con):
    """The i-th probability column belongs to the i-th class, whatever its label."""
    y = np.array(["no", "yes", "yes", "no", "yes"])
    proba = np.array([[0.8, 0.2], [0.3, 0.7], [0.6, 0.4], [0.9, 0.1], [0.2, 0.8]])
    rel = proba_relation(con, y, proba)
    assert sq.metrics.log_loss.compute(
        rel, "y", classes=["no", "yes"]
    ) == pytest.approx(log_loss(y, proba, labels=["no", "yes"]), rel=1e-12)
    assert sq.metrics.roc_auc.compute(rel, "y", classes=["no", "yes"]) == pytest.approx(
        roc_auc_score(y, proba[:, 1]), rel=1e-12
    )


def test_a_probability_metric_needs_the_classes(con):
    """Without the model's classes the columns cannot be matched to labels."""
    y, proba = random_labels_and_probabilities(2, rows=10, ties=False)
    with pytest.raises(SqlearnError, match="classes"):
        sq.metrics.log_loss.compute(proba_relation(con, y, proba), "y")


def test_a_label_outside_the_classes_is_refused(con):
    """A target the model has no probability for cannot be scored."""
    y = np.array([0, 1, 2])
    proba = np.array([[0.5, 0.5]] * 3)
    for metric in (sq.metrics.log_loss, sq.metrics.roc_auc):
        with pytest.raises(SqlearnError, match="none of the classes"):
            metric.compute(proba_relation(con, y, proba), "y", classes=[0, 1])


def test_roc_auc_of_one_class_is_refused(con):
    """With every target one class, there is no pair to rank: refused."""
    y = np.array([1, 1, 1])
    proba = np.array([[0.2, 0.8], [0.4, 0.6], [0.1, 0.9]])
    with pytest.raises(SqlearnError, match="class 0"):
        sq.metrics.roc_auc.compute(proba_relation(con, y, proba), "y", classes=[0, 1])


def test_probability_metrics_refuse_missing_values_and_no_rows(con):
    """NULL, NaN and an empty relation have no score."""
    y = np.array([0, 1])
    for metric in (sq.metrics.log_loss, sq.metrics.roc_auc):
        empty = proba_relation(con, y[:0], np.zeros((0, 2)))
        with pytest.raises(SqlearnError, match="no rows"):
            metric.compute(empty, "y", classes=[0, 1])
        nan = con.sql(
            f"SELECT * FROM (VALUES (0, 0.5, 0.5), (1, 'NaN'::DOUBLE, 0.5)) "
            f't(y, "{PROBA}0", "{PROBA}1")'
        )
        with pytest.raises(SqlearnError, match="NaN"):
            metric.compute(nan, "y", classes=[0, 1])
        null = con.sql(
            f"SELECT * FROM (VALUES (0, 0.5, 0.5), (1, NULL, 0.5)) "
            f't(y, "{PROBA}0", "{PROBA}1")'
        )
        with pytest.raises(SqlearnError, match="NULL"):
            metric.compute(null, "y", classes=[0, 1])
