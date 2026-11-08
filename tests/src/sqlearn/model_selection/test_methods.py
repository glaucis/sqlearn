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


def separable(rows=120):
    """Return two numbers and a label the first one decides."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, rows)
    return pd.DataFrame(
        {"x": x, "z": rng.normal(0, 1, rows), "y": (x + rng.normal(0, 0.3, rows) > 0)}
    ).astype({"y": int})


def optuna_pipe(model=None):
    """Return a scaler and a model."""
    from sklearn.linear_model import LogisticRegression

    return sq.Pipeline(
        [
            ("scale", sq.scale.standard()),
            ("model", model if model is not None else LogisticRegression()),
        ]
    )


def test_optuna_finds_the_better_setting():
    """A log range of C: every trial is scored on every fold."""
    search = sq.search(
        optuna_pipe(),
        params={"model__C": sq.search.range(1e-4, 10, log=True)},
        method=sq.search.optuna(trials=15, seed=0),
        folds=sq.folds.kfold(3),
    )
    search.train(separable(), target="y")
    assert search.best_params_["model__C"] > 0.1
    assert search.results_.count("*").fetchall()[0][0] == 45


def test_optuna_is_repeatable_for_a_seed():
    """The same seed picks the same best setting."""

    def run():
        return (
            sq.search(
                optuna_pipe(),
                params={"model__C": sq.search.range(1e-3, 10, log=True)},
                method=sq.search.optuna(trials=6, seed=1),
                folds=sq.folds.kfold(2),
            )
            .train(separable(), target="y")
            .best_params_
        )

    assert run() == run()


def test_optuna_chooses_among_models():
    """A list of models comes back as the model objects themselves."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier

    models = [LogisticRegression(), DecisionTreeClassifier()]
    search = sq.search(
        optuna_pipe(),
        params={"model": models},
        method=sq.search.optuna(trials=4, seed=0),
        folds=sq.folds.kfold(2),
    )
    best = search.train(separable(), target="y").best_params_["model"]
    assert any(best is m for m in models)


def test_optuna_integer_range_and_several_grids():
    """Integer bounds give integers; several grids add a grid choice."""
    method = sq.search.optuna(trials=12, seed=0)
    space = [{"a": sq.search.range(1, 5)}, {"b": [True, False], "c": ["u", "v"]}]
    drawn = asked(method, space)
    assert len(drawn) == 12
    assert all(
        ("a" in d and isinstance(d["a"], int) and 1 <= d["a"] <= 5)
        or set(d) == {"b", "c"}
        for d in drawn
    )
    assert any("a" in d for d in drawn) and any("b" in d for d in drawn)


def test_optuna_minimises_when_lower_is_better():
    """A metric where lower is better makes a minimising study."""
    import duckdb

    from sqlearn.metrics import Metric

    error = Metric(
        "error",
        lambda y, p: duckdb.FunctionExpression(
            "avg",
            duckdb.CaseExpression(y == p, duckdb.ConstantExpression(0.0)).otherwise(
                duckdb.ConstantExpression(1.0)
            ),
        ),
        False,
    )
    method = sq.search.optuna(trials=8, seed=0)
    search = sq.search(
        optuna_pipe(),
        params={"model__C": sq.search.range(1e-4, 10, log=True)},
        metric=error,
        method=method,
        folds=sq.folds.kfold(3),
    )
    search.train(separable(), target="y")
    assert method.study_.direction.name == "MINIMIZE"
    assert search.best_params_["model__C"] > 0.1


def test_optuna_missing_names_how_to_install(monkeypatch):
    """Without optuna the message says how to install it."""
    monkeypatch.setitem(__import__("sys").modules, "optuna", None)
    with pytest.raises(SqlearnError, match=r"uv add optuna"):
        sq.search.optuna().start([{"a": [1]}], maximize=True)


def test_optuna_refusals_and_repr():
    """Bad trials and values are refused; the repr shows the settings."""
    assert repr(sq.search.optuna(trials=7, seed=2)) == "Optuna(trials=7, seed=2)"
    with pytest.raises(SqlearnError, match="trials"):
        sq.search.optuna(trials=0)
    with pytest.raises(SqlearnError, match="empty list"):
        sq.search.optuna().start([{"a": []}], maximize=True)
    with pytest.raises(SqlearnError, match="single value"):
        sq.search.optuna().start([{"a": 1}], maximize=True)


def test_optuna_takes_a_sampler():
    """A given sampler is used instead of the default."""
    import optuna

    sampler = optuna.samplers.RandomSampler(seed=0)
    method = sq.search.optuna(trials=2, sampler=sampler)
    method.start([{"a": [1, 2]}], maximize=True)
    assert method.study_.sampler is sampler


@pytest.mark.parametrize("make", [sq.search.random, sq.search.optuna])
@pytest.mark.parametrize("trials", [True, 2.5, "3", None])
def test_trials_must_be_a_whole_number(make, trials):
    """A bool, a fraction or text is refused by name, before any work."""
    with pytest.raises(SqlearnError, match=rf"trials={trials!r}.*whole number"):
        make(trials=trials)
