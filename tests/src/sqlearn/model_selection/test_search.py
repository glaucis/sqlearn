"""Tests of the search: grid over settings, fold first, on copies of the pipe."""

import json
import math
import warnings
import weakref
from typing import ClassVar

import duckdb
import numpy as np
import pandas as pd
import pytest
from search_data_for_tests import customers, slice_pipe
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import TargetEncoder
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier
from steps_for_tests import MyEncoder

import sqlearn as sq
from sqlearn import _feed
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.metrics import Metric
from sqlearn.model_selection import Grid
from sqlearn.model_selection import search as search_module

GRID = {"model__C": [0.1, 1, 10], "impute__value": ["median", "mean"]}
PIPE_WITH_SCALE = sq.Pipeline(
    [("scale", sq.scale.standard()), ("model", LogisticRegression())]
)
DATA = pd.DataFrame({"x": np.arange(30.0), "y": [0, 1, 1] * 10})


def _separable(rows=90):
    """Return two columns that decide the class, with a little noise."""
    rng = np.random.default_rng(1)
    x = rng.normal(size=(rows, 2))
    y = (x[:, 0] + 0.5 * x[:, 1] + rng.normal(scale=0.3, size=rows) > 0).astype(int)
    return pd.DataFrame({"a": x[:, 0], "b": x[:, 1], "y": y})


SEPARABLE = _separable()
# Ordered by t: the first half mixes the classes, the second half is all
# class 1, so a time fold holding out a later chunk sees one class only.
SORTED_BY_CLASS = pd.DataFrame(
    {
        "t": np.arange(120),
        "x": np.random.default_rng(2).normal(size=120),
        "y": [0, 1] * 30 + [1] * 60,
    }
)


def mean_scores(search):
    """Return each setting's mean score, keyed by its JSON text."""
    rows = search.results_.aggregate("setting, avg(score)", "setting").fetchall()
    return dict(rows)


class Counted(LogisticRegression):
    """LogisticRegression counting its fits across every copy."""

    fits = 0

    def fit(self, x, y, sample_weight=None):
        """Count, then fit."""
        type(self).fits += 1
        return super().fit(x, y, sample_weight)


class Echo:
    """A model of no library: predicts the most common label it saw."""

    def __init__(self):
        self.label = None

    def fit(self, x, y):
        """Remember the most common label."""
        values, counts = np.unique(y, return_counts=True)
        self.label = values[np.argmax(counts)]
        return self

    def predict(self, x):
        """Predict the remembered label for every row."""
        return np.full(len(x), self.label)


def test_grid_matches_gridsearchcv():
    """The slice's grid: the same best setting and mean scores as scikit-learn."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.model_selection import GridSearchCV, PredefinedSplit
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

    data = customers()
    con = connection()
    con.register("search_data", data)
    folds = [
        k
        for (k,) in sq.folds.kfold(5, seed=0)
        .numbered(con.table("search_data"), "k")
        .project("k")
        .fetchall()
    ]
    con.unregister("search_data")
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
        {
            "columntransformer__num__strategy": ["median", "mean"],
            "logisticregression__C": [0.1, 1, 10],
        },
        scoring="accuracy",
        cv=PredefinedSplit(folds),
    ).fit(data.drop(columns="churned"), data["churned"])

    search = sq.search(slice_pipe(), params=GRID, metric=sq.metrics.accuracy)
    search.train(data, target="churned")

    sk_best = sk_grid.best_params_
    assert search.best_params_ == {
        "impute__value": sk_best["columntransformer__num__strategy"],
        "model__C": sk_best["logisticregression__C"],
    }
    ours = mean_scores(search)
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
    assert search.best_score_ == pytest.approx(sk_grid.best_score_, abs=1e-12)


def test_changing_only_c_learns_nothing():
    """2 imputer settings x 5 folds: Impute and Scale 10, the encoders 5.

    The final training on all the data learns each step once more.
    """
    sq.search(slice_pipe(), params=GRID).train(customers(), target="churned")
    assert dict(STORE.learns) == {"impute": 11, "scale": 11, "onehot": 6, "ordinal": 6}
    STORE.clear()
    sq.search(slice_pipe(), params={"model__C": [0.1, 1, 10]}).train(
        customers(), target="churned"
    )
    assert dict(STORE.learns) == {"impute": 6, "scale": 6, "onehot": 6, "ordinal": 6}


def test_fold_first_prepares_once_per_fold_and_preparation():
    """30 trainings, 10 preparations; then one more training on all the data."""
    Counted.fits = 0
    search = sq.search(slice_pipe(Counted()), params=GRID)
    search.train(customers(), target="churned")
    assert search.transforms_ == 10
    assert Counted.fits == 31
    assert search.results_.count("*").fetchall() == [(30,)]


def test_the_users_pipe_is_unchanged():
    """The search trains copies: the user's steps and model stay as they were."""
    pipe = slice_pipe()
    before = [(name, dict(vars(step))) for name, step in pipe.steps]
    search = sq.search(pipe, params=GRID).train(customers(), target="churned")
    assert [(name, dict(vars(step))) for name, step in pipe.steps] == before
    assert pipe._feed is None
    assert pipe._entries is None
    assert not hasattr(pipe["model"], "coef_")
    assert search.best_pipeline_ is not pipe
    assert all(
        a is not b
        for (_, a), (_, b) in zip(search.best_pipeline_.steps, pipe.steps, strict=True)
    )
    assert hasattr(search.best_pipeline_["model"], "coef_")


def test_list_of_grids_for_two_models():
    """Settings only one model has go in that model's own grid."""
    tree = DecisionTreeClassifier(random_state=0)
    params = [
        {"model": [LogisticRegression()], "model__C": [0.1, 1]},
        {"model": [tree], "model__max_depth": [2, 3]},
    ]
    search = sq.search(slice_pipe(), params=params).train(customers(), target="churned")
    settings = mean_scores(search)
    assert len(settings) == 4
    assert search.results_.count("*").fetchall() == [(20,)]
    assert '"model": "DecisionTreeClassifier(random_state=0)"' in " ".join(settings)
    best_model = search.best_params_["model"]
    assert type(search.best_pipeline_["model"]) is type(best_model)
    assert search.best_pipeline_["model"] is not best_model
    assert not hasattr(tree, "tree_")


