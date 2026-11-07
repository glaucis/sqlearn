"""Tests of the feed: handing data to a model and its predictions back."""

import builtins
import gc
import sys

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn import _feed
from sqlearn._config import connection
from sqlearn._feed import fetch, hand_over, predict_streamed, received
from sqlearn._model import Model


@pytest.fixture
def con():
    """Return sqlearn's connection."""
    return connection()


def without_pyarrow(monkeypatch):
    """Make sqlearn's feed find no pyarrow; other libraries still find it."""
    real = builtins.__import__

    def refuse(name, globals=None, *args, **kwargs):
        if name == "pyarrow" and (globals or {}).get("__name__") == _feed.__name__:
            raise ImportError(name)
        return real(name, globals, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


def test_predictions_come_in_batches_in_row_order(con, monkeypatch):
    """Each batch goes to the model apart; the result is sorted by row."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 3)
    seen = []

    class Echo:
        def fit(self, x, y):
            return self

        def predict(self, x):
            seen.append(len(x))
            return x[:, 0] * 10

    rel = con.sql(
        "SELECT i::DOUBLE AS a, i + 1 AS r FROM range(8) t(i) ORDER BY hash(i)"
    )
    out = predict_streamed(con, rel, ["a"], "r", Model(Echo()))
    assert seen == [3, 3, 2]
    assert [v for (v,) in out.fetchall()] == [i * 10.0 for i in range(8)]


def test_text_predictions_keep_order_across_batches(con, monkeypatch):
    """Text predictions land as VARCHAR, in row order, across batches."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)

    class Words:
        def fit(self, x, y):
            return self

        def predict(self, x):
            return np.where(x[:, 0] > 2, "yes", "no")

    rel = con.sql("SELECT i::DOUBLE AS a, i + 1 AS r FROM range(6) t(i)")
    out = predict_streamed(con, rel, ["a"], "r", Model(Words()))
    assert str(out.types[0]) == "VARCHAR"
    assert [v for (v,) in out.fetchall()] == ["no", "no", "no", "yes", "yes", "yes"]


class Tens:
    """A model predicting ten times its first column, counting its calls."""

    calls = 0

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return ten times the first column."""
        type(self).calls += 1
        return x[:, 0] * 10


def test_without_pyarrow_one_fetch_gives_the_same_predictions(con, monkeypatch):
    """pyarrow is optional: without it the rows go over in one batch."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 3)
    rel = con.sql(
        "SELECT i::DOUBLE AS a, i + 1 AS r FROM range(8) t(i) ORDER BY hash(i)"
    )
    Tens.calls = 0
    streamed = predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()
    assert Tens.calls == 3
    without_pyarrow(monkeypatch)
    monkeypatch.setattr(_feed, "_WARNED", set())
    Tens.calls = 0
    with pytest.warns(sq.errors.SqlearnWarning, match=r"not streamed.*uv add pyarrow"):
        fetched = predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()
    assert Tens.calls == 1
    assert fetched == streamed
    # Once per process: the second fallback is silent (warnings are errors).
    predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()


def test_a_search_without_pyarrow_scores_the_same(monkeypatch):
    """The search's results do not depend on pyarrow being installed."""
    data = pd.DataFrame({"x": np.arange(40.0), "y": [0, 1, 1, 0] * 10})
    pipe = sq.Pipeline([("scale", sq.scale.standard()), LogisticRegression()])

    def run():
        search = sq.search(pipe, params={"model__C": [0.1, 1.0]})
        search.train(data, target="y")
        return search.results_.fetchall(), search.predict(data, out="numpy")

    monkeypatch.setattr(_feed, "BATCH_ROWS", 3)
    streamed, streamed_predicted = run()
    without_pyarrow(monkeypatch)
    monkeypatch.setattr(_feed, "_WARNED", set())
    with pytest.warns(sq.errors.SqlearnWarning, match="uv add pyarrow"):
        fetched, fetched_predicted = run()
    assert fetched == streamed
    np.testing.assert_array_equal(
        fetched_predicted["prediction"], streamed_predicted["prediction"]
    )


def test_no_rows_are_handed_over_once(con):
    """With no rows, the model still sees one (empty) hand-over, as before."""
    rel = con.sql("SELECT 1.0::DOUBLE AS a, 1 AS r WHERE false")
    Tens.calls = 0
    out = predict_streamed(con, rel, ["a"], "r", Model(Tens()))
    assert Tens.calls == 1
    assert out.fetchall() == []
    assert out.columns == ["prediction"]


def test_probabilities_come_back_one_column_per_class(con, monkeypatch):
    """predict_proba gives one column per class, in row order."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    model = Model(LogisticRegression().fit(x, [0, 0, 1, 1]))
    rel = con.sql("SELECT i::DOUBLE AS a, 4 - i AS r FROM range(4) t(i)")
    out = predict_streamed(con, rel, ["a"], "r", model, method="predict_proba")
    assert out.columns == ["__sqlearn_proba_0", "__sqlearn_proba_1"]
    expected = model.estimator.predict_proba(x[::-1])
    np.testing.assert_allclose(np.array(out.fetchall()), expected)


def test_a_prediction_per_row_is_required_in_every_batch(con, monkeypatch):
    """A model returning two values per row is refused, naming the shape."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)

    class Wide:
        def fit(self, x, y):
            return self

        def predict(self, x):
            return np.zeros((len(x), 2))

    rel = con.sql("SELECT i::DOUBLE AS a, i AS r FROM range(4) t(i)")
    with pytest.raises(sq.errors.SqlearnError, match=r"shape \(2, 2\).*one value"):
        predict_streamed(con, rel, ["a"], "r", Model(Wide()))


def test_the_predictions_table_is_dropped_with_the_relation(con):
    """Once the relation is gone, the next call drops its predictions table."""

    def tables():
        query = (
            "SELECT count(*) FROM duckdb_tables() "
            f"WHERE database_name = '{_feed._DATABASE}'"
        )
        return con.sql(query).fetchall()[0][0]

    before = tables()
    rel = con.sql("SELECT i::DOUBLE AS a, i AS r FROM range(4) t(i)")
    out = predict_streamed(con, rel, ["a"], "r", Model(Tens()))
    assert tables() == before + 1
    del out
    gc.collect()
    sq.Pipeline([sq.scale.standard()]).learn(pd.DataFrame({"x": [1.0, 2.0]}))
    assert tables() == before


def test_pipeline_predict_streams_in_batches(monkeypatch):
    """Pipeline.predict hands the model one batch at a time, rows in order."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 4)
    frame = pd.DataFrame({"x": np.arange(10.0), "y": [0, 1] * 5})
    pipe = sq.Pipeline([("model", Tens())]).train(frame, target="y")
    Tens.calls = 0
    predicted = pipe.predict(frame, out="numpy")["prediction"]
    assert Tens.calls == 3
    np.testing.assert_array_equal(predicted, np.arange(10.0) * 10)


def test_received_sorts_predictions_by_row(con):
    """received registers the arrays and sorts them by row number."""
    rel = received(con, np.array([2, 1]), np.array(["b", "a"]))
    assert rel.fetchall() == [("a",), ("b",)]


def test_hand_over_gives_a_float_matrix_in_column_order():
    """numpy: a 2-D float64 array, columns in order, NULL as NaN."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1, 2.5, true), (NULL, 4.0, false)) t(a, b, c)"
    )
    x = hand_over(rel, "numpy")
    assert isinstance(x, np.ndarray)
    assert x.dtype == np.float64
    assert x.shape == (2, 3)
    np.testing.assert_array_equal(x, [[1.0, 2.5, 1.0], [np.nan, 4.0, 0.0]])


