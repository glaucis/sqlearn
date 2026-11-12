"""Tests of the pipeline: learn, apply and the shape of what comes back."""

import gc
import math
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import INTEGER
from steps_for_tests import MyEncoder, MyScale, dynamic_step

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._selectors import Selector
from sqlearn._store import STORE

AGES = (10.0, 20.0, 30.0)
MEAN = 20.0
SD = math.sqrt(200 / 3)


@pytest.fixture
def people():
    """Return a relation of three people: an age and a city each."""
    return connection().sql(
        "SELECT * FROM (VALUES (10.0, 'b'), (20.0, 'a'), (30.0, 'b')) t(age, city)",
    )


def scale_pipe(**settings):
    """Return a pipeline of one MyScale step named ``scale``."""
    return sq.Pipeline([("scale", MyScale(**settings))])


def test_learn_then_apply_matches_hand_computed_values(people):
    """Scaling three ages gives (age - mean) / population sd."""
    pipe = scale_pipe().learn(people)
    rows = pipe.apply(people).fetchall()
    got = [r[0] for r in rows]
    assert got == pytest.approx([(a - MEAN) / SD for a in AGES])
    assert [r[1] for r in rows] == ["b", "a", "b"]


def test_apply_is_lazy_and_keeps_names(people):
    """`apply` returns a relation, not yet run, with the output's names."""
    pipe = scale_pipe().learn(people)
    rel = pipe.apply(people)
    assert isinstance(rel, duckdb.DuckDBPyRelation)
    assert rel.columns == ["age", "city"]
    assert len(pipe.runs_) == 1
    assert len(pipe.runs_[0].statements) == 1
    assert "20.0" in pipe.runs_[0].statements[0]


def test_out_pandas_and_out_parquet(people, tmp_path):
    """`out=` hands back a pandas frame, or writes a parquet file."""
    pipe = scale_pipe().learn(people)
    frame = pipe.apply(people, out="pandas")
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["age", "city"]
    path = tmp_path / "prepared.parquet"
    pipe.apply(people, out=sq.out.parquet(path))
    rows = connection().sql(f"SELECT * FROM '{path}'").fetchall()
    assert [r[0] for r in rows] == pytest.approx([(a - MEAN) / SD for a in AGES])


def test_set_config_out_is_the_default_and_out_overrides_it(people):
    """The session's `out` applies when a call names none."""
    pipe = scale_pipe().learn(people)
    sq.set_config(out="pandas")
    assert isinstance(pipe.apply(people), pd.DataFrame)
    assert isinstance(pipe.apply(people, out="numpy"), dict)


def test_learned_values_are_attributes(people):
    """A step's learned values read as attributes ending in ``_``."""
    pipe = scale_pipe().learn(people)
    assert pipe["scale"].mean_ == {"age": pytest.approx(MEAN)}
    assert pipe[0].scale_ == {"age": pytest.approx(SD)}


def test_relearning_unchanged_steps_hits_the_store(people):
    """A second `learn` on the same data runs nothing and learns nothing."""
    scale_pipe().learn(people)
    assert STORE.learns["scale"] == 1
    again = scale_pipe().learn(people)
    assert STORE.learns["scale"] == 1
    assert again.runs_ == []
    assert again["scale"].mean_ == {"age": pytest.approx(MEAN)}


def test_learning_from_no_rows_is_refused():
    """Learning from no rows names the step; no NULL values are stored."""
    empty = connection().sql("SELECT 1.0 AS age WHERE false")
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*no rows") as err:
        scale_pipe().learn(empty)
    assert err.value.step == "scale"
    assert err.value.position == 1
    assert len(STORE) == 0


def test_apply_names_a_missing_column(people):
    """Data at apply without a learned column, or with it as text, is named."""
    pipe = scale_pipe().learn(people)
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'age'"):
        pipe.apply(connection().sql("SELECT 'b' AS city"))
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'age'.*VARCHAR"):
        pipe.apply(connection().sql("SELECT '10' AS age, 'b' AS city"))


def test_a_selector_matching_nothing_names_the_step():
    """A selector choosing no column stops `learn`, naming the step."""
    text = connection().sql("SELECT 'b' AS city")
    with pytest.raises(
        sq.errors.StepError, match=r"scale \(step 1\).*matches no column"
    ):
        scale_pipe().learn(text)


@pytest.mark.parametrize("given", [["age", "incme"], "incme", sq.cols("age", "incme")])
def test_a_name_not_in_the_data_is_refused(given):
    """A misspelt name in cols= is refused, naming it and the columns there."""
    df = pd.DataFrame({"age": [1.0, 2.0, 3.0], "income": [5.0, 6.0, 9.0]})
    with pytest.raises(
        sq.errors.StepError, match=r"s \(step 1\).*'incme'.*'age', 'income'.*Fix:"
    ):
        sq.Pipeline([("s", sq.scale.standard(cols=given))]).learn(df)


def test_a_name_made_by_an_earlier_step_is_accepted():
    """A name a dynamic step creates is found once that step has learned."""
    df = pd.DataFrame({"city": ["a", "b"], "x": [1.0, 2.0]})
    pipe = sq.Pipeline(
        [("oh", sq.encode.onehot(["city"])), ("s", sq.scale.standard(["city_a"]))]
    )
    assert list(pipe.learn(df)["s"].center_) == ["city_a"]


def test_keep_adds_a_named_column(people):
    """With keep, the scaled column is added beside the original."""
    pipe = scale_pipe(keep=True).learn(people)
    rel = pipe.apply(people)
    assert rel.columns == ["age", "age_scale", "city"]
    assert [r[0] for r in rel.fetchall()] == list(AGES)