def test_unknown_setting_is_named():
    """A setting a model or step lacks is refused, naming both."""
    data = customers(rows=50)
    cases = [
        ({"model__nope": [1]}, r"LogisticRegression.*'nope'"),
        ({"scale__nope": [1]}, r"Scale.*'scale'.*'nope'"),
        ({"nostep__x": [1]}, r"'nostep'.*impute, onehot, ordinal, scale, model"),
        (
            [{"model": [LogisticRegression()], "model__max_depth": [2]}],
            r"LogisticRegression.*'max_depth'",
        ),
        ({"scale": [sq.scale.standard()]}, r"'scale'.*step__setting"),
    ]
    for params, message in cases:
        with pytest.raises(sq.errors.SqlearnError, match=message):
            sq.search(slice_pipe(), params=params).train(data, target="churned")


def test_a_setting_of_a_model_without_get_params_is_checked_by_attribute():
    """A model of no library: its settings are its attributes."""
    data = customers(rows=100)
    search = sq.search(slice_pipe(Echo()), params={"model__label": [None]})
    search.train(data, target="churned")
    assert search.best_params_ == {"model__label": None}
    with pytest.raises(sq.errors.SqlearnError, match=r"Echo.*'nope'"):
        sq.search(slice_pipe(Echo()), params={"model__nope": [1]}).train(
            data, target="churned"
        )


class Sparse(Echo):
    """A model whose get_params lists only the settings it was given, as CatBoost's."""

    def __init__(self, depth=6, verbose=None):
        super().__init__()
        self._given = {"verbose": verbose} if verbose is not None else {}
        self.depth = depth

    def get_params(self, deep=True):
        """Return the settings given to the constructor, and no others."""
        return dict(self._given)

    def set_params(self, **params):
        """Record and set each setting."""
        self._given.update(params)
        for name, value in params.items():
            setattr(self, name, value)
        return self


def test_a_setting_get_params_leaves_out_is_found_in_the_constructor():
    """CatBoost lists in get_params only the settings it was given.

    A setting of its constructor is still a setting; one of neither is
    refused, listing both.
    """
    data = customers(rows=100)
    search = sq.search(slice_pipe(Sparse(verbose=0)), params={"model__depth": [2, 3]})
    search.train(data, target="churned")
    assert search.best_pipeline_["model"].depth in {2, 3}
    with pytest.raises(sq.errors.SqlearnError, match=r"Sparse.*'nope'.*depth"):
        sq.search(slice_pipe(Sparse(verbose=0)), params={"model__nope": [1]}).train(
            data, target="churned"
        )


def test_range_given_to_grid_is_refused():
    """Grid cannot try a range: the search refuses it, naming the setting."""
    search = sq.search(
        slice_pipe(), params={"model__C": sq.search.range(0.01, 10, log=True)}
    )
    with pytest.raises(sq.errors.SqlearnError, match=r"'model__C'.*range"):
        search.train(customers(rows=50), target="churned")


def test_no_params_uses_default_space_and_warns():
    """No params: LogisticRegression's default space, and a warning saying so."""
    search = sq.search(slice_pipe())
    with pytest.warns(
        sq.errors.DefaultsUsedWarning, match="LogisticRegression"
    ) as caught:
        search.train(customers(), target="churned")
    text = str(caught[0].message)
    assert text == (
        "Hint: no params given. sqlearn searched its default space for\n"
        "LogisticRegression: C in [0.001, 100], log scale, 7 values.\n"
        "Pass params=... to choose what to search."
    )
    assert "LogisticRegression" in search.used_["params"]
    assert search.used_["method"] == "default: Grid()"
    assert search.used_["folds"] == "default: KFold(n=5, seed=0)"
    assert len(mean_scores(search)) == 7
    assert set(search.best_params_) == {"model__C"}


def test_unknown_model_runs_one_trial_and_warns():
    """A model with no default space is scored with its own settings."""
    search = sq.search(slice_pipe(Echo()))
    with pytest.warns(sq.errors.DefaultsUsedWarning, match="no default space for Echo"):
        search.train(customers(rows=100), target="churned")
    assert search.results_.count("*").fetchall() == [(5,)]
    assert search.best_params_ == {}
    assert "Echo" in search.used_["params"]


