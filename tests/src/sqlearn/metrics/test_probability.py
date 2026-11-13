"""Tests of log_loss and roc_auc against scikit-learn."""

import warnings

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError, UndefinedMetricWarning
from sqlearn.metrics import MissingClassError

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


@pytest.mark.parametrize("bad", [1.2, -0.1])
def test_probability_metrics_refuse_a_probability_outside_zero_and_one(con, bad):
    """As scikit-learn 1.9.1, a probability above 1 or below 0 is refused."""
    y = np.array([0, 1, 1])
    proba = np.array([[0.5, 0.5], [0.3, bad], [0.4, 0.6]])
    for metric in (sq.metrics.log_loss, sq.metrics.roc_auc):
        with pytest.raises(
            SqlearnError, match=rf"'{PROBA}1' has 1 of 3 rows .* below 0 or above 1"
        ):
            metric.compute(proba_relation(con, y, proba), "y", classes=[0, 1])


def test_a_target_incomparable_with_the_classes_is_refused_with_a_fix():
    """The classes' comparison failure has the house Fix: and DuckDB's first line."""
    rel = connection().sql(
        f"SELECT DATE '2020-01-01' AS y, 0.3::DOUBLE AS {PROBA}0, "
        f"0.7::DOUBLE AS {PROBA}1"
    )
    with pytest.raises(sq.errors.SqlearnError, match=r"DuckDB cannot compare") as e:
        sq.metrics.log_loss.compute(rel, "y", classes=[0, 1])
    text = str(e.value)
    assert "Fix: cast one" in text
    assert "LINE" not in text
    assert "\n" not in text


def test_average_precision_matches_sklearn_on_two_classes(con):
    """Two classes, with ties: the second class's column, as proba[:, 1]."""
    y, proba = random_labels_and_probabilities(2, rows=400, ties=True)
    rel = proba_relation(con, y, proba)
    got = sq.metrics.average_precision.compute(rel, "y", classes=[0, 1])
    assert got == pytest.approx(average_precision_score(y, proba[:, 1]), rel=1e-12)


def test_average_precision_scores_pos_label_on_labels_one_and_two(con):
    """Classes [1, 2]: pos_label 1 is the first class, proba[:, 0]."""
    y, proba = random_labels_and_probabilities(2, rows=300, ties=False)
    rel = proba_relation(con, y + 1, proba)
    got = sq.metrics.average_precision.compute(rel, "y", classes=[1, 2])
    assert got == pytest.approx(average_precision_score(y + 1, proba[:, 0]), rel=1e-12)
    two = sq.metrics.average_precision(pos_label=2).compute(rel, "y", classes=[1, 2])
    expected = average_precision_score(y + 1, proba[:, 1], pos_label=2)
    assert two == pytest.approx(expected, rel=1e-12)


def test_average_precision_needs_pos_label_for_text_labels(con):
    """Text classes: pos_label=1 is none of them; a pos_label names a column."""
    y, proba = random_labels_and_probabilities(2, rows=200, ties=False)
    text = np.where(y == 1, "b", "a")
    rel = proba_relation(con, text, proba)
    with pytest.raises(SqlearnError, match=r"pos_label=1.*Fix: .*pos_label='b'"):
        sq.metrics.average_precision.compute(rel, "y", classes=["a", "b"])
    got = sq.metrics.average_precision(pos_label="b").compute(
        rel, "y", classes=["a", "b"]
    )
    expected = average_precision_score(text, proba[:, 1], pos_label="b")
    assert got == pytest.approx(expected, rel=1e-12)


def test_average_precision_matches_sklearn_on_three_classes(con):
    """More classes: each class against the rest, macro averaged."""
    y, proba = random_labels_and_probabilities(3, rows=400, ties=True)
    rel = proba_relation(con, y, proba)
    got = sq.metrics.average_precision.compute(rel, "y", classes=[0, 1, 2])
    assert got == pytest.approx(average_precision_score(y, proba), rel=1e-12)


def test_average_precision_refuses_pos_label_on_more_classes(con):
    """As scikit-learn, pos_label is fixed to 1 for more than two classes."""
    y, proba = random_labels_and_probabilities(3, rows=60, ties=False)
    rel = proba_relation(con, y, proba)
    with pytest.raises(SqlearnError, match=r"pos_label=2.*more than two.*Fix: "):
        sq.metrics.average_precision(pos_label=2).compute(rel, "y", classes=[0, 1, 2])


def test_no_positive_rows_give_zero_with_sklearns_warning(con):
    """No row of the scored class: 0.0 and a warning, as scikit-learn."""
    proba = np.array([[0.9, 0.1], [0.6, 0.4], [0.3, 0.7]])
    rel = proba_relation(con, np.array([0, 0, 0]), proba)
    with pytest.warns(UndefinedMetricWarning, match=r"No positive class.*Fix: "):
        got = sq.metrics.average_precision.compute(rel, "y", classes=[0, 1])
    assert got == 0.0


def test_no_negative_rows_give_one(con):
    """Every row of the scored class: 1.0, and no warning."""
    proba = np.array([[0.9, 0.1], [0.6, 0.4], [0.3, 0.7]])
    rel = proba_relation(con, np.array([1, 1, 1]), proba)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = sq.metrics.average_precision.compute(rel, "y", classes=[0, 1])
    assert got == 1.0


def test_a_class_missing_on_more_classes_is_a_missing_class_error(con):
    """With three classes, a class absent from the target has no answer."""
    y, proba = random_labels_and_probabilities(3, rows=60, ties=False)
    rel = proba_relation(con, np.where(y == 2, 1, y), proba)
    with pytest.raises(MissingClassError, match=r"class 2 has no row.*Fix: "):
        sq.metrics.average_precision.compute(rel, "y", classes=[0, 1, 2])


def test_average_precision_settings_are_pos_label_only():
    """The call takes pos_label, keeps the metric's name and says what it set."""
    metric = sq.metrics.average_precision(pos_label="b")
    assert (metric.name, metric.pos_label, repr(metric)) == (
        "average_precision",
        "b",
        "average_precision(pos_label='b')",
    )
    assert repr(sq.metrics.average_precision) == "average_precision"
    with pytest.raises(SqlearnError, match=r"no setting average=.*Fix: "):
        sq.metrics.average_precision(average="micro")