def test_a_kept_name_in_use_is_numbered():
    """With keep, a new name taken by an input column is numbered (ADR 0035)."""
    data = connection().sql(
        "SELECT * FROM (VALUES (10.0::DOUBLE, 1.0::DOUBLE), (30.0, 2.0)) "
        "t(age, age_scale)"
    )
    pipe = sq.Pipeline(
        [
            ("scale", MyScale(cols=["age"], keep=True)),
            ("double", sq.Step(cols=["age_scale_2"], apply=lambda x: x * 2)),
        ]
    ).learn(data)
    assert pipe.columns_out_ == ["age", "age_scale_2", "age_scale"]
    alone = sq.Pipeline([MyScale(cols=["age"], keep=True)]).learn(data).apply(data)
    doubled = [(a, 2 * s, k) for a, s, k in alone.fetchall()]
    assert pipe.apply(data).fetchall() == doubled
    assert [k for _, _, k in doubled] == [1.0, 2.0]


def test_a_new_dynamic_column_never_renames_an_input_column():
    """A dynamic step's new column taking a name in use is numbered."""
    data = connection().sql("SELECT 'a' AS city, 1 AS city_a")
    pipe = sq.Pipeline([("onehot", MyEncoder())]).learn(data)
    assert pipe.columns_out_ == ["city_a_2", "city_a"]


def test_selectors_are_fixed_at_learn(people):
    """At apply a numeric column unseen at learn is left as it is."""
    pipe = scale_pipe().learn(people)
    more = connection().sql("SELECT 20.0 AS age, 'a' AS city, 7.0 AS extra")
    assert pipe.apply(more).fetchall() == [(0.0, "a", 7.0)]


def test_columns_out_without_running(people):
    """`columns_out_` is known after learn; only learn statements ran."""
    pipe = sq.Pipeline([("onehot", MyEncoder()), ("scale", MyScale())])
    pipe.learn(people)
    assert pipe.columns_out_ == ["age", "city_a", "city_b"]
    assert len(pipe.runs_) == 2
    assert all(len(run.statements) == 1 for run in pipe.runs_)


def test_a_dynamic_step_then_a_step_waiting_for_it(people):
    """Scale after OneHot learns in the second run, on the new columns."""
    pipe = sq.Pipeline([("onehot", MyEncoder()), ("scale", MyScale())])
    pipe.learn(people)
    assert pipe["scale"].mean_ == {
        "age": pytest.approx(MEAN),
        "city_a": pytest.approx(1 / 3),
        "city_b": pytest.approx(2 / 3),
    }
    rows = pipe.apply(people).fetchall()
    assert rows[1][1] == pytest.approx((1 - 1 / 3) / math.sqrt(2 / 9))


class IntEncoder(MyEncoder):
    """MyEncoder declared dynamic, creating integer columns."""

    static = False
    creates = INTEGER