def test_given_settings_are_recorded_as_given():
    """What the user passes is recorded as given, with no warning."""
    search = sq.search(
        slice_pipe(),
        params=GRID,
        method=sq.search.grid(),
        folds=sq.folds.kfold(3, seed=1),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        search.train(customers(), target="churned")
    assert search.used_ == {
        "params": "given",
        "method": "given",
        "folds": "given: KFold(n=3, seed=1)",
    }
    assert search.results_.count("*").fetchall() == [(18,)]
    assert search.transforms_ == 6


def test_results_hold_one_row_per_setting_and_fold():
    """`results_` is a relation; `best_score_` is the best setting's mean."""
    search = sq.search(slice_pipe(), params=GRID).train(customers(), target="churned")
    assert search.results_.columns == ["setting", "fold", "score"]
    assert [str(t) for t in search.results_.types] == ["VARCHAR", "BIGINT", "DOUBLE"]
    rows = search.results_.fetchall()
    assert sorted({fold for _, fold, _ in rows}) == [0, 1, 2, 3, 4]
    means = mean_scores(search)
    assert search.best_score_ == pytest.approx(max(means.values()))
    assert means[json.dumps(search.best_params_)] == pytest.approx(search.best_score_)


def test_ties_go_to_the_first_setting_in_grid_order():
    """When scores tie, the first setting wins, as in scikit-learn."""
    search = sq.search(slice_pipe(Echo()), params={"model__label": [None, None]})
    search.train(customers(rows=100), target="churned")
    scores = mean_scores(search)
    assert len(set(scores.values())) == 1
    assert search.best_params_ == {"model__label": None}


def test_scores_one_rounding_step_apart_tie_and_the_first_tried_wins():
    """A score 1 ULP better is a tie (ADR 0043): the first setting tried wins."""
    from sqlearn.metrics import Metric

    one_ulp_more = math.nextafter(0.6, 1.0)
    tiny = Metric(
        "tiny",
        lambda y, p: sq.agg.mean(
            duckdb.CaseExpression(
                p == sq.fn.const(1), sq.fn.const(one_ulp_more)
            ).otherwise(sq.fn.const(0.6))
        ),
        True,
    )
    search = sq.search(
        sq.Pipeline([("model", Constant())]),
        params={"model__label": [0, 1]},
        metric=tiny,
    ).train(SEPARABLE, target="y")
    assert mean_scores(search)[json.dumps({"model__label": 1})] == one_ulp_more
    assert search.best_params_ == {"model__label": 0}


def test_a_better_score_beyond_the_tolerance_still_wins():
    """Scores further apart than the tie tolerance are not a tie."""
    better = 0.6 + 1e-12
    clear = sq.metrics.Metric(
        "clear",
        lambda y, p: sq.agg.mean(
            duckdb.CaseExpression(p == sq.fn.const(1), sq.fn.const(better)).otherwise(
                sq.fn.const(0.6)
            )
        ),
        True,
    )
    search = sq.search(
        sq.Pipeline([("model", Constant())]),
        params={"model__label": [0, 1]},
        metric=clear,
    ).train(SEPARABLE, target="y")
    assert search.best_params_ == {"model__label": 1}


def test_a_metric_where_lower_is_better_picks_the_lowest():
    """With greater_is_better False, the best setting has the lowest score."""
    error = Metric(
        "error",
        lambda y, p: sq.agg.mean(
            __import__("duckdb")
            .CaseExpression(y != p, sq.fn.const(1.0))
            .otherwise(sq.fn.const(0.0))
        ),
        False,
    )
    search = sq.search(slice_pipe(), params=GRID, metric=error)
    search.train(customers(), target="churned")
    assert search.best_score_ == pytest.approx(min(mean_scores(search).values()))


def test_a_method_asking_one_setting_at_a_time_gives_the_same_scores():
    """A method that does not know all its settings loops setting first."""

    class OneByOne(Grid):
        knows_all = False

    data = customers()
    grid = sq.search(slice_pipe(), params=GRID).train(data, target="churned")
    one = sq.search(slice_pipe(), params=GRID, method=OneByOne()).train(
        data, target="churned"
    )
    assert mean_scores(one) == mean_scores(grid)
    assert one.best_params_ == grid.best_params_
    assert one.transforms_ == 10  # two preparations, five folds: each once


def test_predict_uses_the_best_pipeline():
    """`predict` is the best pipeline's, trained on all the data."""
    data = customers()
    search = sq.search(slice_pipe(), params=GRID)
    with pytest.raises(sq.errors.SqlearnError, match="train"):
        search.predict(data)
    search.train(data, target="churned")
    got = search.predict(data, out="numpy")["prediction"]
    want = search.best_pipeline_.predict(data, out="numpy")["prediction"]
    np.testing.assert_array_equal(got, want)
    assert len(got) == len(data)


def test_the_input_is_read_once(monkeypatch):
    """A search reads (and fingerprints) its input once, final training included."""
    from sqlearn import _inputs

    calls = []
    real = _inputs._fingerprint

    def counting(name):
        calls.append(name)
        return real(name)

    monkeypatch.setattr(_inputs, "_fingerprint", counting)
    sq.search(slice_pipe(), params=GRID).train(customers(), target="churned")
    assert len(calls) == 1


def test_a_column_named_as_the_fold_column_is_refused():
    """The search keeps a column name for the fold number."""
    data = customers(rows=50)
    data[search_module.FOLD] = 1
    with pytest.raises(sq.errors.SqlearnError, match=search_module.FOLD):
        sq.search(slice_pipe(), params=GRID).train(data, target="churned")


def test_the_target_must_be_a_column():
    """A missing target is refused before any work."""
    with pytest.raises(sq.errors.SqlearnError, match="'nope' is not a column"):
        sq.search(slice_pipe(), params=GRID).train(customers(rows=50), target="nope")


class Wide(Echo):
    """A model predicting two values per row."""

    def predict(self, x):
        """Return a column too many."""
        return np.zeros((len(x), 2))


def test_a_candidate_that_is_not_a_model_is_refused():
    """``"model"`` lists models; anything else is named."""
    with pytest.raises(sq.errors.SqlearnError, match=r"'model': 'tree'.*not a model"):
        sq.search(slice_pipe(), params={"model": ["tree"]}).train(
            customers(rows=50), target="churned"
        )


def test_settings_are_checked_before_the_data_is_read(monkeypatch):
    """A bad setting is refused before the input is read; an empty space too."""
    from sqlearn._inputs import _fingerprint

    calls = []
    monkeypatch.setattr(
        "sqlearn._inputs._fingerprint", lambda name: calls.append(name) or (0, 0)
    )
    with pytest.raises(sq.errors.SqlearnError, match="nope"):
        sq.search(slice_pipe(), params={"model__nope": [1]}).train(
            customers(rows=50), target="churned"
        )
    assert calls == []
    monkeypatch.setattr("sqlearn._inputs._fingerprint", _fingerprint)
    with pytest.raises(sq.errors.SqlearnError, match="no setting to try"):
        sq.search(slice_pipe(), params=[]).train(customers(rows=50), target="churned")


def test_a_model_predicting_the_wrong_shape_is_refused():
    """One prediction per held-out row, or the score cannot be computed."""
    with pytest.raises(sq.errors.SqlearnError, match=r"shape \(\d+, 2\)"):
        sq.search(slice_pipe(Wide()), params={}).train(
            customers(rows=100), target="churned"
        )


def test_an_empty_fold_is_refused_before_any_work():
    """A fold holding out no row is refused, with every fold's size."""
    df = pd.DataFrame({"x": np.arange(10, dtype=float), "y": [0, 1] * 5})
    pipe = sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    )
    search = sq.search(
        pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(5, seed=0)
    )
    with pytest.raises(
        sq.errors.SqlearnError, match=r"fold 3 .*4, 1, 2, 0, 3 rows.*Fix: .*fewer folds"
    ):
        search.train(df, target="y")
    assert STORE.learns == {}


def test_a_fold_with_nothing_to_learn_from_is_refused_before_any_work():
    """A time fold whose gap leaves no training row is refused, with sizes."""
    df = pd.DataFrame({"t": np.arange(12.0), "x": np.arange(12.0), "y": [0, 1] * 6})
    pipe = sq.Pipeline([("model", LogisticRegression())])
    search = sq.search(
        pipe, params={"model__C": [1.0]}, folds=sq.folds.time("t", 2, gap=5)
    )
    with pytest.raises(
        sq.errors.SqlearnError, match=r"fold 0 .*learns from no row.*Fix: .*gap"
    ):
        search.train(df, target="y")
    assert STORE.learns == {}


