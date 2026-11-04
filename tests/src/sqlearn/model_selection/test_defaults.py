"""Tests of the default search spaces."""

import numpy as np
from sklearn.linear_model import LogisticRegression

from sqlearn.model_selection.defaults import DEFAULT_SPACES, default_space, hint


def test_logistic_regression_c_is_logspace_to_five_figures():
    """C: numpy.logspace(-3, 2, 7), five significant figures."""
    space = DEFAULT_SPACES["sklearn", "LogisticRegression"]
    expected = [float(f"{v:.5g}") for v in np.logspace(-3, 2, 7)]
    assert space == {"C": expected}
    assert space["C"] == [0.001, 0.0068129, 0.046416, 0.31623, 2.1544, 14.678, 100.0]


def test_every_default_names_settings_the_model_has():
    """Each entry's settings exist on the model it is for."""
    models = {("sklearn", "LogisticRegression"): LogisticRegression()}
    assert set(models) == set(DEFAULT_SPACES)
    for key, space in DEFAULT_SPACES.items():
        assert set(space) <= set(models[key].get_params())


def test_default_space_is_looked_up_by_package_and_class():
    """The top-level package of the model's module and its class name."""
    assert (
        default_space(LogisticRegression())
        == DEFAULT_SPACES["sklearn", "LogisticRegression"]
    )
    assert default_space(object()) is None


def test_hint_describes_the_space():
    """The hint says the range, the scale and the number of values."""
    text = hint("LogisticRegression", DEFAULT_SPACES["sklearn", "LogisticRegression"])
    assert text == "LogisticRegression: C in [0.001, 100], log scale, 7 values"
    assert hint("M", {"k": [1, 2, 4, 5]}) == "M: k in [1, 5], 4 values"
    assert hint("M", {"k": [-1, 1, 2]}) == "M: k in [-1, 2], 3 values"