class CountText(sq.Step):
    """Learn how many values each column has; leave the column as it is."""

    def learn(self, x):
        """Count the values."""
        return {"n": sq.agg.count(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def test_a_step_not_waiting_skips_a_pending_dynamic_step():
    """A text step after OneHot learns in the first run, not seeing ``city``."""
    data = connection().sql(
        "SELECT * FROM (VALUES ('x', 'b'), ('y', 'a')) t(name, city)",
    )
    pipe = sq.Pipeline(
        [("onehot", IntEncoder()), ("text", CountText(sq.cols.string()))]
    )
    pipe.learn(data)
    assert len(pipe.runs_) == 1
    assert pipe["text"].n_ == {"name": 2}
    assert pipe.columns_out_ == ["name", "city_a", "city_b"]


def test_a_step_waiting_between_steps_of_the_first_run():
    """Scale waits for OneHot; the text step after it learns in the first run."""
    data = connection().sql(
        "SELECT * FROM (VALUES ('x', 1.0, 'b'), ('y', 2.0, 'a')) t(name, age, city)",
    )
    steps = [
        ("onehot", IntEncoder()),
        ("scale", MyScale()),
        ("text", CountText(sq.cols.string())),
    ]
    pipe = sq.Pipeline(steps).learn(data)
    assert len(pipe.runs_) == 2
    assert '"l03_text"' in pipe.runs_[0].statements[0]
    assert '"l02_scale"' not in pipe.runs_[0].statements[0]
    assert pipe["text"].n_ == {"name": 2}
    assert pipe.columns_out_ == ["name", "age", "city_a", "city_b"]


@dataclass(frozen=True, repr=False)
class Named(Selector):
    """Choose columns by name; never a column whose name is not known yet."""

    names: tuple[str, ...]

    def _matches(self, name, dtype):
        return name in self.names

    def _may(self, dtype):
        return False

    def _must(self, dtype):
        return False


def test_a_waiting_dynamic_step_hides_its_columns_from_the_first_run():
    """A column a later dynamic step replaces is not seen by an earlier run."""
    data = connection().sql(
        "SELECT * FROM (VALUES ('x', 1.0, 'b'), ('y', 2.0, 'a')) t(name, age, city)",
    )
    steps = [
        ("onehot", IntEncoder()),
        ("scale", MyScale()),
        ("bucket", dynamic_step(["age"])),
        ("text", CountText(Named(("name", "age")))),
    ]
    pipe = sq.Pipeline(steps).learn(data)
    assert pipe["text"].n_ == {"name": 2}
    assert len(pipe.runs_) == 2


def test_a_step_learning_nothing_runs_nothing(people):
    """A pipeline whose steps learn nothing runs no SQL at learn."""
    pipe = sq.Pipeline([("copy", sq.Step())]).learn(people)
    assert pipe.runs_ == []
    assert STORE.learns["copy"] == 1
    assert pipe.apply(people).fetchall() == people.fetchall()


def test_a_dynamic_step_may_keep_its_input(people):
    """With keep, OneHot's new columns follow the column it read."""
    pipe = sq.Pipeline([("onehot", MyEncoder(keep=True))]).learn(people)
    assert pipe.columns_out_ == ["age", "city", "city_a", "city_b"]


def test_a_stored_step_is_applied_while_others_learn(people):
    """A step found in the store is applied with its values in a later learn."""
    sq.Pipeline([("scale", MyScale(cols=["age"]))]).learn(people)
    pipe = sq.Pipeline([("scale", MyScale(cols=["age"])), ("onehot", MyEncoder())])
    pipe.learn(people)
    assert STORE.learns == {"scale": 1, "onehot": 1}
    assert "20.0" in pipe.runs_[0].statements[0]
    assert pipe.columns_out_ == ["age", "city_a", "city_b"]


def test_sql_duckdb_refuses_names_the_step(people):
    """A step whose SQL DuckDB cannot bind is named in the message."""
    add_text = type(
        "AddText",
        (sq.Step,),
        {"apply": lambda self, x, learned: duckdb.FunctionExpression("no_such", x)},
    )
    pipe = sq.Pipeline([("scale", MyScale()), ("bad", add_text(cols=["age"]))])
    with pytest.raises(sq.errors.StepError, match=r"bad \(step 2\).*DuckDB refuses"):
        pipe.learn(people)


class _Model:
    """A stand-in model: anything with fit and predict is one."""

    def fit(self, x, y):
        return self

    def predict(self, x):
        return x


def test_a_plain_list_names_its_steps():
    """Plain steps are named by default_name, a model "model"; clashes numbered."""
    pipe = sq.Pipeline([MyScale(), MyEncoder(), MyScale(), _Model()])
    assert [n for n, _ in pipe.steps] == ["step-1", "step-2", "step-3", "model"]
    assert list(pipe.named_steps) == ["step-1", "step-2", "step-3", "model"]


def test_default_name_of_a_step_is_step():
    """The base step's name in a plain list is "step"."""
    assert sq.Step().default_name() == "step"


def test_a_step_may_override_default_name():
    """A step's own default_name is what a plain list uses."""

    class Named(sq.Step):
        def default_name(self):
            return "named"

    pipe = sq.Pipeline([Named(), Named(), sq.Step()])
    assert [n for n, _ in pipe.steps] == ["named-1", "named-2", "step"]


@pytest.mark.parametrize("item", [("a", sq.Step("a"), "extra"), ("a",), ()])
def test_a_tuple_that_is_not_a_pair_is_refused(item):
    """A named step is a pair (name, step); a longer or shorter tuple is refused."""
    with pytest.raises(sq.errors.SqlearnError, match=r"item 1 .*\(name, step\)"):
        sq.Pipeline([item])


def test_pairs_and_plain_steps_mix():
    """Given names stay; plain items take the default."""
    pipe = sq.Pipeline([("first", sq.Step("a")), sq.Step("b")])
    assert [n for n, _ in pipe.steps] == ["first", "step"]


def test_numbering_does_not_clash_with_a_given_name():
    """A plain step numbered into a given name is moved on to the next free one."""
    pipe = sq.Pipeline([("step-1", sq.Step()), sq.Step(), sq.Step()])
    assert [n for n, _ in pipe.steps] == ["step-1", "step-2", "step-3"]


def test_two_models_are_numbered():
    """Two models in a list are model-1 and model-2."""
    pipe = sq.Pipeline([_Model(), _Model()])
    assert [n for n, _ in pipe.steps] == ["model-1", "model-2"]


def test_equal_given_names_are_refused():
    """Two equal given names are refused, as before."""
    with pytest.raises(sq.errors.SqlearnError, match="'a'"):
        sq.Pipeline([("a", sq.Step()), ("a", sq.Step())])


def test_make_pipeline_is_gone():
    """The function is removed with no alias."""
    assert not hasattr(sq, "make_pipeline")


def test_a_frame_result_outlives_the_frame():
    """A lazy result of a pandas frame still reads after the frame is dropped."""
    frame = pd.DataFrame({"age": list(AGES)})
    pipe = scale_pipe().learn(frame)
    rel = pipe.apply(frame)
    del frame
    gc.collect()
    assert len(rel.fetchall()) == 3


def test_each_input_is_read_once(people, monkeypatch):
    """`learn` and `apply` read their input once per call."""
    from sqlearn import _pipeline

    calls = []
    real = _pipeline.read

    def counting(data, **kwargs):
        calls.append(data)
        return real(data, **kwargs)

    monkeypatch.setattr(_pipeline, "read", counting)
    pipe = sq.Pipeline([("onehot", MyEncoder()), ("scale", MyScale())])
    pipe.learn(people)
    pipe.apply(people)
    assert len(calls) == 2


def test_apply_before_learn_is_refused(people):
    """`apply` before `learn` says to learn first."""
    with pytest.raises(sq.errors.SqlearnError, match="learn"):
        scale_pipe().apply(people)
    with pytest.raises(AttributeError, match="learn"):
        _ = scale_pipe().columns_out_


def test_steps_must_be_named_uniquely_and_be_steps(people):
    """Two steps sharing a name, or an object that is not a step, are refused."""
    with pytest.raises(sq.errors.SqlearnError, match="'scale'"):
        sq.Pipeline([("scale", MyScale()), ("scale", MyScale())])
    with pytest.raises(sq.errors.SqlearnError, match="not a step"):
        sq.Pipeline([("model", object())]).learn(people)


def test_a_relation_is_read_on_its_own_connection():
    """Another connection's table is refused, then read once it is configured."""
    connection().sql("CREATE TABLE t AS SELECT 100.0 AS a")
    other = duckdb.connect()
    other.sql("CREATE TABLE t AS SELECT * FROM (VALUES (1.0), (3.0)) v(a)")
    pipe = sq.Pipeline([("scale", MyScale())])
    with pytest.raises(sq.errors.SqlearnError, match="another DuckDB connection"):
        pipe.learn(other.table("t"))
    sq.set_config(connection=other)
    pipe.learn(other.table("t"))
    assert pipe["scale"].mean_ == {"a": pytest.approx(2.0)}
    assert [r[0] for r in pipe.apply(other.table("t")).fetchall()] == [-1.0, 1.0]


def test_a_replacement_scan_relation_is_learned():
    """A relation scanning a frame by its Python name learns its values."""
    frame = pd.DataFrame({"a": [1.0, 3.0]})
    rel = connection().sql("FROM frame")
    del frame
    gc.collect()
    pipe = sq.Pipeline([("scale", MyScale())]).learn(rel)
    assert pipe["scale"].mean_ == {"a": pytest.approx(2.0)}
    assert len(pipe.apply(rel).fetchall()) == 2


def test_a_source_duckdb_cannot_bind_is_an_input_error(people, monkeypatch):
    """A source failing to bind is reported as the input's, not a step's."""
    from sqlearn import _inputs, _pipeline

    source = _inputs.read(people)
    connection().execute(
        source.relation.sql_query().replace("SELECT * FROM", "DROP VIEW")
    )
    monkeypatch.setattr(_pipeline, "read", lambda data, **_: source)
    with pytest.raises(sq.errors.SqlearnError, match="cannot read the input") as err:
        sq.Pipeline([("scale", MyScale())]).learn(people)
    assert not isinstance(err.value, sq.errors.StepError)


def customers(seed, rows=300):
    """Return seeded customers: two numbers with gaps, a city, and churned."""
    rng = np.random.default_rng(seed)
    age = rng.normal(40, 12, rows)
    income = rng.normal(3000, 800, rows)
    city = rng.choice(["kyiv", "oslo", "rome"], rows)
    logit = 0.08 * (age - 40) - 0.002 * (income - 3000) + (city == "oslo") * 1.5
    churned = (rng.random(rows) < 1 / (1 + np.exp(-logit))).astype(int)
    age[rng.random(rows) < 0.1] = np.nan
    income[rng.random(rows) < 0.1] = np.nan
    return pd.DataFrame(
        {"age": age, "income": income, "city": city, "churned": churned},
    )


def churn_pipe(model):
    """Return Impute, OneHot and Scale, then the model."""
    return sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(["city"])),
            ("scale", sq.scale.standard(sq.cols.numeric())),
            ("model", model),
        ]
    )