def test_a_failing_fit_names_the_setting_and_the_fold():
    """A model that cannot fit a fold is named with its setting and fold."""
    dup = pd.DataFrame({"x": [1.0] * 6 + [2.0] * 6, "y": [0] * 6 + [1] * 6})
    pipe = sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    )
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    with pytest.raises(
        sq.errors.SqlearnError, match=r'"model__C": 1.0.*fold 0'
    ) as info:
        search.train(dup, target="y")
    assert isinstance(info.value.__cause__, ValueError)
    assert "Fix:" in str(info.value)


def test_settings_changing_a_later_steps_inputs_score_as_if_alone():
    """Each setting's later steps learn on their own inputs, never stale."""
    rng = np.random.default_rng(0)
    rows = 200
    df = pd.DataFrame(
        {
            "city": rng.choice(["a", "b"], rows),
            "region": rng.choice(["n", "s"], rows),
            "plan": rng.choice(["x", "y", "z"], rows),
            "y": rng.integers(0, 2, rows),
        }
    )

    def pipe():
        return sq.Pipeline(
            [
                ("onehot", sq.encode.onehot(cols=["city"])),
                ("ordinal", sq.encode.ordinal(cols=sq.cols.string())),
                ("model", LogisticRegression()),
            ]
        )

    grid = {"onehot__cols": [["city", "region"], ["city"]]}
    both = sq.search(pipe(), params=grid, folds=sq.folds.kfold(3)).train(df, target="y")
    city = json.dumps({"onehot__cols": ["city"]})
    got = [r for r in both.results_.fetchall() if r[0] == city]
    STORE.clear()
    alone = sq.search(
        pipe(), params={"onehot__cols": [["city"]]}, folds=sq.folds.kfold(3)
    )
    assert got == alone.train(df, target="y").results_.fetchall()


class Recorder(BaseEstimator, ClassifierMixin):
    """A model that keeps what each fold trains and predicts on."""

    seen: list[tuple[str, np.ndarray]] = []  # noqa: RUF012  (shared on purpose)

    def fit(self, x, y):
        """Keep the features."""
        Recorder.seen.append(("fit", np.array(x)))
        self.classes_ = np.unique(y)
        return self

    def predict(self, x):
        """Keep the features; predict the first class."""
        Recorder.seen.append(("predict", np.array(x)))
        return np.full(len(x), self.classes_[0])


def test_a_target_step_cross_fits_within_each_folds_training_rows():
    """Each fold's training rows are cross-fitted, its held-out rows encoded
    with what was learned on all its training rows, as scikit-learn's."""
    Recorder.seen.clear()
    frame = customers()[["plan", "age", "churned"]].fillna({"age": 0.0})
    pipe = sq.Pipeline([sq.encode.target("plan"), Recorder()])
    sq.search(pipe, params={"target__cv": [5]}, folds=sq.folds.kfold(2)).train(
        frame, target="churned"
    )
    rel = connection().from_df(frame)
    outer = np.array([r[-1] for r in sq.folds.kfold(2).numbered(rel, "f").fetchall()])
    positions = connection().sql(f"SELECT range + 1 AS p FROM range({len(frame)})")
    inner = np.array(
        [
            r[0]
            for r in positions.set_alias("d")
            .project(sq.folds.kfold(5, 0).expression("d"))
            .fetchall()
        ]
    )
    train = outer != 0
    x = np.array(frame[["plan"]], dtype=object)
    y = frame["churned"].to_numpy()
    folds = inner[train]
    cv = [(np.flatnonzero(folds != k), np.flatnonzero(folds == k)) for k in range(5)]
    theirs = TargetEncoder(target_type="binary", cv=[s for s in cv if len(s[1])])
    crossed = theirs.fit_transform(x[train], y[train])[:, 0]
    (fit, fitted), (predict, held) = Recorder.seen[:2]
    assert (fit, predict) == ("fit", "predict")
    assert fitted[:, 0] == pytest.approx(crossed, rel=1e-12)
    assert held[:, 0] == pytest.approx(theirs.transform(x[~train])[:, 0], rel=1e-12)


def test_a_search_over_the_inner_folds_of_a_target_step():
    """Each setting's own inner folds are dealt: cv=2 and cv=3 both run."""
    frame = customers()[["plan", "age", "churned"]].fillna({"age": 0.0})
    pipe = sq.Pipeline([sq.encode.target("plan"), LogisticRegression()])
    search = sq.search(pipe, params={"target__cv": [2, 3]}, folds=sq.folds.kfold(2))
    search.train(frame, target="churned")
    assert search.results_.count("*").fetchall() == [(4,)]
    assert search.best_pipeline_["target"].cv in (2, 3)


def test_a_search_takes_any_scheme():
    """A user's own scheme decides which rows each fold fits and scores."""
    import duckdb

    class Halves:
        splits = 2
        key = ("halves",)
        calls: ClassVar[list[object]] = []

        def numbered(self, rel, name, target):
            self.calls.append("numbered")
            order = "ORDER BY city, plan, churned, age, income"
            return rel.project(f"*, (row_number() OVER ({order}) % 2) AS {name}")

        def training(self, name, k):
            self.calls.append("training")
            return duckdb.ColumnExpression(name) != duckdb.ConstantExpression(k)

        def held(self, name, k):
            self.calls.append("held")
            return duckdb.ColumnExpression(name) == duckdb.ConstantExpression(k)

        def __repr__(self):
            return "Halves()"

    class Sizes(Echo):
        """Records how many rows each fold fits on and scores."""

        seen: ClassVar[list[object]] = []

        def fit(self, x, y):
            type(self).seen.append(["fit", len(x)])
            return super().fit(x, y)

        def predict(self, x):
            type(self).seen.append(["predict", len(x)])
            return super().predict(x)

    scheme = Halves()
    search = sq.search(
        slice_pipe(Sizes()), params={"model__label": [None]}, folds=scheme
    )
    search.train(customers(rows=101), target="churned")
    assert search.results_.count("*").fetchall()[0][0] == 2
    assert {"numbered", "training", "held"} <= set(scheme.calls)
    # 101 rows: positions 1..101 mod 2 give 51 rows in fold 1 and 50 in fold 0.
    fold_runs = Sizes.seen[:4]
    assert fold_runs == [["fit", 51], ["predict", 50], ["fit", 50], ["predict", 51]]
    assert search.used_["folds"] == "given: Halves()"


def test_a_column_starting_with_the_fold_prefix_is_refused():
    """The masks and helpers share the prefix, so any such column is refused."""
    data = customers(rows=50).assign(__sqlearn_fold_fit=1)
    with pytest.raises(sq.errors.SqlearnError, match="starts with"):
        sq.search(slice_pipe(), params={"model__C": [1.0]}).train(
            data, target="churned"
        )


