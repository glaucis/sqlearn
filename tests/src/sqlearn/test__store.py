"""Tests for the learning store and its keys."""

from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._store import STORE, Entry, Store, step_key

DATA = ("table", "t", 1)
OTHER = ("table", "t", 2)


class MyImpute(sq.Step):
    """A step with a setting, to change between keys."""

    def __init__(self, cols=("a",), strategy="mean", keep=False, suffix=None):
        """Set the settings."""
        self.cols, self.strategy, self.keep, self.suffix = cols, strategy, keep, suffix


def _keys(data, fold, strategy):
    steps = [
        ("impute", MyImpute(strategy=strategy)),
        ("onehot", MyEncoder()),
        ("scale", MyScale(cols=("a",))),
    ]
    deps = [frozenset(), frozenset(), frozenset({0})]
    return [step_key(data, fold, steps, i, deps[i]) for i in range(3)]


def test_a_changed_setting_misses_and_others_hit():
    """A changed setting changes its key and its readers, not the others."""
    mean, median = _keys(DATA, None, "mean"), _keys(DATA, None, "median")
    assert mean[0] != median[0]
    assert mean[2] != median[2]
    assert mean[1] == median[1]


def test_another_fold_misses():
    """Another fold has another key."""
    assert _keys(DATA, (10, 0, 0), "mean")[1] != _keys(DATA, (10, 0, 1), "mean")[1]


def test_other_data_misses():
    """Other data has another key."""
    assert _keys(DATA, None, "mean")[1] != _keys(OTHER, None, "mean")[1]


def test_get_put_and_learns():
    """Put stores an entry and counts one learn."""
    store = Store()
    key = _keys(DATA, None, "mean")[0]
    assert store.get(key) is None
    store.put(key, Entry({"mean": {"a": 1.0}}, ["a"], "SELECT 1"))
    entry = store.get(key)
    assert entry is not None
    assert entry.columns == ["a"]
    assert len(store) == 1
    assert store.learns["impute"] == 1


def test_size_is_reported():
    """The size estimate is positive once something is stored."""
    key = _keys(DATA, None, "mean")[0]
    STORE.put(key, Entry({"mean": {"a": 1.0}}, ["a"], "SELECT 1"))
    assert STORE.size_bytes() > 0
