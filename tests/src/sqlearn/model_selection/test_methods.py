"""Tests of the methods: the grid, ranges, and ask and tell."""

import json

import pytest
from search_data_for_tests import customers, slice_pipe
from sklearn.model_selection import ParameterGrid

import sqlearn as sq
from sqlearn.errors import SqlearnError
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


def test_random_draws_the_same_settings_for_a_seed():
    """The same seed draws the same settings, within the range."""
    space = [
        {
            "model__C": sq.search.range(0.01, 10, log=True),
            "model__penalty": ["l1", "l2"],
        }
    ]
    a, b = sq.search.random(trials=20, seed=3), sq.search.random(trials=20, seed=3)
    a.start(space, maximize=True)
    b.start(space, maximize=True)
    draws = [a.ask() for _ in range(20)]
    assert draws == [b.ask() for _ in range(20)] and a.ask() is None
    assert all(0.01 <= d["model__C"] <= 10 for d in draws if d is not None)


def test_integer_bounds_draw_integers():
    """Integer bounds draw integers."""
    m = sq.search.random(trials=30, seed=0)
    m.start([{"model__depth": sq.search.range(4, 10)}], maximize=True)
    assert all(
        isinstance(d["model__depth"], int) and 4 <= d["model__depth"] <= 10
        for d in iter(m.ask, None)
    )


def test_random_chooses_among_the_grids_and_lists_uniformly():
    """Draws reach every grid and every listed value."""
    space = [{"model": ["a", "b"]}, {"scale__keep": [True]}]
    draws = asked(sq.search.random(trials=100, seed=1), space)
    assert any("model" in d for d in draws) and any("scale__keep" in d for d in draws)
    assert {d["model"] for d in draws if "model" in d} == {"a", "b"}


def test_random_repr_and_refusals():
    """The repr, and the refusals of bad trials and values."""
    assert repr(sq.search.random(trials=20, seed=3)) == ("Random(trials=20, seed=3)")
    for bad in (0, -1):
        with pytest.raises(SqlearnError, match="trials"):
            sq.search.random(trials=bad)
    with pytest.raises(SqlearnError, match="empty list"):
        sq.search.random().start([{"model__C": []}], maximize=True)
    with pytest.raises(SqlearnError, match="single value"):
        sq.search.random().start([{"model__C": 1}], maximize=True)


def assert_scores_match_grid_search(method):
    """Hand a random search's draws to GridSearchCV, on sqlearn's folds."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV, PredefinedSplit
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

    from sqlearn._config import connection

    data = customers()
    con = connection()
    con.register("random_data", data)
    folds = [
        k
        for (k,) in sq.folds.kfold(5, seed=0)
        .numbered(con.table("random_data"), "k")
        .project("k")
        .fetchall()
    ]
    con.unregister("random_data")
    space = {
        "model__C": sq.search.range(0.01, 10, log=True),
        "impute__value": ["median", "mean"],
    }
    search = sq.search(
        slice_pipe(), params=space, metric=sq.metrics.accuracy, method=method
    )
    search.train(data, target="churned")
    ours = dict(search.results_.aggregate("setting, avg(score)", "setting").fetchall())
    drawn = [json.loads(s) for s in ours]
    assert len(drawn) == 8
    sk = make_pipeline(
        ColumnTransformer(
            [
                ("num", SimpleImputer(strategy="median"), ["age", "income"]),
                ("city", OneHotEncoder(), ["city"]),
                ("plan", OrdinalEncoder(), ["plan"]),
            ]
        ),
        StandardScaler(),
        LogisticRegression(),
    )
    sk_grid = GridSearchCV(
        sk,
        [
            {
                "columntransformer__num__strategy": [d["impute__value"]],
                "logisticregression__C": [d["model__C"]],
            }
            for d in drawn
        ],
        scoring="accuracy",
        cv=PredefinedSplit(folds),
    ).fit(data.drop(columns="churned"), data["churned"])
    for params, sk_mean in zip(
        sk_grid.cv_results_["params"],
        sk_grid.cv_results_["mean_test_score"],
        strict=True,
    ):
        setting = json.dumps(
            {
                "impute__value": params["columntransformer__num__strategy"],
                "model__C": params["logisticregression__C"],
            }
        )
        assert ours[setting] == pytest.approx(sk_mean, abs=1e-12)


def test_random_search_matches_scikit_learn_on_its_draws():
    """Scores match GridSearchCV given the same draws and folds."""
    assert_scores_match_grid_search(method=sq.search.random(trials=8, seed=0))