class SeenTargets(BaseEstimator, ClassifierMixin):
    """A model that keeps the target of every fit."""

    fits: ClassVar[list[np.ndarray]] = []

    def fit(self, x, y):
        """Keep the target."""
        SeenTargets.fits.append(np.array(y))
        self.classes_ = np.unique(y)
        return self

    def predict(self, x):
        """Predict the first class."""
        return np.full(len(x), self.classes_[0])


def test_a_search_over_stratified_folds_passes_its_target_to_the_scheme():
    """Each fold learns from the class shares of the whole: 10% positives."""
    SeenTargets.fits.clear()
    frame = pd.DataFrame({"a": np.arange(1000.0), "y": (np.arange(1000) % 10 == 0) * 1})
    pipe = sq.Pipeline([SeenTargets()])
    search = sq.search(pipe, params={}, folds=sq.folds.stratified(5, seed=0))
    search.train(frame, target="y")
    folds = [fit for fit in SeenTargets.fits if len(fit) == 800]
    assert len(folds) == 5
    assert all(fit.sum() == 80 for fit in folds)
    assert sorted({f for _, f, _ in search.results_.fetchall()}) == [0, 1, 2, 3, 4]


def test_a_setting_picked_twice_is_prepared_once():
    """A method asking one setting twice reads each fold's table again."""

    class Twice:  # asks the same setting twice, one at a time
        knows_all = False

        def start(self, space, *, maximize):
            self.left = [{"model__C": 1.0}] * 2

        def ask(self):
            return self.left.pop() if self.left else None

        def tell(self, params, score):
            pass

    search = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        method=Twice(),
        folds=sq.folds.kfold(3),
    )
    search.train(DATA, target="y")
    assert search.transforms_ == 3  # three folds, once each


def _fold_tables_alive():
    """Return how many temporary tables of prepared folds exist now."""
    return (
        connection()
        .sql(
            "SELECT count(*) FROM duckdb_tables() "
            "WHERE temporary AND starts_with(table_name, '__sqlearn_fold_')"
        )
        .fetchall()[0][0]
    )


def test_one_at_a_time_keeps_only_the_current_preparations_fold_tables():
    """Alternating two preparations, one preparation's tables live at a time."""

    class Alternating:  # an Optuna-style method: one setting at a time
        knows_all = False

        def start(self, space, *, maximize):
            self.left = [{"impute__value": v} for v in ["mean", "median"] * 2]
            self.alive = []

        def ask(self):
            self.alive.append(_fold_tables_alive())
            return self.left.pop() if self.left else None

        def tell(self, params, score):
            pass

    method = Alternating()
    search = sq.search(slice_pipe(), params=GRID, method=method)
    search.train(customers(), target="churned")
    assert max(method.alive) == 5  # five folds of one preparation
    assert search.transforms_ == 20  # each preparation asked anew is prepared anew
    assert _fold_tables_alive() == 0


class Tracked(LogisticRegression):
    """LogisticRegression noting, at each fit, how many fitted copies are alive."""

    fitted: ClassVar[list[weakref.ref[LogisticRegression]]] = []
    alive_at_fit: ClassVar[list[int]] = []

    def fit(self, x, y, sample_weight=None):
        """Count the fitted copies still alive, then fit."""
        type(self).alive_at_fit.append(sum(r() is not None for r in self.fitted))
        super().fit(x, y, sample_weight)
        type(self).fitted.append(weakref.ref(self))
        return self


def test_each_model_is_dropped_once_it_is_scored():
    """Three settings of one preparation: no fitted model outlives its score."""
    Tracked.fitted.clear()
    Tracked.alive_at_fit.clear()
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Tracked())])
    search = sq.search(
        pipe, params={"model__C": [0.1, 1.0, 10.0]}, folds=sq.folds.kfold(2)
    )
    search.train(DATA, target="y")
    # The fits over the folds; the last is the best pipeline's, on all data.
    assert Tracked.alive_at_fit[:6] == [0] * 6


def test_fold_tables_are_dropped_after_train():
    """No temporary table outlives the train call that made it."""
    search = sq.search(
        PIPE_WITH_SCALE, params={"model__C": [1.0]}, folds=sq.folds.kfold(2)
    )
    search.train(DATA, target="y")
    temp = (
        connection()
        .sql("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        .fetchall()[0][0]
    )
    assert temp == 0


class Broken(LogisticRegression):
    """LogisticRegression that fails every fit."""

    def fit(self, x, y, sample_weight=None):
        """Fail."""
        msg = "broken"
        raise ValueError(msg)


def test_fold_tables_are_dropped_when_train_raises():
    """A model failing on a fold still leaves no temporary table behind."""
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Broken())])
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    with pytest.raises(sq.errors.SqlearnError, match="failed to fit"):
        search.train(DATA, target="y")
    temp = (
        connection()
        .sql("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        .fetchall()[0][0]
    )
    assert temp == 0


def test_a_column_named_as_the_row_number_is_refused():
    """The fold tables number their rows under a name the search keeps."""
    data = customers(rows=50).assign(__sqlearn_row=1)
    with pytest.raises(sq.errors.SqlearnError, match=r"'__sqlearn_row'.*Fix"):
        sq.search(slice_pipe(), params={"model__C": [1.0]}).train(
            data, target="churned"
        )


def test_a_step_output_named_as_the_row_number_is_refused():
    """A step creating a column named as the row number is refused too."""
    # The encoder names its columns column_value: "_" and "sqlearn_row".
    data = pd.DataFrame({"_": ["sqlearn_row", "oslo"] * 10, "y": [0, 0, 1, 1] * 5})
    pipe = sq.Pipeline([MyEncoder(cols=["_"]), LogisticRegression()])
    with pytest.raises(sq.errors.SqlearnError, match=r"'__sqlearn_row'.*Fix"):
        sq.search(pipe, params={}, folds=sq.folds.kfold(2)).train(data, target="y")


def test_each_held_out_fold_is_scored_in_batches(monkeypatch):
    """The held-out rows reach predict one batch at a time; scores unchanged."""
    expected = sq.search(
        PIPE_WITH_SCALE, params={"model__C": [1.0]}, folds=sq.folds.kfold(2)
    ).train(DATA, target="y")
    monkeypatch.setattr(_feed, "BATCH_ROWS", 4)
    seen = []

    class Batches(LogisticRegression):
        def predict(self, X):  # noqa: N803  (scikit-learn's name)
            seen.append(len(X))
            return super().predict(X)

    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Batches())])
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    search.train(DATA, target="y")
    assert sum(seen) == len(DATA)  # every row held out once
    assert max(seen) == 4
    assert len(seen) >= 8
    assert search.results_.fetchall() == expected.results_.fetchall()


