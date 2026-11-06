"""Tests of OneHot against scikit-learn's OneHotEncoder."""

import time

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import VARCHAR
from sklearn.preprocessing import OneHotEncoder

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import Learned, classify


def towns(seed=3, rows=40):
    """Return seeded data: two text columns and a number."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "city": rng.choice(["paris", "rome", "oslo", "kyiv"], rows),
            "kind": rng.choice(["a", "b", "c"], rows),
            "n": rng.normal(size=rows),
        },
    )


def test_onehot_matches_sklearn():
    """Values and column names match OneHotEncoder(handle_unknown="ignore")."""
    frame = towns()
    cols = ["city", "kind"]
    sk = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(frame[cols])
    pipe = sq.Pipeline([("hot", sq.OneHot(cols=cols))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == [*sk.get_feature_names_out(), "n"]
    np.testing.assert_array_equal(
        got[list(sk.get_feature_names_out())].to_numpy(),
        sk.transform(frame[cols]).astype(int),
    )


def test_output_is_integer():
    """The new columns are INTEGER."""
    frame = towns()
    rel = sq.Pipeline([("hot", sq.OneHot(cols="kind"))]).learn(frame).apply(frame)
    assert [str(t) for t in rel.types] == [
        "VARCHAR",
        "INTEGER",
        "INTEGER",
        "INTEGER",
        "DOUBLE",
    ]


def test_unseen_value_is_all_zeros():
    """A value not seen at learn gives zeros in every column."""
    pipe = sq.Pipeline([("hot", sq.OneHot(cols="c"))]).learn(
        pd.DataFrame({"c": ["a", "b"]}),
    )
    rel = pipe.apply(pd.DataFrame({"c": ["a", "z", "b"]}))
    assert rel.columns == ["c_a", "c_b"]
    assert rel.fetchall() == [(1, 0), (0, 0), (0, 1)]


def test_null_is_a_category_only_if_seen():
    """NULL gets its own ``_NULL`` column when learned, else is all zeros."""
    seen = connection().sql("SELECT * FROM (VALUES ('b'), (NULL), ('a')) t(c)")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(seen)
    rel = pipe.apply(seen)
    assert rel.columns == ["c_a", "c_b", "c_NULL"]
    assert rel.fetchall() == [(0, 1, 0), (0, 0, 1), (1, 0, 0)]
    unseen = connection().sql("SELECT * FROM (VALUES ('b'), ('a')) t(c)")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(unseen)
    more = connection().sql("SELECT * FROM (VALUES ('b'), (NULL)) t(c)")
    rel = pipe.apply(more)
    assert rel.columns == ["c_a", "c_b"]
    assert rel.fetchall() == [(0, 1), (0, 0)]


def test_null_matches_sklearn_apart_from_its_name():
    """scikit-learn also adds a column for missing; it names it ``c_nan``."""
    frame = pd.DataFrame({"c": ["b", None, "a", "b"]})
    sk = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(frame)
    got = sq.Pipeline([("hot", sq.OneHot())]).learn(frame).apply(frame, out="pandas")
    assert list(sk.get_feature_names_out()) == ["c_a", "c_b", "c_nan"]
    assert list(got.columns) == ["c_a", "c_b", "c_NULL"]
    np.testing.assert_array_equal(got.to_numpy(), sk.transform(frame).astype(int))


def test_integer_categories_are_named_by_their_string_form():
    """An integer column gives ``x_1``, ``x_2``, as scikit-learn does."""
    frame = pd.DataFrame({"x": [2, 1, 2, 3]})
    sk = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(frame)
    got = sq.Pipeline([("hot", sq.OneHot(cols="x"))]).learn(frame)
    got = got.apply(frame, out="pandas")
    assert list(got.columns) == list(sk.get_feature_names_out())
    np.testing.assert_array_equal(got.to_numpy(), sk.transform(frame).astype(int))


def test_keep_and_categories_learned():
    """With keep the input stays; the categories are learned per column."""
    frame = towns()
    pipe = sq.Pipeline([("hot", sq.OneHot(cols="kind", keep=True))]).learn(frame)
    assert pipe["hot"].categories_ == {"kind": ["a", "b", "c"]}
    assert pipe.apply(frame).columns == [
        "city",
        "kind",
        "kind_a",
        "kind_b",
        "kind_c",
        "n",
    ]


def test_text_null_beside_a_real_null():
    """The text 'NULL' and a real NULL share a label and are numbered.

    Equal labels keep output order: learned categories first, the missing
    category last.
    """
    data = connection().sql("SELECT * FROM (VALUES ('NULL'), (NULL)) t(city)")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(data)
    assert pipe.columns_out_ == ["city_NULL", "city_NULL_2"]
    assert pipe.apply(data).fetchall() == [(1, 0), (0, 1)]


def test_onehot_of_case_only_categories():
    """Categories differing only in case are numbered, not refused (ADR 0035)."""
    data = connection().sql("SELECT * FROM (VALUES ('Oslo'), ('oslo'), (NULL)) t(city)")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(data)
    assert pipe.columns_out_ == ["city_Oslo", "city_oslo_2", "city_NULL"]
    assert pipe.apply(data).fetchall() == [(1, 0, 0), (0, 1, 0), (0, 0, 1)]


def test_a_later_step_sees_the_numbered_names():
    """A selector after OneHot matches the final, numbered names."""
    data = connection().sql("SELECT * FROM (VALUES ('Oslo'), ('oslo')) t(city)")
    pipe = sq.Pipeline(
        [("hot", sq.OneHot()), ("scale", sq.Scale(cols=["city_oslo_2"]))]
    ).learn(data)
    assert pipe.columns_out_ == ["city_Oslo", "city_oslo_2"]
    assert pipe.apply(data).fetchall() == [(1, -1.0), (0, 1.0)]


def test_onehot_and_ordinal_learn_in_one_run():
    """Two dynamic steps on different columns learn in one statement."""
    frame = towns()
    pipe = sq.Pipeline(
        [("hot", sq.OneHot(cols="city")), ("ord", sq.Ordinal(cols="kind"))],
    ).learn(frame)
    assert len(pipe.runs_) == 1
    assert len(pipe.runs_[0].statements) == 1


def test_settings_and_declaration():
    """Defaults are as documented and the step declares dynamic."""
    assert sq.OneHot(keep=True).settings() == {
        "cols": sq.cols.string(),
        "keep": True,
        "suffix": None,
    }
    undeclared = type("Undeclared", (sq.OneHot,), {"dynamic": None})()
    assert classify(undeclared, [("a", VARCHAR)]) == "dynamic"
    assert sq.OneHot.dynamic is True
    assert str(sq.OneHot.creates) == "INTEGER"


def test_awkward_names_survive_the_slice_steps():
    """Spaces, quotes and reserved words in names and categories come out right."""
    frame = pd.DataFrame(
        {
            "order": ["New York", "O'Brien", 'say "hi"', "New York"],
            "my col": [1.0, None, 3.0, 4.0],
            'a"b': ["x", "y", "x", "y"],
        },
    )
    pipe = sq.Pipeline(
        [
            ("fill", sq.Impute()),
            ("scale", sq.Scale()),
            ("hot", sq.OneHot(cols=["order", 'a"b'])),
        ],
    ).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == [
        "order_New York",
        "order_O'Brien",
        'order_say "hi"',
        "my col",
        'a"b_x',
        'a"b_y',
    ]
    assert got["order_O'Brien"].tolist() == [0, 1, 0, 0]
    assert got['order_say "hi"'].tolist() == [0, 0, 1, 0]
    assert got["order_New York"].tolist() == [1, 0, 0, 1]
    ordinal = sq.Pipeline([("o", sq.Ordinal(cols=["order"]))]).learn(frame)
    assert ordinal.apply(frame, out="pandas")["order"].tolist() == [0, 1, 2, 0]


def test_onehot_handles_two_thousand_categories():
    """A column with 2,000 distinct values builds and runs."""
    rows = 4000
    frame = pd.DataFrame({"c": [f"v{i % 2000}" for i in range(rows)]})
    start = time.perf_counter()
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(frame)
    rel = pipe.apply(frame)
    result = rel.fetchall()
    elapsed = time.perf_counter() - start
    assert elapsed < 30
    assert len(rel.columns) == 2000
    assert len(result) == rows
    assert all(sum(row) == 1 for row in result)


def test_an_all_null_column_gives_one_null_column_as_in_sklearn():
    """Only NULL seen: one column, ``c_NULL``, all ones (scikit-learn: one too)."""
    frame = pd.DataFrame({"c": [None, None, None]}, dtype=object)
    sk = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(frame)
    pipe = sq.Pipeline([("hot", sq.OneHot(cols="c"))]).learn(frame)
    assert pipe["hot"].categories_ == {"c": []}
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == ["c_NULL"]
    np.testing.assert_array_equal(got.to_numpy(), sk.transform(frame).astype(int))


def test_a_new_column_never_renames_an_input_column():
    """A created name taken by a column passing through is numbered instead."""
    data = connection().sql("SELECT 'a' AS city, 1 AS city_a")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(data)
    assert pipe.columns_out_ == ["city_a_2", "city_a"]


def test_names_are_fixed_at_learn():
    """Applying to data with an extra column keeps the names columns_out_ shows."""
    learn = connection().sql(
        "SELECT * FROM (VALUES ('Oslo', 1.0), ('Rome', 2.0)) t(city, n)"
    )
    pipe = sq.Pipeline(
        [("hot", sq.OneHot()), ("scale", sq.Scale(cols=["city_Oslo"]))]
    ).learn(learn)
    assert pipe.columns_out_ == ["city_Oslo", "city_Rome", "n"]
    more = connection().sql("SELECT 'Oslo' AS city, 1.0 AS n, 5 AS extra")
    assert pipe.apply(more).columns == ["city_Oslo", "city_Rome", "n", "extra"]


def test_an_extra_column_taking_a_learned_name_is_refused():
    """A column at apply clashing with a created name is refused, not renamed."""
    learn = connection().sql("SELECT * FROM (VALUES ('Oslo'), ('Rome')) t(city)")
    pipe = sq.Pipeline([("hot", sq.OneHot())]).learn(learn)
    more = connection().sql("SELECT 'Oslo' AS city, 1 AS city_oslo")
    with pytest.raises(
        sq.errors.StepError,
        match=r"hot \(step 1\).*'city_Oslo'.*'city_oslo'.*rename or drop 'city_oslo'",
    ):
        pipe.apply(more)


def test_zero_categories_give_no_column():
    """With no category and no NULL learned, the column becomes nothing."""
    learned = Learned.values({"categories": [], "has_null": False})
    assert sq.OneHot().apply(duckdb.ColumnExpression("c"), learned) == []


def test_nan_in_a_float_column_is_its_own_category_as_in_sklearn():
    """NaN is a category named ``c_nan``, sorted last, as scikit-learn has it."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (2.0::DOUBLE), ('nan'), (1.0), (2.0)) t(c)"
    )
    values = np.array([[2.0], [np.nan], [1.0], [2.0]])
    sk = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(values)
    got = sq.Pipeline([("hot", sq.OneHot(cols="c"))]).learn(rel).apply(rel)
    assert got.columns == ["c_1.0", "c_2.0", "c_nan"]
    assert list(sk.get_feature_names_out(["c"])) == got.columns
    np.testing.assert_array_equal(np.array(got.fetchall()), sk.transform(values))