def test_hand_over_refuses_a_column_that_is_not_a_number():
    """Text left in the data is named, with the steps that encode it."""
    rel = connection().sql("SELECT 1.0 AS a, 'x' AS city")
    with pytest.raises(sq.errors.SqlearnError, match=r"'city'.*onehot"):
        hand_over(rel, "numpy")


def test_an_unknown_feed_is_refused_naming_the_forms():
    """A feed that is not a form is refused by the hand-over and by Model."""
    rel = connection().sql("SELECT 1.0 AS a")
    with pytest.raises(sq.errors.SqlearnError, match=r"'parquet'.*arrow, stream"):
        hand_over(rel, "parquet")
    with pytest.raises(sq.errors.SqlearnError, match=r"'parquet'.*arrow, stream"):
        sq.Model(LogisticRegression(), feed="parquet")


def test_null_text_arrives_missing_in_every_form(con):
    """Text arrives as categories, and a NULL stays missing, never a category."""
    rel = con.sql("SELECT * FROM (VALUES ('Oslo'), (NULL)) t(city)")
    assert fetch(rel, "pandas", ["city"], None)[0]["city"].isna().tolist() == [
        False,
        True,
    ]
    assert fetch(rel, "polars", ["city"], None)[0]["city"].is_null().to_list() == [
        False,
        True,
    ]
    assert fetch(rel, "arrow", ["city"], None)[0]["city"].null_count == 1
    assert str(fetch(rel, "pandas", ["city"], None)[0]["city"].dtype) == "category"