class Echo:
    """A model predicting its first column, to check where each row lands."""

    def fit(self, x, y):
        """Remember what was handed over."""
        self.shape_ = x.shape
        self.y_ = y
        return self

    def predict(self, x):
        """Return the first column."""
        return x[:, 0]


def test_train_predict_matches_sklearn_pipeline():
    """Impute, OneHot, Scale, LogisticRegression: as scikit-learn's pipeline."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline as sk_make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    train, new = customers(1), customers(2)
    new.loc[0, "city"] = "riga"  # unseen: all zeros, as handle_unknown="ignore"
    features = ["age", "income", "city"]
    sk = sk_make_pipeline(
        ColumnTransformer(
            [
                ("num", SimpleImputer(strategy="median"), ["age", "income"]),
                ("cat", OneHotEncoder(handle_unknown="ignore"), ["city"]),
            ]
        ),
        StandardScaler(),
        LogisticRegression(),
    ).fit(train[features], train["churned"])
    pipe = churn_pipe(LogisticRegression()).train(train, target="churned")
    assert pipe.columns_out_ == [
        "age",
        "income",
        "city_kyiv",
        "city_oslo",
        "city_rome",
    ]
    np.testing.assert_allclose(pipe["model"].coef_, sk[-1].coef_, rtol=1e-6)
    np.testing.assert_allclose(pipe["model"].intercept_, sk[-1].intercept_, rtol=1e-6)
    got = pipe.predict(new, out="numpy")["prediction"]
    np.testing.assert_array_equal(got, sk.predict(new[features]))
    # The same arrays give the same probabilities: the models are one model.
    prepared = sk[:-1].transform(new[features])
    np.testing.assert_allclose(
        pipe["model"].predict_proba(prepared),
        sk.predict_proba(new[features]),
        rtol=1e-6,
    )


def test_a_target_named_like_a_created_column_does_not_renumber_it():
    """Learn and train name created columns against the same columns.

    The target is set aside before the steps learn, and so before their new
    columns are named: a target spelt like one (``city_oslo`` beside OneHot's
    ``city_Oslo``) numbers nothing, at learn as in the data fed to the model.
    """
    frame = pd.DataFrame(
        {"city": ["Oslo", "Rome", "Oslo", "Rome"], "city_oslo": [1, 0, 1, 0]}
    )
    pipe = sq.Pipeline([("hot", sq.encode.onehot("city")), ("model", Echo())])
    pipe.train(frame, target="city_oslo")
    assert pipe.columns_out_ == ["city_Oslo", "city_Rome"]
    assert pipe._names == [{"city": ["city_Oslo", "city_Rome"]}]
    assert pipe["model"].shape_ == (4, 2)
    got = pipe.predict(frame, out="numpy")["prediction"]
    assert got.tolist() == [1, 0, 1, 0]


def test_the_target_is_never_scaled():
    """A numeric target is set aside: no selector matches it, no step sees it."""
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [0.0, 1.0, 0.0, 1.0]})
    pipe = sq.Pipeline(
        [("scale", sq.scale.standard(sq.cols.numeric())), ("model", Echo())]
    )
    pipe.train(frame, target="y")
    assert pipe["scale"].center_ == {"x": 2.5}
    assert pipe.columns_out_ == ["x"]
    assert pipe["model"].shape_ == (4, 1)
    assert sorted(pipe["model"].y_.tolist()) == [0.0, 0.0, 1.0, 1.0]


def test_target_and_features_come_from_one_query():
    """Each row's target travels with its features; train records its runs."""
    frame = pd.DataFrame({"x": [3.0, 1.0, 2.0], "y": [30, 10, 20]})
    pipe = sq.Pipeline([("model", Echo())]).train(frame, target="y")
    assert pipe["model"].y_.tolist() == [30, 10, 20]
    pipe = churn_pipe(Echo()).train(customers(3), target="churned")
    # Run 1 learns Impute and OneHot; run 2 learns Scale and feeds the model.
    assert [len(r.statements) for r in pipe.runs_] == [1, 2]
    assert '"churned"' in pipe.runs_[-1].statements[-1]
    pipe.train(customers(3), target="churned")
    assert [len(r.statements) for r in pipe.runs_] == [1]


