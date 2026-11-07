"""Tests of the feed: handing data to a model and its predictions back."""

import builtins
import gc
import sys

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn import _feed
from sqlearn._config import connection
from sqlearn._feed import hand_over, predict_streamed, received
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
    Tens.calls = 0
    fetched = predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()
    assert Tens.calls == 1
    assert fetched == streamed


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


def test_feed_other_than_numpy_points_to_issue_21():
    """Any other feed is not built yet, and the message says where it is planned."""
    rel = connection().sql("SELECT 1.0 AS a")
    url = "https://github.com/glaucis/sqlearn/issues/21"
    with pytest.raises(sq.errors.SqlearnError, match=url):
        hand_over(rel, "arrow")
    with pytest.raises(sq.errors.SqlearnError, match=url):
        sq.Model(LogisticRegression(), feed="arrow")


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
