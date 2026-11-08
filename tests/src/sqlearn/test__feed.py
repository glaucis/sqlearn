"""Tests of the feed: handing data to a model and its predictions back."""

import builtins
import gc
import sys

import duckdb
import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest
from sklearn.linear_model import LogisticRegression, SGDClassifier

import sqlearn as sq
from sqlearn import _feed, _memory
from sqlearn._config import connection
from sqlearn._feed import fetch, hand_over, predict_streamed
from sqlearn._model import Model
from sqlearn.errors import SqlearnWarning


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
    assert x.schema["city"] == pl.Enum(["Oslo", "Rome"])
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


def codes(x, feed, column):
    """Return the category codes of a column as the model would read them."""
    if feed == "pandas":
        return [None if c < 0 else int(c) for c in x[column].cat.codes]
    if feed == "polars":
        # As the model would take the frame: each way must keep the codes.
        physical = x[column].to_physical().to_list()
        arrow = x.to_arrow().column(column).combine_chunks().indices.to_pylist()
        pandas = [None if c < 0 else int(c) for c in x.to_pandas()[column].cat.codes]
        assert physical == arrow == pandas
        return physical
    return x.column(column).combine_chunks().indices.to_pylist()


@pytest.mark.parametrize("feed", ["pandas", "polars", "arrow"])
def test_known_categories_keep_their_codes_and_new_ones_follow(con, feed):
    """Training's sorted list is the prefix; a new value is appended, not lost."""
    train = con.sql("SELECT * FROM (VALUES ('rome'), ('oslo'), ('kyiv')) t(city)")
    known = {}
    x, _ = fetch(train, feed, ["city"], None, categories=known)
    assert known == {"city": ["kyiv", "oslo", "rome"]}
    assert codes(x, feed, "city") == [2, 1, 0]
    later = con.sql("SELECT * FROM (VALUES ('rome'), ('paris'), (NULL)) t(city)")
    x, _ = fetch(later, feed, ["city"], None, categories=known)
    assert codes(x, feed, "city") == [2, 3, None]
    assert known == {"city": ["kyiv", "oslo", "rome"]}


def test_a_nan_target_is_not_missing_in_any_form(con):
    """Only NULL is a missing target: NaN is a value, the same in every form."""
    rel = con.sql("SELECT * FROM (VALUES (1.0, 'NaN'::DOUBLE), (2.0, 1.0)) t(a, y)")
    for feed in ("numpy", "pandas", "polars", "arrow"):
        _, y = fetch(rel, feed, ["a"], "y")
        assert len(y) == 2


def test_a_feature_named_like_the_null_helper_is_handed_over(con):
    """The pandas target's NULL count never takes a feature's name."""
    rel = con.sql(
        "SELECT * FROM (VALUES (1.0, 0), (2.0, 1)) t(__sqlearn_target_null, y)"
    )
    x, y = fetch(rel, "pandas", ["__sqlearn_target_null"], "y")
    assert x["__sqlearn_target_null"].tolist() == [1.0, 2.0]
    assert y.tolist() == [0, 1]


DATA_100_ROWS = pd.DataFrame(
    {
        "a": np.arange(100.0),
        "b": np.cos(np.arange(100.0)),
        "y": [0, 1, 1, 0, 1] * 20,
    }
)
"""One hundred rows of two features and a target of two classes."""


def numpy_of(data):
    """Return the features and the target of `data` as numpy, in its order."""
    return data[["a", "b"]].to_numpy(dtype=np.float64), data["y"].to_numpy()


class Batches:
    """A model learning in pieces that records every batch it is handed."""

    def __init__(self):
        self.seen = []
        self.classes = []

    def partial_fit(self, x, y, classes=None):
        """Record the batch and the classes it was given."""
        self.seen.append((x.copy(), y.copy()))
        self.classes.append(classes)
        return self

    def fit(self, x, y):
        """Refuse: the stream calls partial_fit only."""
        raise AssertionError("fit called")

    def predict(self, x):
        """Predict nothing useful."""
        return np.zeros(len(x))


def record_first_rows(*, feed, rows, epochs, seed):
    """Return each epoch's order of the rows, by their feature ``a``."""
    model = Batches()
    sq.Pipeline(
        [sq.Model(model, feed=feed, rows=rows, epochs=epochs, seed=seed)]
    ).train(DATA_100_ROWS, target="y")
    order = [v for x, _ in model.seen for v in x[:, 0].tolist()]
    return [tuple(order[e * 100 : (e + 1) * 100]) for e in range(epochs)]


