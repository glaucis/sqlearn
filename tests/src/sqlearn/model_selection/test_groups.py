"""Tests of the search's groups, ``sq.search`` and ``sq.folds``."""

from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn.model_selection import KFold, Range, Search


def test_search_is_a_callable_group():
    """`sq.search` builds a `Search` and holds `grid` and `range`."""
    pipe = sq.Pipeline([("model", LogisticRegression())])
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    assert isinstance(search, Search)
    assert repr(sq.search) == "sq.search"
    assert sq.search.grid().knows_all
    assert sq.search.range(0.01, 10, log=True) == Range(0.01, 10, True)


def test_folds_group_builds_kfold():
    """`sq.folds.kfold` builds a `KFold`."""
    assert sq.folds.kfold(3, seed=1) == KFold(3, seed=1)
    assert "kfold" in dir(sq.folds)
    assert repr(sq.folds) == "sq.folds"


def test_search_lists_its_shortcuts():
    """`dir(sq.search)` names its shortcuts."""
    assert {"grid", "range"} <= set(dir(sq.search))