def test_no_predictions_table_outlives_the_search():
    """Each fold's predictions are dropped once scored."""
    search = sq.search(
        PIPE_WITH_SCALE, params={"model__C": [0.1, 1.0]}, folds=sq.folds.kfold(2)
    )
    search.train(DATA, target="y")
    query = (
        "SELECT count(*) FROM duckdb_tables() "
        f"WHERE database_name = '{_feed._DATABASE}'"
    )
    assert connection().sql(query).fetchall()[0][0] == 0


def test_a_held_out_row_without_a_target_is_refused():
    """The last rows in time are only ever held out; a missing target there."""
    data = pd.DataFrame(
        {"t": np.arange(30), "x": np.arange(30.0), "y": [0.0, 1.0] * 14 + [1.0, None]}
    )
    pipe = sq.Pipeline([("model", LogisticRegression())])
    search = sq.search(pipe, params={}, folds=sq.folds.time("t", n=2))
    with pytest.raises(sq.errors.SqlearnError, match=r"'y' is missing in 1 row"):
        search.train(data, target="y")


class Refusing(LogisticRegression):
    """A model whose fit raises sqlearn's own error, as a wrapped one might."""

    def fit(self, X, y, sample_weight=None):  # noqa: N803  (scikit-learn's name)
        """Fail with a SqlearnError."""
        msg = "inner refusal"
        raise sq.errors.SqlearnError(msg)


def test_a_sqlearn_error_inside_fit_keeps_the_setting_and_fold():
    """Only the stream's own shape error passes unwrapped; others get context."""
    pipe = sq.Pipeline([("model", Refusing())])
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    with pytest.raises(
        sq.errors.SqlearnError,
        match=r"failed to fit .*model__C.* fold 0.*inner refusal",
    ):
        search.train(DATA, target="y")


class Forms(BaseEstimator, ClassifierMixin):
    """A model recording the form of each fit's features, across copies."""

    seen: ClassVar[list[str]] = []

    def __init__(self, tag=0):
        self.tag = tag

    def fit(self, x, y):
        """Record the form, then learn nothing."""
        type(self).seen.append(type(x).__module__.partition(".")[0])
        return self

    def predict(self, x):
        """Predict class 0 for every row."""
        return np.zeros(len(x), dtype=int)


def test_each_model_of_a_search_trains_in_its_own_form(monkeypatch):
    """A preparation's rows are fetched once per distinct feed (Ruling R7)."""
    fetched = []
    real = search_module.fetch

    def counted(rel, feed, *args, **kwargs):
        fetched.append(feed)
        return real(rel, feed, *args, **kwargs)

    monkeypatch.setattr(search_module, "fetch", counted)
    Forms.seen = []
    candidates = [
        sq.Model(Forms(0), feed="pandas"),
        sq.Model(Forms(1), feed="polars"),
        sq.Model(Forms(2), feed="pandas"),
    ]
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Forms())])
    sq.search(pipe, params={"model": candidates}, folds=sq.folds.kfold(n=2)).train(
        DATA, target="y"
    )
    assert Forms.seen[:6] == ["pandas", "pandas", "polars"] * 2
    assert fetched == ["pandas", "polars"] * 2


class ByCode(BaseEstimator, ClassifierMixin):
    """A model that learns each city code's class and predicts by code."""

    def fit(self, x, y):
        """Learn the class of each code."""
        self.classes_ = np.unique(np.asarray(y))
        self.by_code_ = dict(zip(x["city"].cat.codes, np.asarray(y), strict=True))
        return self

    def predict(self, x):
        """Look each row's code up."""
        return np.array([self.by_code_.get(c, -1) for c in x["city"].cat.codes])


def test_a_search_scores_held_rows_with_their_training_codes(monkeypatch):
    """Each held-out batch is cast with its fold's training categories."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 1)
    data = pd.DataFrame(
        {
            "n": np.arange(30.0),
            "city": ["kyiv", "oslo", "rome"] * 10,
            "y": [0, 1, 2] * 10,
        }
    )
    pipe = sq.Pipeline([("model", sq.Model(ByCode(), feed="pandas"))])
    search = sq.search(
        pipe,
        params={"model": [sq.Model(ByCode(), feed="pandas")]},
        folds=sq.folds.kfold(3),
    )
    search.train(data, target="y")
    assert search.best_score_ == 1.0


def test_a_search_scores_by_log_loss():
    """Lower log loss wins: a weak penalty beats a crushing one on separable data."""
    search = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [0.001, 10.0]},
        metric=sq.metrics.log_loss,
        folds=sq.folds.stratified(3),
    )
    assert search.train(SEPARABLE, target="y").best_params_ == {"model__C": 10.0}


def test_a_search_scores_by_roc_auc_as_scikit_learn_on_each_fold():
    """Each fold's score is roc_auc_score of the fold's model on its held rows."""
    folds = sq.folds.stratified(3)
    search = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        metric=sq.metrics.roc_auc,
        folds=folds,
    )
    search.train(SEPARABLE, target="y")
    scores = [s for *_, s in search.results_.order("fold").fetchall()]
    numbered = folds.numbered(connection().from_df(SEPARABLE), "f", "y")
    expected = []
    for k in range(3):
        train = numbered.filter(folds.training("f", k)).df()
        held = numbered.filter(folds.held("f", k)).df()
        mean, std = train[["a", "b"]].mean(), train[["a", "b"]].std(ddof=0)
        model = LogisticRegression().fit((train[["a", "b"]] - mean) / std, train["y"])
        proba = model.predict_proba((held[["a", "b"]] - mean) / std)
        expected.append(roc_auc_score(held["y"], proba[:, 1]))
    assert scores == pytest.approx(expected, rel=1e-9)


def test_roc_auc_on_a_one_class_time_fold_names_a_fix_for_time():
    """A held-out time fold of one class: fewer folds or a later cut-off."""
    with pytest.raises(sq.errors.SqlearnError, match=r"fold 1 .*fewer folds") as e:
        sq.search(
            PIPE_WITH_SCALE,
            params={"model__C": [1.0]},
            metric=sq.metrics.roc_auc,
            folds=sq.folds.time("t", 3),
        ).train(SORTED_BY_CLASS, target="y")
    assert "later cut-off" in str(e.value)
    assert "stratified" not in str(e.value)


def test_roc_auc_on_a_one_class_kfold_fold_names_stratified():
    """Under folds dealt by a hash, the fix names stratified folds."""
    rare = pd.DataFrame({"x": np.arange(40.0), "y": [1] * 37 + [0] * 3})
    with pytest.raises(sq.errors.SqlearnError, match=r"fold \d .*stratified"):
        sq.search(
            PIPE_WITH_SCALE,
            params={"model__C": [1.0]},
            metric=sq.metrics.roc_auc,
            folds=sq.folds.kfold(5),
        ).train(rare, target="y")


def test_a_label_no_training_row_held_names_the_fold_and_setting():
    """A held-out class the fold's model never saw: the fold and setting named."""
    late = pd.DataFrame(
        {"t": np.arange(120), "x": np.arange(120.0), "y": [0, 1] * 45 + [0, 1, 2] * 10}
    )
    with pytest.raises(
        sq.errors.SqlearnError,
        match=r"fold 2 of TimeSplit.*model__C.*none of the classes \[0, 1\]",
    ):
        sq.search(
            PIPE_WITH_SCALE,
            params={"model__C": [1.0]},
            metric=sq.metrics.log_loss,
            folds=sq.folds.time("t", 3),
        ).train(late, target="y")