def test_predict_returns_one_column_in_input_order():
    """`predict` gives a lazy relation of one column, one row per input row."""
    frame = pd.DataFrame({"x": [5.0, 1.0, 4.0, 2.0, 3.0], "y": [1, 0, 1, 0, 1]})
    pipe = sq.Pipeline([("impute", sq.impute()), ("model", Echo())])
    pipe.train(frame, target="y")
    rel = pipe.predict(frame.drop(columns="y"))
    assert isinstance(rel, duckdb.DuckDBPyRelation)
    assert rel.columns == ["prediction"]
    assert [r[0] for r in rel.fetchall()] == [5.0, 1.0, 4.0, 2.0, 3.0]
    assert len(pipe.runs_) == 1
    assert len(pipe.runs_[0].statements) == 1
    # Data holding the target is predicted too: the target is not a feature.
    assert [r[0] for r in pipe.predict(frame).fetchall()] == [5, 1, 4, 2, 3]


def test_predictions_line_up_with_a_large_parquet_input(tmp_path):
    """A million rows read by several threads come back in the input's order."""
    path = tmp_path / "big.parquet"
    connection().execute(
        "COPY (SELECT (i * 7919) % 1000003 AS x, i % 2 AS y FROM range(1000000) "
        f"t(i)) TO '{path}' (FORMAT parquet, ROW_GROUP_SIZE 50000)"
    )
    threads = connection().sql("SELECT current_setting('threads')").fetchall()
    assert threads[0][0] > 1
    pipe = sq.Pipeline([("impute", sq.impute()), ("model", Echo())])
    pipe.train(path, target="y")
    got = pipe.predict(path, out="numpy")["prediction"]
    want = connection().sql(f"SELECT x FROM '{path}'").fetchnumpy()["x"]
    np.testing.assert_array_equal(got, want)


def test_predictions_keep_the_model_labels():
    """Text labels come back as text."""
    from sklearn.tree import DecisionTreeClassifier

    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0], "y": ["no", "yes", "no", "yes"]})
    pipe = sq.Pipeline([("model", DecisionTreeClassifier())]).train(frame, "y")
    assert [r[0] for r in pipe.predict(frame).fetchall()] == ["no", "yes", "no", "yes"]


def test_predictions_outlive_the_input():
    """The predictions stay readable after the input and the call are gone."""
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    pipe = sq.Pipeline([("model", Echo())]).train(frame, target="y")
    rel = pipe.predict(pd.DataFrame({"x": [7.0, 8.0]}))
    gc.collect()
    assert rel.fetchall() == [(7.0,), (8.0,)]


def test_train_takes_a_model_or_a_wrapped_model_and_a_feed():
    """`sq.Model` carries the feed; `train(feed=...)` overrides it per call."""
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    pipe = sq.Pipeline([("model", sq.Model(Echo(), feed="numpy"))])
    pipe.train(frame, target="y")
    assert [r[0] for r in pipe.predict(frame).fetchall()] == [1.0, 2.0]
    with pytest.raises(sq.errors.SqlearnError, match=r"'parquet'.*numpy"):
        pipe.train(frame, target="y", feed="parquet")
    pipe.train(frame, target="y", feed="pandas")
    assert isinstance(pipe["model"].estimator.y_, pd.Series)


def test_train_and_predict_refuse_mistakes():
    """A missing target, no model, or predict before train are explained."""
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    with pytest.raises(sq.errors.SqlearnError, match=r"'churned'.*'x', 'y'"):
        sq.Pipeline([("model", Echo())]).train(frame, target="churned")
    with pytest.raises(sq.errors.SqlearnError, match="no model"):
        scale_pipe().train(frame, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="train"):
        sq.Pipeline([("model", Echo())]).predict(frame)
    with pytest.raises(sq.errors.SqlearnError, match="ends in a model"):
        sq.Pipeline([("model", Echo())]).learn(frame)
    with pytest.raises(sq.errors.SqlearnError, match="not a step"):
        sq.Pipeline([("model", Echo()), ("scale", MyScale())]).train(frame, "y")
    gaps = connection().sql("SELECT * FROM (VALUES (1.0, 0), (2.0, NULL)) t(x, y)")
    with pytest.raises(sq.errors.SqlearnError, match="target 'y' is missing in 1 row"):
        sq.Pipeline([("model", Echo())]).train(gaps, target="y")


def test_a_failed_retrain_keeps_the_trained_pipeline():
    """A retrain refused before fit leaves the old values and the old model."""
    frame = pd.DataFrame({"x": [3.0, 1.0, 2.0], "y": [1, 0, 1]})
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Echo())])
    pipe.train(frame, target="y")
    gaps = connection().sql("SELECT * FROM (VALUES (100.0, 0), (300.0, NULL)) t(x, y)")
    with pytest.raises(sq.errors.SqlearnError, match="missing"):
        pipe.train(gaps, target="y")
    assert pipe["scale"].center_ == {"x": 2.0}
    assert pipe["model"].y_.tolist() == [1, 0, 1]
    got = [r[0] for r in pipe.predict(pd.DataFrame({"x": [2.0]})).fetchall()]
    assert got == [0.0]


