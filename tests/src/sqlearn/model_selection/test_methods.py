"""Tests of the methods: the grid, ranges, and ask and tell."""

import pytest
from sklearn.model_selection import ParameterGrid

import sqlearn as sq
from sqlearn.model_selection.methods import Method, Range


def asked(method, space):
    """Start a method on a space and ask until it ends."""
    method.start(space, maximize=True)
    out = []
    while (params := method.ask()) is not None:
        out.append(params)
    return out


def test_grid_expands_as_parameter_grid():
    """Keys sorted, the last varying fastest; a list of grids one after another."""
    space = [
        {"model__C": [0.1, 1, 10], "impute__value": ["median", "mean"]},
        {"model": ["a", "b"]},
    ]
    assert asked(sq.search.grid(), space) == list(ParameterGrid(space))


def test_an_empty_grid_is_one_trial():
    """No settings to vary: one trial, with the pipeline's own settings."""
    assert asked(sq.search.grid(), [{}]) == [{}]


def test_grid_knows_all_and_records_scores():
    """Grid knows its settings up front; tell records each score."""
    grid = sq.search.grid()
    assert grid.knows_all
    assert isinstance(grid, Method)
    settings = asked(grid, [{"a": [1, 2]}])
    grid.tell(settings[0], 0.5)
    assert grid.scores_ == [({"a": 1}, 0.5)]
    assert repr(grid) == "Grid()"


def test_range_given_to_grid_is_refused():
    """A range has no list of values to try: grid names the setting."""
    r = sq.search.range(0.01, 10, log=True)
    assert r == Range(0.01, 10, log=True)
    with pytest.raises(sq.errors.SqlearnError, match=r"'model__C'.*sq\.search\.range"):
        sq.search.grid().start([{"model__C": r}], maximize=True)


def test_a_single_value_is_refused():
    """Grid wants a list of values per setting, as scikit-learn's grid does."""
    with pytest.raises(sq.errors.SqlearnError, match=r"'model__C'.*\[1\.0\]"):
        sq.search.grid().start([{"model__C": 1.0}], maximize=True)
    with pytest.raises(sq.errors.SqlearnError, match=r"'model__C'.*no value"):
        sq.search.grid().start([{"model__C": []}], maximize=True)


def test_range_refuses_low_above_high_and_log_from_zero():
    """A range runs from low to high; a log range starts above zero."""
    with pytest.raises(sq.errors.SqlearnError, match="low"):
        sq.search.range(2, 1)
    with pytest.raises(sq.errors.SqlearnError, match="log"):
        sq.search.range(0, 1, log=True)
