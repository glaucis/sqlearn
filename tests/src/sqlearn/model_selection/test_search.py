"""Tests of the search: grid over settings, fold first, on copies of the pipe."""

import json
import warnings
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import TargetEncoder
from sklearn.tree import DecisionTreeClassifier

import sqlearn as sq
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


def customers(seed=0, rows=600):
    """Return the slice's data: two numbers with gaps, a city, a plan, churned."""
    rng = np.random.default_rng(seed)
    age = rng.normal(40, 12, rows)
    income = rng.normal(3000, 800, rows)
    city = rng.choice(["kyiv", "oslo", "rome"], rows)
    plan = rng.choice(["basic", "pro", "team"], rows)
    logit = (
        0.08 * (age - 40)
        - 0.002 * (income - 3000)
        + (city == "oslo") * 1.5
        - (plan == "team") * 1.0
    )
    churned = (rng.random(rows) < 1 / (1 + np.exp(-logit))).astype(int)
    age[rng.random(rows) < 0.1] = np.nan
    income[rng.random(rows) < 0.1] = np.nan
    return pd.DataFrame(
        {"age": age, "income": income, "city": city, "plan": plan, "churned": churned},
    )


def slice_pipe(model=None):
    """Return the slice's pipeline (spec §2)."""
    return sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric())),
            ("model", LogisticRegression() if model is None else model),
        ]
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