class Failing(Echo):
    """A model whose fit fails on its second call."""

    calls = 0

    def fit(self, x, y):
        """Fit once, then fail."""
        self.calls += 1
        if self.calls > 1:
            msg = "cannot fit"
            raise ValueError(msg)
        return super().fit(x, y)


def test_a_failed_fit_leaves_the_pipeline_untrained():
    """When fit itself fails, predict is refused rather than run half-changed."""
    frame = pd.DataFrame({"x": [3.0, 1.0, 2.0], "y": [1, 0, 1]})
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Failing())])
    pipe.train(frame, target="y")
    with pytest.raises(ValueError, match="cannot fit"):
        pipe.train(pd.DataFrame({"x": [100.0, 300.0], "y": [0, 1]}), target="y")
    assert pipe["scale"].center_ == {"x": 2.0}
    with pytest.raises(sq.errors.SqlearnError, match="not been trained"):
        pipe.predict(frame)


def test_predict_refuses_data_missing_a_trained_column():
    """A column passed through to the model must be there at predict."""
    frame = pd.DataFrame({"x": [1.0, 2.0], "z": [5.0, 6.0], "y": [0, 1]})
    pipe = sq.Pipeline([("scale", sq.scale.standard(["x"])), ("model", Echo())])
    pipe.train(frame, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="no column 'z'"):
        pipe.predict(pd.DataFrame({"x": [1.0]}))


def test_predict_refuses_the_row_number_name():
    """A column named as sqlearn's row number is refused as an input error."""
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    pipe = sq.Pipeline([("model", Echo())]).train(frame, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="'__sqlearn_row'"):
        pipe.predict(pd.DataFrame({"x": [1.0], "__sqlearn_row": [1]}))


def test_predict_refuses_a_connection_not_keeping_order():
    """Without preserve_insertion_order, rows could not be matched: refused."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '256MB'")  # under half the budget: no warning
    sq.set_config(connection=con)
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    pipe = sq.Pipeline([("model", Echo())]).train(frame, target="y")
    con.execute("SET preserve_insertion_order = false")
    with pytest.raises(sq.errors.SqlearnError, match="preserve_insertion_order"):
        pipe.predict(frame)


def test_a_column_removed_upstream_is_in_a_later_steps_key():
    """A later step whose inputs changed upstream learns again, never stale."""
    df = pd.DataFrame(
        {"city": ["a", "b", "a"], "region": ["n", "s", "s"], "plan": ["x", "y", "z"]}
    )

    def pipe(cols):
        return sq.Pipeline(
            [
                ("onehot", sq.encode.onehot(cols=cols)),
                ("ordinal", sq.encode.ordinal(sq.cols.string())),
            ]
        )

    pipe(["city", "region"]).learn(df)
    second = pipe(["city"]).learn(df)
    assert list(second["ordinal"].categories_) == ["region", "plan"]
    got = second.apply(df).fetchall()
    STORE.clear()
    assert got == pipe(["city"]).learn(df).apply(df).fetchall()
    assert all(isinstance(v, int) for row in got for v in row)


class _TargetStep(sq.Step):
    """A step learning the target's mean; how it fails is set per test."""

    uses_target = True
    static = True

    def __init__(self, cols="x", keep=False, cv=2, seed=0, broken=""):
        super().__init__(cols, keep)
        self.cv = cv
        self.seed = seed
        self.broken = broken

    def learn(self, x, y=None):
        return {"mean": sq.agg.mean(y)}

    def derive(self, values, k):
        if self.broken == "derive":
            raise ValueError("no luck")
        return super().derive(values, k)

    def apply(self, x, learned):
        if self.broken == "apply":
            return {"a": x}
        return x * learned.mean


def target_frame():
    """Return eight rows of a number and a 0/1 target."""
    return pd.DataFrame({"x": [float(i) for i in range(8)], "y": [0, 1] * 4})


def test_a_user_target_step_learns_without_cross_fitting_by_default():
    """The default derive gives every fold the values learned on all rows."""
    pipe = sq.Pipeline([_TargetStep(), Echo()]).train(target_frame(), target="y")
    assert pipe["step"].mean_ == {"x": 0.5}
    np.testing.assert_allclose(pipe.predict(target_frame(), out="numpy")["prediction"],
                               [i * 0.5 for i in range(8)])  # fmt: skip


def test_a_target_steps_failures_name_it():
    """A failing derive is diagnosed; a mapping from apply is refused."""
    with pytest.raises(sq.errors.StepError, match=r"step \(step 1\).*derive"):
        sq.Pipeline([_TargetStep(broken="derive"), Echo()]).train(
            target_frame(), target="y"
        )
    with pytest.raises(sq.errors.StepError, match="one expression"):
        sq.Pipeline([_TargetStep(broken="apply"), Echo()]).train(
            target_frame(), target="y"
        )


def test_a_column_named_as_the_target_aside_is_refused():
    """The name the target travels under is kept: a column of it is refused."""
    frame = target_frame().assign(__sqlearn_target=1.0)
    with pytest.raises(sq.errors.SqlearnError, match="__sqlearn_target"):
        sq.Pipeline([_TargetStep(), Echo()]).train(frame, target="y")


def test_each_step_hears_what_it_learned_once_per_learn(people):
    """`Step.learned` is called once per learn, a store hit too, never on apply."""
    heard = []

    class Heard(MyScale):
        def learned(self, values):
            heard.append(values)

    pipe = sq.Pipeline([("scale", Heard(cols=["age"]))])
    pipe.learn(people)
    assert heard == [{"age": {"mean": MEAN, "scale": pytest.approx(SD)}}]
    pipe.apply(people).fetchall()
    assert len(heard) == 1
    pipe.learn(people)
    assert len(heard) == 2
    assert heard[1] == heard[0]


