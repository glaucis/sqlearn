"""Tests for the learning store and its keys."""

import gc
import weakref

from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._store import STORE, Entry, Store, step_key

DATA = ("table", "t", 1)
OTHER = ("table", "t", 2)


class MyImpute(sq.Step):
    """A step with a setting, to change between keys."""

    def __init__(self, cols=("a",), value="mean", keep=False, suffix=None):
        """Set the settings."""
        self.cols, self.value, self.keep, self.suffix = cols, value, keep, suffix


def _keys(data, fold, value):
    steps = [
        ("impute", MyImpute(value=value)),
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


class _V(sq.Step):
    """A step with one setting."""

    def __init__(self, v):
        """Set the setting."""
        self.v = v


_SOURCE = "class X(sq.Step):\n    def __init__(self, v=1):\n        self.v = v\n"


def _make():
    scope = {"sq": sq}
    exec(_SOURCE, scope)
    return scope["X"]


def test_same_named_classes_get_different_keys():
    """Same name and settings, different class objects: different keys."""
    a, b = _make(), _make()
    ka = step_key(DATA, None, [("x", a())], 0, frozenset())
    kb = step_key(DATA, None, [("x", b())], 0, frozenset())
    assert ka != kb
    assert ka == step_key(DATA, None, [("x", a())], 0, frozenset())


def test_true_and_one_get_different_keys():
    """A boolean and an integer setting do not share a key."""
    keys = {
        step_key(DATA, None, [("x", _V(v))], 0, frozenset()) for v in (True, 1, 1.0)
    }
    assert len(keys) == 3


class _Pick(sq.Step):
    """A step whose `k` chooses only its output (ADR 0056)."""

    output_settings = frozenset({"k"})

    def __init__(self, k, cols=("a",)):
        """Set the settings."""
        self.k, self.cols = k, cols


def test_a_setting_that_only_chooses_the_output_is_not_in_the_learn_key():
    """`k` leaves the step's own key; a step reading its output keeps it."""

    def keys(k):
        steps = [("pick", _Pick(k)), ("after", _V(1))]
        own = step_key(DATA, None, steps, 0, frozenset())
        later = step_key(DATA, None, steps, 1, frozenset({0}))
        return own, later

    (one, one_later), (two, two_later) = keys(1), keys(2)
    assert one == two
    assert one_later != two_later


def test_a_change_two_hops_up_reaches_the_last_key():
    """A to B to C: a change in A changes C's key (transitive depends_on)."""

    def key(value):
        steps = [("a", MyImpute(value=value)), ("b", _V(1)), ("c", _V(2))]
        return step_key(DATA, None, steps, 2, frozenset({0, 1}))

    assert key("mean") != key("median")


def test_the_resolved_inputs_are_in_the_key():
    """The same step reading other columns does not share a key."""
    steps = [("x", _V(1))]
    one = step_key(DATA, None, steps, 0, frozenset(), inputs=["plan"])
    two = step_key(DATA, None, steps, 0, frozenset(), inputs=["region", "plan"])
    assert one != two
    assert one == step_key(DATA, None, steps, 0, frozenset(), inputs=["plan"])


def test_redefining_a_lambda_relearns():
    """Two equal-looking lambdas are two function objects: two keys."""

    def key(step):
        return step_key(DATA, None, [("x", step)], 0, frozenset())

    one = sq.Step(apply=lambda x: x + 1, cols=["a"])
    two = sq.Step(apply=lambda x: x + 1, cols=["a"])
    assert key(one) != key(two)
    assert key(one) == key(one)


class Doubler:
    """A callable object with the default repr, which holds its address."""

    def __call__(self, x):
        """Double a column."""
        return x * 2


def test_a_callable_object_is_keyed_by_itself():
    """A setting whose repr is the default one (an address) is keyed by itself.

    The address may be reused once the object is collected, so a later
    object could share the repr and find the first one's entry; the key holds
    the object instead, which keeps it alive.
    """

    def key(fn):
        return step_key(
            DATA, None, [("x", sq.Step(apply=fn, cols=["a"]))], 0, frozenset()
        )

    first = Doubler()
    kept = key(first)
    held = weakref.ref(first)
    del first
    gc.collect()
    assert held() is not None
    assert kept != key(Doubler())
    assert kept == key(held())


STABLE = ("file", (("/data/c.parquet", 10, 1),))
ORIGIN = ("file", "/data", "c.parquet")


def test_a_miss_finds_an_entry_put_under_the_stable_key():
    """A live key's miss finds the entry put under its stable key, once."""
    store = Store()
    live = _keys(DATA, None, "mean")[0]
    entry = Entry({"mean": {"a": 1.0}}, ["a"], "")
    store.put_stable((STABLE, *live[1:]), entry)
    assert not store.learns
    assert store.get(live) is None
    assert store.get(live, stable=OTHER) is None
    assert store.get(live, stable=STABLE) is entry
    # Filed under the live key too: found again without the stable key.
    assert store.get(live) is entry
    assert not store.learns
    store.clear()
    assert store.get(live, stable=STABLE) is None


def test_a_changed_source_is_said_once():
    """The saved file is named when the same source changed, once."""
    store = Store()
    store.remember_saved(ORIGIN, STABLE, "p.json")
    assert store.changed_since_saved(None, STABLE) is None
    assert store.changed_since_saved(("file", "/data", "d.parquet"), OTHER) is None
    assert store.changed_since_saved(ORIGIN, OTHER) == ("p.json", STABLE)
    assert store.changed_since_saved(ORIGIN, OTHER) is None


def test_an_unchanged_source_is_not_said_and_forgotten():
    """The first learn of an unchanged source says nothing, and later ones neither."""
    store = Store()
    store.remember_saved(ORIGIN, STABLE, "p.json")
    assert store.changed_since_saved(ORIGIN, STABLE) is None
    assert store.changed_since_saved(ORIGIN, OTHER) is None
    store.remember_saved(ORIGIN, STABLE, "p.json")
    store.clear()
    assert store.changed_since_saved(ORIGIN, OTHER) is None