def test_an_empty_held_out_fold_is_worded_for_any_scheme():
    """A holdout holding out no row is refused without words of dealing."""
    tiny = pd.DataFrame({"x": np.arange(10.0), "y": [0, 1] * 5})
    with pytest.raises(
        sq.errors.SqlearnError, match=r"of the 10 rows, the folds hold out 0 rows"
    ) as e:
        sq.search(
            PIPE_WITH_SCALE,
            params={"model__C": [1.0]},
            folds=sq.folds.holdout(test=0.01, seed=1),
        ).train(tiny, target="y")
    assert "dealt" not in str(e.value)


def test_a_model_without_predict_proba_is_refused_before_the_data_is_read(
    monkeypatch,
):
    """A probability metric needs predict_proba: refused before any work."""

    def unread(data, **_):
        raise AssertionError("the data was read")

    monkeypatch.setattr(search_module, "read", unread)
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", LinearSVC())])
    with pytest.raises(
        sq.errors.SqlearnError, match=r"log_loss.*LinearSVC.*predict_proba"
    ):
        sq.search(pipe, params={"model__C": [1.0]}, metric=sq.metrics.log_loss).train(
            SEPARABLE, target="y"
        )


class Unnamed(LogisticRegression):
    """A classifier whose fitted probabilities name no classes."""

    def fit(self, X, y):  # noqa: N803  (scikit-learn's name)
        """Fit, then forget the classes."""
        super().fit(X, y)
        self.labels_ = self.classes_
        del self.classes_
        return self

    def predict_proba(self, X):  # noqa: N803  (scikit-learn's name)
        """Return the probabilities with the classes put back for the call."""
        self.classes_ = self.labels_
        try:
            return super().predict_proba(X)
        finally:
            del self.classes_


def test_probabilities_without_classes_are_refused():
    """A fitted model with no classes_ leaves its columns unnamed: refused."""
    pipe = sq.Pipeline([("model", Unnamed())])
    with pytest.raises(sq.errors.SqlearnError, match="Unnamed has no classes_"):
        sq.search(pipe, params={"model__C": [1.0]}, metric=sq.metrics.log_loss).train(
            SEPARABLE, target="y"
        )


class Constant(BaseEstimator, ClassifierMixin):
    """Predicts `label` for every row, whatever it was trained on."""

    def __init__(self, label=0):
        self.label = label

    def fit(self, x, y):
        """Remember the classes."""
        self.classes_ = np.unique(y)
        return self

    def predict(self, x):
        """Predict `label` for every row."""
        return np.full(len(x), self.label)


def _kfold_of(data):
    """Return sqlearn's default fold of each row, for PredefinedSplit."""
    con = connection()
    con.register("nan_data", data)
    try:
        return [
            k
            for (k,) in sq.folds.kfold(5, seed=0)
            .numbered(con.table("nan_data"), "k")
            .project("k")
            .fetchall()
        ]
    finally:
        con.unregister("nan_data")