def _mixed():
    """Return a frame of a number, two texts and a 0/1 target."""
    return pd.DataFrame(
        {
            "age": [1.0, 2.0, 3.0, 4.0] * 5,
            "city": ["a", "b", None, "a"] * 5,
            "plan": ["x", "y", "x", "y"] * 5,
            "y": [0, 1, 0, 1] * 5,
        }
    )


@pytest.mark.parametrize(
    ("first", "encoded"),
    [
        ([sq.encode.target("city")], {"plan"}),
        ([sq.encode.onehot("city")], {"plan"}),
        ([sq.impute.indicator("city")], {"city", "plan"}),
        ([sq.impute.mode("city", indicator=True), sq.encode.target("city")], {"plan"}),
    ],
    ids=["target", "dynamic", "keeping", "target-in-a-later-run"],
)
def test_a_step_not_yet_applied_stays_so_past_a_later_bind(first, encoded):
    """A learning step's changes hold past a later static step in its run.

    The target encoder makes ``city`` a number, so a later step by type must
    not read it as text, even after a static step between them is bound;
    so too when the encoder learns only in a later run.
    """
    frame = _mixed()
    steps = [*first, sq.scale.standard("age"), sq.encode.ordinal()]
    pipe = sq.Pipeline(steps).learn(frame, target="y")
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == pipe.columns_out_
    assert set(pipe["ordinal"].categories_) == encoded


def test_applying_to_an_edited_table_does_not_warn(tmp_path):
    """Apply and predict reuse what was learned: only learning again warns."""
    from sklearn.linear_model import LogisticRegression

    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("SET memory_limit = '256MB'")  # under half the budget: no warning
    con.execute(
        "CREATE TABLE customers AS "
        "SELECT range::DOUBLE AS x, range % 2 AS y FROM range(40)"
    )
    con.execute("CHECKPOINT")
    sq.set_config(connection=con)
    steps = sq.Pipeline([("scale", sq.scale.standard())])
    model = sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    )
    steps.learn("customers")
    model.train("customers", target="y")
    con.execute("UPDATE customers SET x = -x WHERE y = 0")
    con.execute("CHECKPOINT")
    steps.apply("customers").fetchall()
    model.predict("customers")
    with pytest.warns(sq.errors.SqlearnWarning, match="main.customers"):
        steps.learn("customers")


def _model_pipe(model=None):
    from sklearn.linear_model import LogisticRegression

    return sq.Pipeline(
        [("scale", sq.scale.standard()), ("model", model or LogisticRegression())]
    )


MODEL_DATA = pd.DataFrame(
    {"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "z": [3.0, 1.0, 2.0, 6.0, 4.0, 5.0],
     "y": [0, 0, 0, 1, 1, 1]}
)  # fmt: skip


def test_model_is_the_trained_estimator():
    """`model_` is the library's own object, not the `sq.Model` wrapper."""
    pipe = _model_pipe().train(MODEL_DATA, target="y")
    assert pipe.model_ is pipe.steps[-1][1] or pipe.model_ is pipe["model"].estimator
    assert type(pipe.model_).__name__ == "LogisticRegression"
    assert not isinstance(pipe.model_, sq.Model)


def test_model_refuses_before_train():
    """`model_` on an untrained pipeline, or one without a model, says to train."""
    for pipe in (_model_pipe(), scale_pipe()):
        with pytest.raises(
            sq.errors.SqlearnError,
            match=r"Fix: call train\(data, target=\.\.\.\) first",
        ):
            pipe.model_  # noqa: B018


def test_use_model_puts_a_trained_model_back():
    """B, trained on other labels, predicts as A once given A's model."""
    flipped = MODEL_DATA.assign(y=[1, 1, 1, 0, 0, 0])
    a = _model_pipe().train(MODEL_DATA, target="y")
    b = _model_pipe().train(flipped, target="y")
    assert b.predict(MODEL_DATA, out="numpy")["prediction"].tolist() != (
        a.predict(MODEL_DATA, out="numpy")["prediction"].tolist()
    )
    assert b.use_model(a.model_) is b
    assert b.model_ is a.model_
    assert b.predict(MODEL_DATA, out="numpy")["prediction"].tolist() == (
        a.predict(MODEL_DATA, out="numpy")["prediction"].tolist()
    )


def test_use_model_refuses_a_pipeline_without_a_model_step():
    """Refusal 1: the last element is a step."""
    from sklearn.linear_model import LogisticRegression

    with pytest.raises(sq.errors.SqlearnError, match="no model"):
        scale_pipe().use_model(LogisticRegression())


def test_use_model_refuses_without_a_training_record_and_data():
    """Refusal 2: nothing was trained and no data was given."""
    from sklearn.linear_model import LogisticRegression

    trained = LogisticRegression().fit([[1.0], [2.0]], [0, 1])
    with pytest.raises(
        sq.errors.SqlearnError, match="Fix: pass the training data, as use_model"
    ):
        _model_pipe().use_model(trained)


def test_use_model_refuses_an_object_that_is_not_a_model():
    """Refusal 3: no fit or predict."""
    pipe = _model_pipe().train(MODEL_DATA, target="y")
    with pytest.raises(sq.errors.SqlearnError, match=r"fit.*predict"):
        pipe.use_model(object())


