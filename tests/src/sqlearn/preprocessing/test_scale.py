"""Tests of Scale against scikit-learn's StandardScaler."""

import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_allclose
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline as SkPipeline
from sklearn.preprocessing import StandardScaler

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify


def data(seed=1, rows=50):
    """Return seeded data: two float columns, an int column, a text column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(5, 2, rows),
            "b": rng.uniform(-3, 40, rows),
            "n": rng.integers(0, 100, rows).astype("int64"),
            "city": rng.choice(["x", "y"], rows),
        },
    )


def test_scale_matches_standard_scaler():
    """Scaled columns and the learned mean and scale match scikit-learn."""
    frame = data()
    cols = ["a", "b", "n"]
    sk = StandardScaler().fit(frame[cols])
    pipe = sq.Pipeline([("scale", sq.Scale())]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), sk.transform(frame[cols]), rtol=1e-12)
    assert_allclose([pipe["scale"].mean_[c] for c in cols], sk.mean_, rtol=1e-12)
    assert_allclose([pipe["scale"].scale_[c] for c in cols], sk.scale_, rtol=1e-12)
    assert got["city"].tolist() == frame["city"].tolist()


def test_integer_columns_come_out_double():
    """Scaling an integer column gives DOUBLE."""
    frame = data()
    rel = sq.Pipeline([("scale", sq.Scale(cols="n"))]).learn(frame).apply(frame)
    assert str(rel.types[2]) == "DOUBLE"


def test_constant_column_scales_to_zero():
    """A zero standard deviation counts as 1, so a constant column becomes 0."""
    frame = pd.DataFrame({"k": [4.0, 4.0, 4.0], "v": [1.0, 2.0, 3.0]})
    sk = StandardScaler().fit(frame)
    pipe = sq.Pipeline([("scale", sq.Scale())]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert got["k"].tolist() == [0.0, 0.0, 0.0]
    assert pipe["scale"].scale_["k"] == 1.0
    assert_allclose(got.to_numpy(), sk.transform(frame), rtol=1e-12)


def test_keep_adds_a_column_beside_the_input():
    """With keep=True the input stays and ``a_scale`` is added."""
    frame = data()
    got = (
        sq.Pipeline([("scale", sq.Scale(cols="a", keep=True))])
        .learn(frame)
        .apply(frame, out="pandas")
    )
    assert "a_scale" in got.columns
    assert "a" in got.columns


def test_impute_then_scale_matches_sklearn_pipeline():
    """Impute then Scale equals scikit-learn's imputer then scaler."""
    frame = data(rows=60)
    rng = np.random.default_rng(7)
    frame.loc[rng.choice(60, 9, replace=False), "a"] = np.nan
    frame.loc[rng.choice(60, 6, replace=False), "b"] = np.nan
    cols = ["a", "b"]
    sk = SkPipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())])
    expected = sk.fit_transform(frame[cols])
    pipe = sq.Pipeline(
        [("fill", sq.impute.median(cols)), ("scale", sq.Scale(cols=cols))],
    ).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), expected, rtol=1e-12)


def test_all_missing_column():
    """A column of only NULLs is named in a StepError."""
    frame = pd.DataFrame({"dead": [np.nan, np.nan], "a": [1.0, 2.0]})
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'dead'"):
        sq.Pipeline([("scale", sq.Scale())]).learn(frame)


def test_settings_and_declaration():
    """Settings read back, and the static declaration matches the learning."""
    assert sq.Scale(keep=True).settings() == {
        "cols": sq.cols.numeric(),
        "keep": True,
        "suffix": None,
    }
    undeclared = type("Undeclared", (sq.Scale,), {"static": None})()
    assert classify(undeclared, [("a", DOUBLE)]) == "static"
    assert sq.Scale.static is True


def test_reserved_word_and_space_names_work_and_are_named_in_errors():
    """Columns called ``order`` and ``my col`` scale, and are named when refused."""
    frame = pd.DataFrame({"order": [1.0, 2.0, 3.0], "my col": [2.0, 4.0, 7.0]})
    sk = StandardScaler().fit(frame)
    got = sq.Pipeline([("scale", sq.Scale())]).learn(frame).apply(frame, out="pandas")
    assert_allclose(got.to_numpy(), sk.transform(frame), rtol=1e-12)
    dead = pd.DataFrame({"order": [np.nan, np.nan], "my col": [np.nan, np.nan]})
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'order'"):
        sq.Pipeline([("scale", sq.Scale(cols="order"))]).learn(dead)
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'my col'"):
        sq.Pipeline([("scale", sq.Scale(cols="my col"))]).learn(dead)


def test_real_nulls_are_skipped_in_learning():
    """NULLs (not NaN) stay NULL and do not count in the mean or spread."""
    rel = connection().sql("SELECT * FROM (VALUES (1.0), (NULL), (3.0)) t(a)")
    pipe = sq.Pipeline([("scale", sq.Scale())]).learn(rel)
    assert pipe["scale"].mean_ == {"a": 2.0}
    assert pipe.apply(rel).fetchall() == [(-1.0,), (None,), (1.0,)]


def test_integer_column_with_nulls():
    """An integer column with NULLs scales to DOUBLE and keeps the NULLs."""
    rel = connection().sql("SELECT * FROM (VALUES (2), (NULL), (4), (6)) t(n)")
    pipe = sq.Pipeline([("scale", sq.Scale())]).learn(rel)
    out = pipe.apply(rel)
    assert str(out.types[0]) == "DOUBLE"
    known = [[2.0], [4.0], [6.0]]
    expected = StandardScaler().fit(known).transform(known)
    got = [r[0] for r in out.fetchall()]
    assert got[1] is None
    assert_allclose([got[0], got[2], got[3]], expected[:, 0], rtol=1e-12)


def test_one_non_missing_value_scales_to_zero():
    """With a single non-missing value the spread is 0 (counts as 1): result 0."""
    frame = pd.DataFrame({"a": [np.nan, 7.0, np.nan]})
    got = sq.Pipeline([("scale", sq.Scale())]).learn(frame).apply(frame, out="pandas")
    assert got["a"].iloc[1] == 0.0


def test_all_null_column_without_nan():
    """A column of real NULLs is refused, naming it."""
    rel = connection().sql("SELECT NULL::DOUBLE AS dead, 1.0 AS ok")
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'dead'"):
        sq.Pipeline([("scale", sq.Scale())]).learn(rel)


def test_all_missing_after_impute_in_the_same_statement():
    """Impute then Scale on an all-missing column fails at Impute, by name."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "dead": [np.nan, np.nan]})
    pipe = sq.Pipeline([("fill", sq.impute()), ("scale", sq.Scale())])
    with pytest.raises(sq.errors.StepError, match=r"fill \(step 1\).*'dead'") as err:
        pipe.learn(frame)
    assert err.value.position == 1


def test_infinity_is_refused():
    """A column holding infinity is refused instead of scaling to NaN."""
    frame = pd.DataFrame({"a": [1.0, np.inf, 3.0]})
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 1\).*'a'.*infinity"):
        sq.Pipeline([("scale", sq.Scale())]).learn(frame)
