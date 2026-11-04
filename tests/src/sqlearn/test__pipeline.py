"""Tests of the pipeline: learn, apply and the shape of what comes back."""

import gc
import math
from dataclasses import dataclass

import duckdb
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
    pipe.apply(people, out=sq.out_parquet(path))
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
    with pytest.raises(sq.StepError, match=r"scale \(step 1\).*no rows") as err:
        scale_pipe().learn(empty)
    assert err.value.step == "scale"
    assert err.value.position == 1
    assert len(STORE) == 0


def test_apply_names_a_missing_column(people):
    """Data at apply without a learned column, or with it as text, is named."""
    pipe = scale_pipe().learn(people)
    with pytest.raises(sq.StepError, match=r"scale \(step 1\).*'age'"):
        pipe.apply(connection().sql("SELECT 'b' AS city"))
    with pytest.raises(sq.StepError, match=r"scale \(step 1\).*'age'.*VARCHAR"):
        pipe.apply(connection().sql("SELECT '10' AS age, 'b' AS city"))


def test_a_selector_matching_nothing_names_the_step():
    """A selector choosing no column stops `learn`, naming the step."""
    text = connection().sql("SELECT 'b' AS city")
    with pytest.raises(sq.StepError, match=r"scale \(step 1\).*matches no column"):
        scale_pipe().learn(text)


def test_keep_adds_a_named_column(people):
    """With keep, the scaled column is added beside the original."""
    pipe = scale_pipe(keep=True).learn(people)
    rel = pipe.apply(people)
    assert rel.columns == ["age", "age_scale", "city"]
    assert [r[0] for r in rel.fetchall()] == list(AGES)


def test_a_name_collision_suggests_suffix():
    """An output taking a name in use is refused, suggesting suffix=."""
    data = connection().sql("SELECT 10.0 AS age, 1.0 AS age_scale")
    pipe = sq.Pipeline([("scale", MyScale(cols=["age"], keep=True))])
    with pytest.raises(sq.StepError, match=r"'age_scale'.*suffix="):
        pipe.learn(data)


def test_a_new_dynamic_column_may_not_take_a_name_in_use():
    """A dynamic step's new column colliding with a column is refused."""
    data = connection().sql("SELECT 'a' AS city, 1 AS city_a")
    pipe = sq.Pipeline([("onehot", MyEncoder())])
    with pytest.raises(sq.StepError, match=r"onehot \(step 1\).*'city_a'.*suffix="):
        pipe.learn(data)


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
        return {"n": sq.count(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def test_a_step_not_waiting_skips_a_pending_dynamic_step():
    """A text step after OneHot learns in the first run, not seeing ``city``."""
    data = connection().sql(
        "SELECT * FROM (VALUES ('x', 'b'), ('y', 'a')) t(name, city)",
    )
    pipe = sq.Pipeline([("onehot", IntEncoder()), ("text", CountText(sq.string()))])
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
        ("text", CountText(sq.string())),
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
    with pytest.raises(sq.StepError, match=r"bad \(step 2\).*DuckDB refuses"):
        pipe.learn(people)


def test_make_pipeline_names_steps():
    """Steps are named after their class, numbered when names clash."""
    pipe = sq.make_pipeline(MyScale(), MyEncoder(), MyScale())
    assert [name for name, _ in pipe.steps] == ["myscale-1", "myencoder", "myscale-2"]
    assert list(pipe.named_steps) == ["myscale-1", "myencoder", "myscale-2"]


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

    def counting(data):
        calls.append(data)
        return real(data)

    monkeypatch.setattr(_pipeline, "read", counting)
    pipe = sq.Pipeline([("onehot", MyEncoder()), ("scale", MyScale())])
    pipe.learn(people)
    pipe.apply(people)
    assert len(calls) == 2


def test_apply_before_learn_is_refused(people):
    """`apply` before `learn` says to learn first."""
    with pytest.raises(sq.SqlearnError, match="learn"):
        scale_pipe().apply(people)
    with pytest.raises(AttributeError, match="learn"):
        _ = scale_pipe().columns_out_


def test_steps_must_be_named_uniquely_and_be_steps(people):
    """Two steps sharing a name, or an object that is not a step, are refused."""
    with pytest.raises(sq.SqlearnError, match="'scale'"):
        sq.Pipeline([("scale", MyScale()), ("scale", MyScale())])
    with pytest.raises(sq.SqlearnError, match="not a step"):
        sq.Pipeline([("model", object())]).learn(people)