def test_text_arrives_as_each_form_s_categories(con):
    """pandas category, Polars Categorical, Arrow dictionary-encoded."""
    rel = con.sql("SELECT * FROM (VALUES ('Oslo', 1.5), ('Rome', NULL)) t(city, a)")
    x, y = fetch(rel, "polars", ["city", "a"], None)
    assert y is None
    assert x.schema["city"] == pl.Categorical
    assert x["a"].to_list() == [1.5, None]
    table, _ = fetch(rel, "arrow", ["city", "a"], None)
    assert pa.types.is_dictionary(table.schema.field("city").type)
    assert table.column("city").to_pylist() == ["Oslo", "Rome"]
    frame, _ = fetch(rel, "pandas", ["a", "city"], None)
    assert list(frame.columns) == ["a", "city"]
    assert frame["city"].cat.categories.tolist() == ["Oslo", "Rome"]


def test_numpy_still_refuses_text_and_a_missing_target_is_named(con):
    """numpy keeps today's refusal; every form refuses a missing target."""
    rel = con.sql("SELECT * FROM (VALUES ('Oslo', 1), ('Rome', NULL)) t(city, y)")
    with pytest.raises(sq.errors.SqlearnError, match=r"'city'.*onehot"):
        fetch(rel, "numpy", ["city"], "y")
    for feed in ("numpy", "pandas", "polars", "arrow"):
        with pytest.raises(sq.errors.SqlearnError, match="'churned' is missing in 1"):
            fetch(rel, feed, ["city"] if feed != "numpy" else [], "y", named="churned")


def test_streamed_prediction_hands_each_batch_in_the_model_s_form(con, monkeypatch):
    """Each batch reaches predict as the feed's form, text as categories."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)
    seen = []

    class Look:
        def fit(self, x, y):
            return self

        def predict(self, x):
            seen.append(x)
            return np.arange(len(x))

    rel = con.sql("SELECT ['a', 'b', NULL][i + 1] AS city, i AS r FROM range(3) t(i)")
    kinds = {"pandas": pd.DataFrame, "polars": pl.DataFrame, "arrow": pa.Table}
    for feed, kind in kinds.items():
        seen.clear()
        out = predict_streamed(con, rel, ["city"], "r", Model(Look(), feed=feed))
        assert out.fetchall() == [(0,), (1,), (0,)]
        assert [len(x) for x in seen] == [2, 1]
        assert all(isinstance(x, kind) for x in seen)
    assert pa.types.is_dictionary(seen[0].schema.field("city").type)
    assert seen[1].column("city").null_count == 1


def test_missing_numpy_says_to_install_it(monkeypatch):
    """Without numpy, the numpy hand-over says to install it."""
    monkeypatch.setitem(sys.modules, "numpy", None)
    rel = connection().sql("SELECT 1.0 AS a")
    with pytest.raises(sq.errors.SqlearnError, match="install numpy"):
        hand_over(rel, "numpy")


class Settings:
    """A model whose predict returns the features themselves: two per row."""

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return the features themselves."""
        return x


def test_predictions_must_be_one_value_per_row():
    """A model returning a table instead of one value per row is refused."""
    frame = connection().sql("SELECT * FROM (VALUES (1.0, 2.0, 0)) t(a, b, y)")
    pipe = sq.Pipeline([("model", Settings())]).train(frame, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="one value per row"):
        pipe.predict(frame)


def test_a_model_failing_mid_stream_leaves_the_connection_usable(con, monkeypatch):
    """A failure in a later batch ends the read and drops the table."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)

    class Second:
        calls = 0

        def fit(self, x, y):
            return self

        def predict(self, x):
            type(self).calls += 1
            if type(self).calls == 2:
                msg = "second batch"
                raise ValueError(msg)
            return x[:, 0]

    query = (
        "SELECT count(*) FROM duckdb_tables() "
        f"WHERE database_name = '{_feed._DATABASE}'"
    )
    before = con.sql(query).fetchall()[0][0]
    rel = con.sql("SELECT i::DOUBLE AS a, i AS r FROM range(6) t(i)")
    with pytest.raises(ValueError, match="second batch"):
        predict_streamed(con, rel, ["a"], "r", Model(Second()))
    assert Second.calls == 2
    assert con.sql("SELECT 1").fetchall() == [(1,)]
    assert con.sql(query).fetchall()[0][0] == before


@pytest.mark.parametrize(
    ("feed", "module"), [("polars", "polars"), ("arrow", "pyarrow")]
)
def test_a_missing_library_says_to_install_it(con, monkeypatch, feed, module):
    """Each form's library is imported only when used, and named when missing."""
    monkeypatch.setitem(sys.modules, module, None)
    rel = con.sql("SELECT 1.0 AS a")
    with pytest.raises(sq.errors.SqlearnError, match=f"uv add {module}"):
        fetch(rel, feed, ["a"], None)


def test_take_hands_over_numpy_only(con):
    """The other forms are fetch's: take refuses them."""
    with pytest.raises(sq.errors.SqlearnError, match="fetch"):
        _feed.take(con.sql("SELECT 1.0 AS a"), "pandas", ["a"])
