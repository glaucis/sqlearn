"""Tests of models: the wrapper, copying it, and handing data over."""

import sys

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._model import Model, as_model, copy_model, hand_over


class Plain:
    """A model without get_params: copied whole."""

    def __init__(self) -> None:
        self.weights = [1.0, 2.0]

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return the first column."""
        return x[:, 0]


def test_model_is_exported_with_a_deterministic_repr():
    """`sq.Model` shows the estimator's own repr and the feed."""
    model = sq.Model(LogisticRegression(C=0.1))
    assert sq.Model is Model
    assert repr(model) == "Model(LogisticRegression(C=0.1), feed='numpy')"
    assert repr(model) == repr(sq.Model(LogisticRegression(C=0.1)))


def test_as_model_wraps_a_plain_estimator_and_keeps_a_model():
    """A plain estimator is wrapped; a Model is passed through as it is."""
    estimator = LogisticRegression()
    wrapped = as_model(estimator)
    assert isinstance(wrapped, Model)
    assert wrapped.estimator is estimator
    assert wrapped.feed == "numpy"
    assert as_model(wrapped) is wrapped


def test_an_object_without_fit_and_predict_is_not_a_model():
    """A model needs fit and predict; the message names what is missing."""
    with pytest.raises(sq.errors.SqlearnError, match="predict"):
        sq.Model(type("OnlyFit", (), {"fit": lambda self, x, y: self})())


def test_copy_model_keeps_settings():
    """A copy holds a new, unfitted estimator with the same settings and feed."""
    model = sq.Model(LogisticRegression(C=0.1, max_iter=55))
    model.estimator.fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
    copy = copy_model(model)
    assert copy is not model
    assert copy.estimator is not model.estimator
    assert copy.estimator.get_params() == model.estimator.get_params()
    assert copy.feed == model.feed
    assert not hasattr(copy.estimator, "coef_")
    assert repr(copy) == repr(model)


def test_copy_model_without_get_params_deep_copies():
    """A model without get_params is copied with copy.deepcopy."""
    model = sq.Model(Plain())
    copy = copy_model(model)
    assert copy.estimator is not model.estimator
    assert copy.estimator.weights == [1.0, 2.0]
    assert copy.estimator.weights is not model.estimator.weights


def test_hand_over_gives_a_float_matrix_in_column_order():
    """numpy: a 2-D float64 array, columns in order, NULL as NaN."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1, 2.5, true), (NULL, 4.0, false)) t(a, b, c)"
    )
    x = hand_over(rel, "numpy")
    assert isinstance(x, np.ndarray)
    assert x.dtype == np.float64
    assert x.shape == (2, 3)
    np.testing.assert_array_equal(x, [[1.0, 2.5, 1.0], [np.nan, 4.0, 0.0]])


def test_hand_over_refuses_a_column_that_is_not_a_number():
    """Text left in the data is named, with the steps that encode it."""
    rel = connection().sql("SELECT 1.0 AS a, 'x' AS city")
    with pytest.raises(sq.errors.SqlearnError, match=r"'city'.*OneHot"):
        hand_over(rel, "numpy")


def test_feed_other_than_numpy_points_to_issue_21():
    """Any other feed is not built yet, and the message says where it is planned."""
    rel = connection().sql("SELECT 1.0 AS a")
    url = "https://github.com/glaucis/sqlearn/issues/21"
    with pytest.raises(sq.errors.SqlearnError, match=url):
        hand_over(rel, "arrow")
    with pytest.raises(sq.errors.SqlearnError, match=url):
        sq.Model(LogisticRegression(), feed="arrow")


def test_missing_numpy_says_to_install_it(monkeypatch):
    """Without numpy, the numpy hand-over says to install it."""
    monkeypatch.setitem(sys.modules, "numpy", None)
    rel = connection().sql("SELECT 1.0 AS a")
    with pytest.raises(sq.errors.SqlearnError, match="install numpy"):
        hand_over(rel, "numpy")


class Settings:
    """A model whose get_params takes no argument, holding a nested model."""

    def __init__(self, alpha=1.0, inner=None, kind=None):
        self.alpha = alpha
        self.inner = inner
        self.kind = kind

    def get_params(self):
        """Return the settings."""
        return {"alpha": self.alpha, "inner": self.inner, "kind": self.kind}

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return the features themselves: two values per row."""
        return x


def test_copy_model_rebuilds_from_settings_and_copies_nested_models():
    """get_params without `deep` is called plainly; nested models are rebuilt."""
    inner = LogisticRegression(C=3.0).fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
    model = sq.Model(Settings(alpha=0.5, inner=inner, kind=LogisticRegression))
    copy = copy_model(model)
    assert copy.estimator.alpha == 0.5
    assert copy.estimator.kind is LogisticRegression
    assert copy.estimator.inner is not inner
    assert copy.estimator.inner.C == 3.0
    assert not hasattr(copy.estimator.inner, "coef_")


def test_predictions_must_be_one_value_per_row():
    """A model returning a table instead of one value per row is refused."""
    frame = connection().sql("SELECT * FROM (VALUES (1.0, 2.0, 0)) t(a, b, y)")
    pipe = sq.Pipeline([("model", Settings())]).train(frame, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="one value per row"):
        pipe.predict(frame)
