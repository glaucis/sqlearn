"""Tests of ``sq.select`` and its shortcuts."""

import pytest

import sqlearn as sq
from sqlearn._store import step_key
from sqlearn.errors import SqlearnError
from sqlearn.feature_selection import SelectKBest, SelectPercentile, VarianceThreshold

DATA = ("table", "t", 1)


def key(name, step):
    """Return the store key of a one-step pipeline of `step`."""
    return step_key(DATA, None, [(name, step)], 0, frozenset())


def test_the_shortcut_is_the_general_form():
    """Each shortcut builds the step the class and the general form build."""
    cases = [
        (
            "variance",
            sq.select.variance(threshold=0.5),
            sq.select(method="variance", threshold=0.5),
            VarianceThreshold(threshold=0.5),
            "sq.select.variance(threshold=0.5)",
        ),
        (
            "best",
            sq.select.best("a", "b", k=2, score="chi2"),
            sq.select("a", "b", method="best", k=2, score="chi2"),
            SelectKBest(k=2, score="chi2", cols=["a", "b"]),
            "sq.select.best(k=2, score='chi2', cols=['a', 'b'])",
        ),
        (
            "percentile",
            sq.select.percentile(percentile=30, score="f_regression"),
            sq.select(method="percentile", percentile=30, score="f_regression"),
            SelectPercentile(percentile=30, score="f_regression"),
            "sq.select.percentile(percentile=30, score='f_regression')",
        ),
    ]
    for name, short, general, cls, text in cases:
        assert type(short) is type(general) is type(cls)
        assert repr(short) == repr(general) == repr(cls) == text
        assert short.settings() == general.settings() == cls.settings()
        assert key(name, short) == key(name, general) == key(name, cls)


def test_the_general_form_defaults_to_variance():
    """Called with no method, it is the variance selector."""
    assert repr(sq.select()) == "sq.select.variance()"


@pytest.mark.parametrize(
    "call",
    [
        lambda: sq.select(method="nope"),
        lambda: sq.select(method="variance", k=3),
        lambda: sq.select(method="variance", score="chi2"),
        lambda: sq.select(method="best", threshold=0.1),
        lambda: sq.select(method="best", percentile=10),
        lambda: sq.select(method="percentile", k=3),
        lambda: sq.select(method="percentile", threshold=0.1),
    ],
)
def test_the_general_form_refuses_a_setting_of_another_method(call):
    """A setting that does not belong to the method is refused, with Why and Fix."""
    with pytest.raises(SqlearnError, match=r"Why:.*Fix:"):
        call()