def test_use_model_refuses_another_class_than_the_recipes():
    """Refusal 4: the model must be the class the recipe names."""
    from sklearn.linear_model import RidgeClassifier

    pipe = _model_pipe().train(MODEL_DATA, target="y")
    other = RidgeClassifier().fit([[1.0], [2.0]], [0, 1])
    with pytest.raises(
        sq.errors.SqlearnError,
        match=(
            r"RidgeClassifier.*LogisticRegression.*Fix: build the pipeline "
            r"with that model, or pass a LogisticRegression"
        ),
    ):
        pipe.use_model(other)


def test_use_model_refuses_a_model_not_trained():
    """Refusal 5: an unfitted model."""
    from sklearn.linear_model import LogisticRegression

    pipe = _model_pipe().train(MODEL_DATA, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="not trained"):
        pipe.use_model(LogisticRegression())


def test_use_model_refuses_a_class_instead_of_a_model():
    """A class is not a trained model: the Fix asks for an object."""
    from sklearn.linear_model import LogisticRegression

    pipe = _model_pipe().train(MODEL_DATA, target="y")
    with pytest.raises(
        sq.errors.SqlearnError, match=r"is a class.*Fix:.*trained model object"
    ):
        pipe.use_model(LogisticRegression)


TEXT_DATA = pd.DataFrame(
    {
        "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "city": ["b", "a", "c", "a", "b", "c"],
        "kind": ["u", "v", "v", "u", "w", "w"],
        "y": [0, 0, 0, 1, 1, 1],
    }
)


def _text_pipe(feed):
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        categorical_features="from_dtype" if feed == "pandas" else None
    )
    return sq.Pipeline([sq.Model(model, feed=feed)])


@pytest.mark.parametrize("feed", ["pandas", "numpy"])
def test_use_model_with_the_data_makes_the_training_record_train_would(feed):
    """The feed and the categories (order included) equal `train`'s."""
    data = TEXT_DATA if feed == "pandas" else MODEL_DATA
    a = _text_pipe(feed).train(data, target="y")
    b = _text_pipe(feed)
    assert b.use_model(a.model_, data=data, target="y") is b
    assert b._feed == a._feed
    assert b._categories == a._categories
    if feed == "pandas":
        assert set(b._categories) == {"city", "kind"}
    assert b.predict(data, out="numpy")["prediction"].tolist() == (
        a.predict(data, out="numpy")["prediction"].tolist()
    )


def test_use_model_with_data_already_learned_learns_nothing_again():
    """The steps were learned by `train`: the store finds them."""
    a = _model_pipe().train(MODEL_DATA, target="y")
    STORE.learns.clear()
    _model_pipe().use_model(a.model_, data=MODEL_DATA, target="y")
    assert not STORE.learns


def test_use_model_with_data_learns_the_steps_again_from_the_data():
    """No store entry for these steps: they are learned, the model is not."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit([[1.0, 2.0], [2.0, 1.0]], [0, 1])
    data = MODEL_DATA.assign(x=MODEL_DATA.x + 100.0)
    pipe = _model_pipe().use_model(model, data=data, target="y")
    assert pipe["scale"].center_ == {"x": 103.5, "z": 3.5}
    assert pipe.model_ is model


def test_use_model_with_data_does_not_fit_the_model():
    """A model whose `fit` raises, trained before, is taken as it is."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit([[1.0, 2.0], [2.0, 1.0]], [0, 1])

    def refuse(*args, **kwargs):
        raise AssertionError("fit was called")

    model.fit = refuse
    pipe = _model_pipe().use_model(model, data=MODEL_DATA, target="y")
    assert pipe.model_ is model
    assert pipe.predict(MODEL_DATA, out="numpy")["prediction"].shape == (6,)


def test_use_model_refuses_target_or_feed_without_data():
    """`target` or `feed` alone is a refusal, as is a missing training record."""
    pipe = _model_pipe().train(MODEL_DATA, target="y")
    for given in ({"target": "y"}, {"feed": "numpy"}):
        with pytest.raises(sq.errors.SqlearnError, match=r"data.*Fix:"):
            pipe.use_model(pipe.model_, **given)


def test_use_model_refuses_data_without_target():
    """The data needs its target, as `train` does."""
    pipe = _model_pipe().train(MODEL_DATA, target="y")
    with pytest.raises(sq.errors.SqlearnError, match=r"target.*Fix:"):
        pipe.use_model(pipe.model_, data=MODEL_DATA)


def test_use_model_refuses_what_train_refuses():
    """A target that is not a column of the data."""
    pipe = _model_pipe().train(MODEL_DATA, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="nope"):
        pipe.use_model(pipe.model_, data=MODEL_DATA, target="nope")


def test_a_model_trained_on_other_columns_fails_in_predict_with_its_own_error():
    """`use_model` takes it; `predict` raises scikit-learn's own ValueError."""
    from sklearn.linear_model import LogisticRegression

    pipe = _model_pipe().train(MODEL_DATA, target="y")
    wide = LogisticRegression().fit(
        np.arange(30.0).reshape(6, 5) ** 2, [0, 0, 0, 1, 1, 1]
    )
    pipe.use_model(wide)
    with pytest.raises(ValueError, match="features"):
        pipe.predict(MODEL_DATA, out="numpy")


def test_a_fit_that_fails_leaves_the_model_untrained():
    """After a failed fit, `model_` and `predict` both refuse."""
    frame = pd.DataFrame({"x": [3.0, 1.0, 2.0], "y": [1, 0, 1]})
    pipe = sq.Pipeline([("scale", sq.scale.standard()), ("model", Failing())])
    pipe.train(frame, target="y")
    with pytest.raises(ValueError, match="cannot fit"):
        pipe.train(pd.DataFrame({"x": [100.0, 300.0], "y": [0, 1]}), target="y")
    with pytest.raises(sq.errors.SqlearnError, match="train"):
        pipe.model_  # noqa: B018
    with pytest.raises(sq.errors.SqlearnError, match="not been trained"):
        pipe.predict(frame)