def test_stream_trains_in_batches_of_the_rows_given():
    """rows= is each batch's size; each epoch streams every row once."""
    sizes = []

    class Count:
        def partial_fit(self, x, y, classes=None):
            sizes.append(len(x))
            return self

        def fit(self, x, y):
            raise AssertionError("fit called")

        def predict(self, x):
            return np.zeros(len(x))

    pipe = sq.Pipeline([sq.Model(Count(), feed="stream", rows=40, epochs=2)])
    pipe.train(DATA_100_ROWS, target="y")
    assert sizes == [40, 40, 20] * 2


def test_stream_never_passes_an_empty_batch():
    """A batch larger than the data is one batch of every row."""
    sizes = []

    class Count:
        def partial_fit(self, x, y, classes=None):
            sizes.append(len(x))
            return self

        def fit(self, x, y):
            raise AssertionError

        def predict(self, x):
            return np.zeros(len(x))

    sq.Pipeline([sq.Model(Count(), feed="stream", rows=1000)]).train(
        DATA_100_ROWS, target="y"
    )
    assert sizes == [100] and 0 not in sizes


def test_stream_shuffles_by_seed_and_epoch():
    """The same seed gives the same orders; each epoch's order is new."""
    orders = record_first_rows(feed="stream", rows=10, epochs=2, seed=0)
    again = record_first_rows(feed="stream", rows=10, epochs=2, seed=0)
    assert orders == again and orders[0] != orders[1]
    other = record_first_rows(feed="stream", rows=10, epochs=2, seed=1)
    assert other != orders
    assert sorted(orders[0]) == sorted(orders[1]) == DATA_100_ROWS["a"].tolist()


def test_stream_without_shuffle_keeps_the_input_order():
    """shuffle=False streams the rows in the order they are read, every epoch."""
    model = Batches()
    sq.Pipeline(
        [sq.Model(model, feed="stream", rows=30, epochs=2, shuffle=False)]
    ).train(DATA_100_ROWS, target="y")
    order = [v for x, _ in model.seen for v in x[:, 0].tolist()]
    assert order == DATA_100_ROWS["a"].tolist() * 2


def test_stream_matches_sgd_on_the_same_order():
    """Streamed in order, the model learns as partial_fit on numpy slices."""
    sgd = SGDClassifier(random_state=0, shuffle=False)
    # The estimator's own shuffle= shuffles inside each batch: off in both.
    streamed = SGDClassifier(random_state=0, shuffle=False)
    pipe = sq.Pipeline([sq.Model(streamed, feed="stream", rows=25, shuffle=False)])
    pipe.train(DATA_100_ROWS, target="y")
    x, y = numpy_of(DATA_100_ROWS)
    for start in range(0, 100, 25):
        sgd.partial_fit(
            x[start : start + 25], y[start : start + 25], classes=np.unique(y)
        )
    np.testing.assert_allclose(np.asarray(streamed.coef_), np.asarray(sgd.coef_))


def test_stream_gives_the_classes_on_the_first_call_only():
    """classes= is the sorted distinct targets, computed in SQL, given once."""
    model = Batches()
    sq.Pipeline([sq.Model(model, feed="stream", rows=40)]).train(
        DATA_100_ROWS, target="y"
    )
    assert model.classes[0].tolist() == [0, 1]
    assert model.classes[1:] == [None, None]
    # Each row's target stays beside its features.
    for x, y in model.seen:
        assert y.tolist() == [[0, 1, 1, 0, 1][int(a) % 5] for a in x[:, 0]]


def test_stream_gives_no_classes_to_a_model_that_takes_none():
    """A partial_fit without a classes parameter is called with X and y only."""
    calls = []

    class Regressor:
        def partial_fit(self, x, y):
            calls.append(len(x))
            return self

        def fit(self, x, y):
            raise AssertionError

        def predict(self, x):
            return np.zeros(len(x))

    sq.Pipeline([sq.Model(Regressor(), feed="stream", rows=50)]).train(
        DATA_100_ROWS, target="y"
    )
    assert calls == [50, 50]


def test_megabytes_sets_the_batch_from_the_row_width(con):
    """megabytes= gives max(1, megabytes * 1e6 // (8 * features)) rows."""
    model = Batches()
    rel = con.sql("SELECT i::DOUBLE AS a, i % 2 AS y FROM range(300000) t(i)")
    _feed.train_streamed(con, rel, ["a"], "y", Model(model, feed="stream", megabytes=1))
    assert [len(x) for x, _ in model.seen] == [125_000, 125_000, 50_000]


