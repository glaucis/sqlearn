"""Tests of ``sq.select`` and its shortcuts."""

import sqlearn as sq
from sqlearn._store import step_key
from sqlearn.feature_selection import VarianceThreshold

DATA = ("table", "t", 1)


def test_the_shortcut_is_the_general_form():
    """sq.select.variance builds the step the class builds: repr, settings, key."""
    short = sq.select.variance(threshold=0.5)
    general = VarianceThreshold(threshold=0.5)
    assert type(short) is VarianceThreshold
    assert repr(short) == repr(general) == "sq.select.variance(threshold=0.5)"
    assert short.settings() == general.settings()

    def key(step):
        return step_key(DATA, None, [("variance", step)], 0, frozenset())

    assert key(short) == key(general)
