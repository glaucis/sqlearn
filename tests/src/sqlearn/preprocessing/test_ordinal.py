"""Tests of Ordinal against scikit-learn's OrdinalEncoder."""

import numpy as np
import pandas as pd
from duckdb.sqltypes import VARCHAR
from sklearn.preprocessing import OrdinalEncoder

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify
from sqlearn.preprocessing.ordinal import Ordinal


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


def encoder():
    """Return the scikit-learn encoder matching Ordinal."""
    return OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)


def test_ordinal_matches_sklearn():
    """Codes match OrdinalEncoder, and the columns keep their names."""
    frame = towns()
    cols = ["city", "kind"]
    sk = encoder().fit(frame[cols])
    pipe = sq.Pipeline([("ord", sq.encode.ordinal(cols=cols))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == ["city", "kind", "n"]
    np.testing.assert_array_equal(got[cols].to_numpy(), sk.transform(frame[cols]))


def test_unseen_value_is_minus_one():
    """A value not seen at learn is -1."""
    pipe = sq.Pipeline([("ord", sq.encode.ordinal())]).learn(
        pd.DataFrame({"c": ["b", "a"]}),
    )
    rel = pipe.apply(pd.DataFrame({"c": ["a", "z", "b"]}))
    assert str(rel.types[0]) == "INTEGER"
    assert rel.fetchall() == [(0,), (-1,), (1,)]


def test_null_stays_null_as_in_sklearn():
    """Missing stays missing (scikit-learn gives NaN) and is not a category."""
    frame = pd.DataFrame({"c": ["b", None, "a", "b"]})
    expected = encoder().fit(frame).transform(frame)
    rel = sq.Pipeline([("ord", sq.encode.ordinal())]).learn(frame).apply(frame)
    got = [r[0] for r in rel.fetchall()]
    assert got == [None if np.isnan(v) else int(v) for v in expected[:, 0]]
    assert got == [1, None, 0, 1]


def test_integer_categories_sort_numerically():
    """Integer categories are ordered as numbers, as scikit-learn orders them."""
    frame = pd.DataFrame({"x": [10, 2, 33, 2]})
    sk = encoder().fit(frame)
    pipe = sq.Pipeline([("ord", sq.encode.ordinal(cols="x"))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    np.testing.assert_array_equal(got.to_numpy(), sk.transform(frame))


def test_keep_and_categories_learned():
    """With keep the code is added beside the input."""
    frame = towns()
    pipe = sq.Pipeline([("ord", sq.encode.ordinal(cols="kind", keep=True))]).learn(
        frame
    )
    assert pipe["ord"].categories_ == {"kind": ["a", "b", "c"]}
    assert pipe.apply(frame).columns == ["city", "kind", "kind_ord", "n"]


def test_settings_and_declaration():
    """Defaults are as documented and the step declares dynamic."""
    assert sq.encode.ordinal().settings() == {
        "cols": sq.cols.string(),
        "keep": False,
    }
    undeclared = type("Undeclared", (Ordinal,), {"dynamic": None})()
    assert classify(undeclared, [("a", VARCHAR)]) == "dynamic"
    assert Ordinal.dynamic is True
    assert str(Ordinal.creates) == "INTEGER"


def test_ordinal_runs_on_a_relation():
    """The step runs on a DuckDB relation, not only a DataFrame."""
    rel = connection().sql("SELECT * FROM (VALUES ('x'), ('y'), (NULL)) t(c)")
    out = sq.Pipeline([("ord", sq.encode.ordinal())]).learn(rel).apply(rel)
    assert out.fetchall() == [(0,), (1,), (None,)]


def test_a_column_of_only_nulls_has_no_categories():
    """With nothing to learn every value is NULL, and an unseen one is -1."""
    rel = connection().sql("SELECT NULL::VARCHAR AS c FROM range(2)")
    pipe = sq.Pipeline([("ord", sq.encode.ordinal())]).learn(rel)
    assert pipe.apply(rel).fetchall() == [(None,), (None,)]
    more = connection().sql("SELECT 'z' AS c")
    assert pipe.apply(more).fetchall() == [(-1,)]


def test_nan_in_a_float_column_is_missing_as_in_sklearn():
    """NaN is missing, as NULL is: not a category, and NaN stays missing."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (2.0::DOUBLE), ('nan'), (1.0), (NULL), (2.0)) t(c)"
    )
    values = np.array([[2.0], [np.nan], [1.0], [np.nan], [2.0]])
    expected = encoder().fit(values).transform(values)[:, 0]
    pipe = sq.Pipeline([("ord", sq.encode.ordinal(cols="c"))]).learn(rel)
    assert pipe["ord"].categories_ == {"c": [1.0, 2.0]}
    got = [r[0] for r in pipe.apply(rel).fetchall()]
    assert got == [None if np.isnan(v) else int(v) for v in expected]
    assert got == [1, None, 0, None, 1]


def test_the_text_nan_is_a_category():
    """In a text column 'nan' is a value like any other."""
    rel = connection().sql("SELECT * FROM (VALUES ('nan'), ('a')) t(c)")
    pipe = sq.Pipeline([("ord", sq.encode.ordinal())]).learn(rel)
    assert pipe.apply(rel).fetchall() == [(1,), (0,)]