def test_stream_defaults_to_batches_of_about_100_megabytes(con, monkeypatch):
    """With neither rows= nor megabytes=, a batch is about 100 MB."""
    seen = []
    duckdb_reader_sizes(monkeypatch, seen)
    rel = con.sql("SELECT i::DOUBLE AS a, i::DOUBLE AS b, 0 AS y FROM range(10) t(i)")
    _feed.train_streamed(con, rel, ["a", "b"], "y", Model(Batches(), feed="stream"))
    assert seen == [100 * 1_000_000 // 16]


def duckdb_reader_sizes(monkeypatch, seen):
    """Record the batch size of every Arrow reader the feed opens."""
    import duckdb

    real = duckdb.DuckDBPyRelation.to_arrow_reader

    def reader(self, batch_size=1_000_000):
        seen.append(batch_size)
        return real(self, batch_size=batch_size)

    monkeypatch.setattr(duckdb.DuckDBPyRelation, "to_arrow_reader", reader)
    return real


def test_a_model_without_partial_fit_is_refused_naming_other_forms():
    """The stream needs partial_fit; the message suggests a form that fits."""
    pipe = sq.Pipeline([sq.Model(LogisticRegression(), feed="stream")])
    with pytest.raises(sq.errors.SqlearnError, match=r"partial_fit.*feed='numpy'"):
        pipe.train(DATA_100_ROWS, target="y")


def test_rows_and_megabytes_together_are_refused():
    """A batch is sized by rows= or by megabytes=, not both."""
    with pytest.raises(sq.errors.SqlearnError, match=r"rows=.*megabytes="):
        sq.Model(SGDClassifier(), feed="stream", rows=10, megabytes=1)


def test_the_stream_without_pyarrow_is_refused(monkeypatch):
    """Training cannot stream without pyarrow: refused, never fetched whole."""
    without_pyarrow(monkeypatch)
    model = Batches()
    pipe = sq.Pipeline([sq.Model(model, feed="stream")])
    with pytest.raises(sq.errors.SqlearnError, match="uv add pyarrow"):
        pipe.train(DATA_100_ROWS, target="y")
    assert model.seen == []


def test_the_stream_refuses_text_before_any_batch():
    """Text reaches no model through the stream, as with numpy."""
    model = Batches()
    data = DATA_100_ROWS.assign(city="oslo")
    pipe = sq.Pipeline([sq.Model(model, feed="stream", rows=10)])
    with pytest.raises(sq.errors.SqlearnError, match=r"sq\.encode\.onehot"):
        pipe.train(data, target="y")
    assert model.seen == []


def test_the_stream_refuses_a_missing_target_counting_every_row():
    """A NULL target is refused before any batch, counted over all the rows."""
    model = Batches()
    data = DATA_100_ROWS.assign(y=DATA_100_ROWS["y"].astype("Int64"))
    data.loc[[3, 57, 98], "y"] = pd.NA
    pipe = sq.Pipeline([sq.Model(model, feed="stream", rows=10)])
    with pytest.raises(sq.errors.SqlearnError, match=r"'y' is missing in 3 row"):
        pipe.train(data, target="y")
    assert model.seen == []


def test_a_stream_model_predicts_in_numpy_batches(monkeypatch):
    """Trained through the stream, the model predicts numpy batches."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 30)
    seen = []

    class Mean(Batches):
        def predict(self, x):
            seen.append((type(x), len(x)))
            return x[:, 0]

    pipe = sq.Pipeline([sq.Model(Mean(), feed="stream", rows=40, epochs=3)])
    pipe.train(DATA_100_ROWS, target="y")
    out = pipe.predict(DATA_100_ROWS, out="numpy")["prediction"]
    assert seen == [(np.ndarray, 30)] * 3 + [(np.ndarray, 10)]
    assert out.tolist() == DATA_100_ROWS["a"].tolist()
    assert pipe["model"].rows == 40 and pipe["model"].epochs == 3


def test_a_search_trains_each_fold_through_the_stream():
    """A search fits a stream model with partial_fit on each fold's rows."""
    fitted = []

    class Folded(Batches):
        def partial_fit(self, x, y, classes=None):
            fitted.append(len(x))
            return super().partial_fit(x, y, classes)

        def get_params(self, deep=True):
            return {}

    pipe = sq.Pipeline(
        [
            ("scale", sq.scale.standard()),
            sq.Model(Folded(), feed="stream", rows=50),
        ]
    )
    search = sq.search(
        pipe,
        params={"scale__method": ["standard", "minmax"]},
        folds=sq.folds.kfold(4),
    )
    search.train(DATA_100_ROWS, target="y")
    # Each of two settings on four folds (every row trains on three of
    # them), in batches of at most 50 rows; then the best pipeline's 100.
    assert fitted[-2:] == [50, 50]
    assert sum(fitted[:-2]) == 2 * 3 * 100
    assert all(0 < n <= 50 for n in fitted)


def test_a_search_streams_folds_in_row_order_without_shuffle():
    """Each fold's training rows stream in the data's order with shuffle=False."""
    orders = []

    class Folded(Batches):
        def partial_fit(self, x, y, classes=None):
            orders.append(x[:, 0].tolist())
            return self

        def get_params(self, deep=True):
            return {}

    pipe = sq.Pipeline([sq.Model(Folded(), feed="stream", rows=1000, shuffle=False)])
    search = sq.search(pipe, params={}, folds=sq.folds.kfold(4))
    search.train(DATA_100_ROWS, target="y")
    for order in orders:
        assert order == sorted(order)


def test_a_search_refuses_a_stream_model_without_partial_fit_as_it_is():
    """The stream's refusal is not reported as a fold's failure."""
    pipe = sq.Pipeline([sq.Model(LogisticRegression(), feed="stream")])
    search = sq.search(pipe, params={"model__C": [0.1, 1.0]})
    with pytest.raises(sq.errors.SqlearnError, match="has no partial_fit") as caught:
        search.train(DATA_100_ROWS, target="y")
    assert "on fold" not in str(caught.value)


def test_batches_are_cut_to_the_size_asked_for():
    """DuckDB's short or empty Arrow batches are joined and cut exactly."""
    parts = [pa.record_batch({"a": list(range(n))}) for n in (3, 0, 4, 1, 5)]
    sizes = [t.num_rows for t in _feed._sized(iter(parts), 4)]
    assert sizes == [4, 4, 4, 1]


def test_the_stream_refuses_data_without_rows(con):
    """With no rows, partial_fit would never be called: refused."""
    model = Batches()
    rel = con.sql("SELECT 1.0 AS a, 0 AS y WHERE false")
    with pytest.raises(sq.errors.SqlearnError, match="no rows to train on"):
        _feed.train_streamed(con, rel, ["a"], "y", Model(model, feed="stream"))
    assert model.seen == []


@pytest.mark.parametrize("setting", [{"rows": 0}, {"megabytes": -1}, {"epochs": 1.5}])
def test_the_stream_s_counts_must_be_positive_ints(setting):
    """rows=, megabytes= and epochs= are counts of at least 1."""
    with pytest.raises(sq.errors.SqlearnError, match="not a count"):
        sq.Model(SGDClassifier(), feed="stream", **setting)


def big(con):
    """Return two number columns of five million rows, about 80 MB."""
    return con.sql("SELECT i::DOUBLE AS a, i::DOUBLE AS b FROM range(5000000) t(i)")


def test_a_fold_too_big_is_refused_before_fetching(con, monkeypatch):
    """Over the allowance, every form but the stream refuses, naming the sizes."""
    sq.set_config(memory="64MB")
    con.execute("SET memory_limit = '32MB'")
    sq.set_config(connection=con)
    fetched = []
    # Each form's fetch starts in one of these: neither may be reached.
    monkeypatch.setattr(_feed, "take", lambda *a: fetched.append(a))
    monkeypatch.setattr(_feed, "_library", lambda *a: fetched.append(a))
    for feed in ("numpy", "pandas", "polars", "arrow"):
        with pytest.raises(sq.errors.SqlearnError, match="stream") as err:
            fetch(big(con), feed, ["a", "b"], None)
        text = str(err.value)
        # Two 8-byte copies of two columns; numpy a mask byte a value more.
        assert ("170 MB" if feed == "numpy" else "160 MB") in text
        assert "32 MB" in text
        assert "swap" in text
        assert "sq.set_config(memory=" in text
        assert "memory_limit" in text  # a passed connection: lower its limit
    assert fetched == []


def test_the_shared_connections_refusal_does_not_suggest_its_limit(con):
    """On sqlearn's own connection the limit follows the budget: not a fix."""
    sq.set_config(memory="64MB")
    with pytest.raises(sq.errors.SqlearnError, match="stream") as err:
        fetch(big(con), "numpy", ["a", "b"], None)
    assert "memory_limit" not in str(err.value)


def test_a_small_fetch_on_a_default_passed_connection_is_not_refused():
    """DuckDB's default limit counts as half the budget, leaving the other half."""
    other = duckdb.connect()
    sq.set_config(connection=other)
    rel = other.sql("SELECT i::DOUBLE AS a, i::DOUBLE AS b FROM range(5000) t(i)")
    with pytest.warns(SqlearnWarning, match="memory_limit of about"):  # R22
        x, _ = fetch(rel, "numpy", ["a", "b"], None)
    assert x.shape == (5000, 2)


def test_a_small_fetch_on_an_unlimited_connection_is_not_refused():
    """An unlimited limit counts as half the budget too."""
    other = duckdb.connect()
    other.execute("SET memory_limit = '-1'")
    sq.set_config(connection=other)
    with pytest.warns(SqlearnWarning, match="no memory_limit"):  # R22
        x, _ = fetch(other.sql("SELECT 1.0 AS a"), "numpy", ["a"], None)
    assert x.tolist() == [[1.0]]


def test_a_too_big_training_is_refused_and_the_pipeline_untouched(con):
    """Pipeline.train stops before the fetch; the stream would still train."""
    sq.set_config(memory="64MB")
    pipe = sq.Pipeline([("model", LogisticRegression())])
    rel = con.sql("SELECT i::DOUBLE AS a, i % 2 AS y FROM range(5000000) t(i)")
    with pytest.raises(sq.errors.SqlearnError, match="partial_fit"):
        pipe.train(rel, target="y")
    with pytest.raises(sq.errors.SqlearnError, match="not been trained"):
        pipe.predict(rel)


def test_the_stream_is_not_checked(con, monkeypatch):
    """The stream holds one batch, never the fold: no estimate, no refusal."""
    sq.set_config(memory="64MB")
    monkeypatch.setattr(_memory, "estimate", lambda *a, **k: 10**15)
    x, _ = fetch(con.sql("SELECT 1.0 AS a, 0 AS y"), "stream", ["a"], "y")
    assert x.tolist() == [[1.0]]


def test_streamed_predictions_are_not_checked_batch_by_batch(con, monkeypatch):
    """Prediction batches are small by construction: never estimated."""
    monkeypatch.setattr(_feed, "BATCH_ROWS", 3)
    monkeypatch.setattr(_memory, "estimate", lambda *a, **k: 10**15)
    rel = con.sql("SELECT i::DOUBLE AS a, i + 1 AS r FROM range(8) t(i)")
    out = predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()
    assert len(out) == 8


def test_the_fallback_without_pyarrow_is_checked(con, monkeypatch):
    """Without pyarrow prediction is one whole fetch, so it is checked too."""
    monkeypatch.setattr(_memory, "estimate", lambda *a, **k: 10**15)
    without_pyarrow(monkeypatch)
    monkeypatch.setattr(_feed, "_WARNED", {"pyarrow"})
    rel = con.sql("SELECT i::DOUBLE AS a, i + 1 AS r FROM range(8) t(i)")
    with pytest.raises(sq.errors.SqlearnError, match="swap"):
        predict_streamed(con, rel, ["a"], "r", Model(Tens())).fetchall()


def test_a_search_is_refused_at_a_folds_training_fetch(tmp_path):
    """A fold's training rows that would not fit stop the search before fetching."""
    other = duckdb.connect()
    # DuckDB's share counts as at most half the budget (R11): 32 MB of its
    # 1 GB, so the fold tables are built in room and the hand-over gets 32 MB.
    other.execute("SET memory_limit = '1GB'")
    other.execute(f"SET temp_directory = '{tmp_path}'")
    sq.set_config(connection=other, memory="64MB")
    rel = other.sql("SELECT i::DOUBLE AS a, i % 2 AS y FROM range(2000000) t(i)")
    pipe = sq.Pipeline([("model", LogisticRegression())])
    search = sq.search(
        pipe, params={"model__C": [1.0]}, folds=sq.folds.holdout(test=0.2)
    )
    with (
        pytest.warns(SqlearnWarning, match="memory_limit of about 1,000 MB"),
        pytest.raises(sq.errors.SqlearnError, match="swap") as err,
    ):
        search.train(rel, target="y")
    # 1.6 million training rows of two numbers, two copies and a mask byte
    # each: about 54 MB, over 32 MB.
    assert "54 MB" in str(err.value)
    assert any(
        entry.name == "_fetch" and str(entry.path).endswith("search.py")
        for entry in err.traceback
    )
