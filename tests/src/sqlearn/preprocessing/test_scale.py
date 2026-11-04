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
        [("fill", sq.Impute(cols=cols)), ("scale", sq.Scale(cols=cols))],
    ).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), expected, rtol=1e-12)


def test_all_missing_column():
    """A column of only NULLs is named in a StepError."""
    frame = pd.DataFrame({"dead": [np.nan, np.nan], "a": [1.0, 2.0]})
    with pytest.raises(sq.StepError, match=r"scale \(step 1\).*'dead'"):
        sq.Pipeline([("scale", sq.Scale())]).learn(frame)


def test_settings_and_declaration():
    """Settings read back, and the static declaration matches the learning."""
    assert sq.Scale(keep=True).settings() == {
        "cols": sq.numeric(),
        "keep": True,
        "suffix": None,
    }
    undeclared = type("Undeclared", (sq.Scale,), {"static": None})()
    assert classify(undeclared, [("a", DOUBLE)]) == "static"
    assert sq.Scale.static is True