def test_a_nan_mean_ranks_last_as_gridsearchcv():
    """A setting scoring NaN is never the best, and the best is scikit-learn's."""
    from sklearn.metrics import make_scorer, precision_score
    from sklearn.model_selection import GridSearchCV, PredefinedSplit

    data = SEPARABLE[["a", "b", "y"]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # scikit-learn warns of the NaN mean
        sk = GridSearchCV(
            Constant(),
            {"label": [0, 1]},
            scoring=make_scorer(precision_score, zero_division=np.nan),
            cv=PredefinedSplit(_kfold_of(data)),
        ).fit(data[["a", "b"]], data["y"])
    search = sq.search(
        sq.Pipeline([("model", Constant())]),
        params={"model__label": [0, 1]},
        metric=sq.metrics.precision(zero_division=math.nan),
    ).train(data, target="y")
    assert search.best_params_ == {"model__label": sk.best_params_["label"]}
    assert search.best_score_ == pytest.approx(sk.best_score_, rel=1e-12)


def test_every_setting_nan_is_refused_naming_zero_division():
    """When no setting has a score, the search refuses, naming zero_division."""
    with pytest.raises(sq.errors.SqlearnError, match="zero_division"):
        sq.search(
            sq.Pipeline([("model", Constant())]),
            params={"model__label": [0]},
            metric=sq.metrics.precision(zero_division=math.nan),
        ).train(SEPARABLE, target="y")


def test_f1_macro_matches_gridsearchcv():
    """f1(average="macro") scores as scikit-learn's "f1_macro"."""
    from sklearn.model_selection import GridSearchCV, PredefinedSplit

    data = SEPARABLE[["a", "b", "y"]]
    sk = GridSearchCV(
        LogisticRegression(),
        {"C": [0.01, 1.0]},
        scoring="f1_macro",
        cv=PredefinedSplit(_kfold_of(data)),
    ).fit(data[["a", "b"]], data["y"])
    search = sq.search(
        sq.Pipeline([("model", LogisticRegression())]),
        params={"model__C": [0.01, 1.0]},
        metric=sq.metrics.f1(average="macro"),
    ).train(data, target="y")
    ours = mean_scores(search)
    for params, sk_mean in zip(
        sk.cv_results_["params"], sk.cv_results_["mean_test_score"], strict=True
    ):
        setting = json.dumps({"model__C": params["C"]})
        assert ours[setting] == pytest.approx(sk_mean, rel=1e-12)


def test_a_search_refuses_fbeta_without_beta_before_any_work(monkeypatch):
    """fbeta has no default beta: refused before the data is read."""

    def unread(data, **_):
        raise AssertionError("the data was read")

    monkeypatch.setattr(search_module, "read", unread)
    with pytest.raises(sq.errors.SqlearnError, match=r"beta=.*Why:.*Fix:"):
        sq.search(
            sq.Pipeline([("model", LogisticRegression())]),
            params={"model__C": [1.0]},
            metric=sq.metrics.fbeta,
        ).train(SEPARABLE, target="y")


def test_a_search_refuses_a_metric_that_is_not_a_metric():
    """A plain function is no metric: refused when the search is made."""
    with pytest.raises(sq.errors.SqlearnError, match=r"metric=.*Why:.*Fix:"):
        sq.search(
            sq.Pipeline([("model", LogisticRegression())]),
            metric=lambda *a: 0.0,  # ty: ignore[invalid-argument-type]
        )


def test_fbeta_scores_as_gridsearchcv():
    """fbeta(beta=2) scores as make_scorer(fbeta_score, beta=2)."""
    from sklearn.metrics import fbeta_score, make_scorer
    from sklearn.model_selection import GridSearchCV, PredefinedSplit

    data = SEPARABLE[["a", "b", "y"]]
    sk = GridSearchCV(
        LogisticRegression(),
        {"C": [0.01, 1.0]},
        scoring=make_scorer(fbeta_score, beta=2),
        cv=PredefinedSplit(_kfold_of(data)),
    ).fit(data[["a", "b"]], data["y"])
    search = sq.search(
        sq.Pipeline([("model", LogisticRegression())]),
        params={"model__C": [0.01, 1.0]},
        metric=sq.metrics.fbeta(beta=2),
    ).train(data, target="y")
    ours = mean_scores(search)
    for params, sk_mean in zip(
        sk.cv_results_["params"], sk.cv_results_["mean_test_score"], strict=True
    ):
        setting = json.dumps({"model__C": params["C"]})
        assert ours[setting] == pytest.approx(sk_mean, rel=1e-12)


def test_a_fold_of_one_class_scores_and_does_not_stop_the_search():
    """Held-out rows of one class score with a warning; the search goes on."""
    with pytest.warns(sq.errors.UndefinedMetricWarning):
        search = sq.search(
            sq.Pipeline([("model", Constant())]),
            params={"model__label": [0, 1]},
            metric=sq.metrics.precision,
            folds=sq.folds.time("t", 3),
        ).train(SORTED_BY_CLASS, target="y")
    assert search.best_params_ == {"model__label": 1}


class SeesCategories(ByCode):
    """A model that records the category list it is fitted and scored on."""

    lists: ClassVar[list[list[str]]] = []

    def fit(self, x, y):
        """Record the list and learn nothing else."""
        self.lists.append(x["m"].cat.categories.tolist())
        self.classes_ = np.unique(np.asarray(y))
        return self

    def predict(self, x):
        """Record the list and predict the first class."""
        self.lists.append(x["m"].cat.categories.tolist())
        return np.full(len(x), self.classes_[0])


def test_a_search_codes_an_enum_feature_alike_in_every_fold(monkeypatch):
    """A fold whose training rows lack an ENUM value still sees its declared list."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)
    con = connection()
    con.execute("DROP TABLE IF EXISTS search_enum_t")
    con.execute("DROP TYPE IF EXISTS search_enum_mood")
    con.execute("CREATE TYPE search_enum_mood AS ENUM ('sad', 'ok', 'happy')")
    con.execute("CREATE TABLE search_enum_t (n DOUBLE, m search_enum_mood, y INTEGER)")
    con.execute(
        "INSERT INTO search_enum_t SELECT range, 'sad', range % 2 FROM range(10)"
        " UNION ALL SELECT 10 + range, 'ok', range % 2 FROM range(10)"
    )
    SeesCategories.lists.clear()
    pipe = sq.Pipeline([("model", sq.Model(SeesCategories(), feed="pandas"))])
    sq.search(
        pipe,
        params={"model": [sq.Model(SeesCategories(), feed="pandas")]},
        folds=sq.folds.kfold(2),
    ).train(con.table("search_enum_t"), target="y")
    assert SeesCategories.lists
    assert all(c == ["sad", "ok", "happy"] for c in SeesCategories.lists)


def test_a_failing_fold_leaves_no_optuna_trial_running():
    """A setting whose fold raises fails its trial; the error is unchanged."""
    pytest.importorskip("optuna")
    from optuna.trial import TrialState

    dup = pd.DataFrame({"x": [1.0] * 6 + [2.0] * 6, "y": [0] * 6 + [1] * 6})
    pipe = sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    )
    method = sq.search.optuna(trials=3, seed=0)
    search = sq.search(
        pipe,
        params={"model__C": [1.0, 2.0]},
        method=method,
        folds=sq.folds.kfold(2),
    )
    with pytest.raises(sq.errors.SqlearnError, match="fold 0"):
        search.train(dup, target="y")
    states = [t.state for t in method.study_.trials]
    assert states
    assert set(states) == {TrialState.FAIL}


def test_a_search_prepares_an_edited_table_again_and_says_so(tmp_path):
    """A table edited in place since the last search is prepared again."""
    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("SET memory_limit = '256MB'")  # under half the budget: no warning
    con.execute("CREATE TABLE customers AS FROM SEPARABLE")
    con.execute("CHECKPOINT")
    sq.set_config(connection=con)
    pipe = sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    )
    run = lambda: sq.search(  # noqa: E731
        pipe,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=path,
    ).train("customers", target="y")
    first = run()
    # Negated on every other row: the scaling cannot undo it, so the scores
    # must change.
    con.execute("UPDATE customers SET a = -a WHERE rowid % 2 = 0")
    con.execute("CHECKPOINT")
    with pytest.warns(sq.errors.SqlearnWarning, match="main.customers") as record:
        second = run()
    assert len(record) == 1
    assert first.transforms_ == 2
    assert second.transforms_ == 2  # prepared again, not read back
    assert mean_scores(second) != pytest.approx(mean_scores(first))
