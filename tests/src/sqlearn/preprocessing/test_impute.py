"""Tests of Impute against scikit-learn's SimpleImputer."""

import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_allclose
from sklearn.impute import SimpleImputer

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify


def holes(seed=0, rows=40):
    """Return seeded data: two float columns with NaN holes, one int column."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "a": rng.normal(10, 3, rows),
            "b": rng.exponential(2, rows),
            "n": rng.integers(0, 50, rows).astype("int64"),
        },
    )
    frame.loc[rng.choice(rows, 7, replace=False), "a"] = np.nan
    frame.loc[rng.choice(rows, 5, replace=False), "b"] = np.nan
    return frame


@pytest.mark.parametrize("strategy", ["median", "mean"])
def test_impute_matches_simple_imputer(strategy):
    """Filling NaN holes gives the same numbers as scikit-learn's imputer."""
    frame = holes()
    cols = ["a", "b"]
    sk = SimpleImputer(strategy=strategy).fit(frame[cols])
    pipe = sq.Pipeline([("fill", sq.Impute(cols=cols, strategy=strategy))])
    got = pipe.learn(frame).apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), sk.transform(frame[cols]), rtol=1e-12)
    assert_allclose(
        [pipe["fill"].value_[c] for c in cols],
        sk.statistics_,
        rtol=1e-12,
    )


def test_median_of_an_even_count_is_the_exact_median():
    """Four values: the median is the mean of the middle two."""
    frame = pd.DataFrame({"a": [1.0, 2.0, 4.0, 10.0, np.nan]})
    got = sq.Pipeline([("fill", sq.Impute())]).learn(frame).apply(frame, out="pandas")
    assert got["a"].tolist()[-1] == 3.0


def test_impute_treats_nan_as_missing():
    """NULL and NaN both count as missing, and neither counts in the learning."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE), (3.0)) t(a)",
    )
    pipe = sq.Pipeline([("fill", sq.Impute(strategy="mean"))]).learn(rel)
    assert pipe["fill"].value_ == {"a": 2.0}
    assert pipe.apply(rel).fetchall() == [(1.0,), (2.0,), (2.0,), (3.0,)]


def test_integer_columns_come_out_double():
    """An integer column is imputed to DOUBLE, as scikit-learn returns floats."""
    frame = holes()
    frame["n"] = frame["n"].astype("Int64")
    frame.loc[[3, 9], "n"] = pd.NA
    expected = (
        SimpleImputer(strategy="median")
        .fit(frame[["n"]].astype("float64"))
        .transform(frame[["n"]].astype("float64"))
    )
    pipe = sq.Pipeline([("fill", sq.Impute(cols=["n"]))]).learn(frame)
    rel = pipe.apply(frame)
    assert str(rel.types[2]) == "DOUBLE"
    got = np.array([[r[2]] for r in rel.fetchall()])
    assert_allclose(got, expected, rtol=1e-12)


def test_default_selects_numeric_columns_only():
    """Text columns are left alone by default."""
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0], "city": ["x", "y", "z"]})
    got = sq.Pipeline([("fill", sq.Impute())]).learn(frame).apply(frame, out="pandas")
    assert got["a"].tolist() == [1.0, 2.0, 3.0]
    assert got["city"].tolist() == ["x", "y", "z"]


def test_keep_adds_a_column_beside_the_input():
    """With keep=True the input stays and ``a_fill`` (step name) is added."""
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
    pipe = sq.Pipeline([("fill", sq.Impute(keep=True))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == ["a", "a_fill"]
    assert got["a_fill"].tolist() == [1.0, 2.0, 3.0]


def test_all_missing_column():
    """Scikit-learn drops such a column; sqlearn names it in a StepError."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "dead": [np.nan, np.nan]})
    with pytest.raises(sq.StepError, match=r"fill \(step 1\).*'dead'") as err:
        sq.Pipeline([("fill", sq.Impute())]).learn(frame)
    assert err.value.step == "fill"
    assert err.value.position == 1


def test_text_column_is_refused_by_name():
    """Selecting a text column is refused, naming it and the step."""
    frame = pd.DataFrame({"city": ["x", "y"]})
    pipe = sq.Pipeline([("pass", sq.Step()), ("fill", sq.Impute(cols="city"))])
    with pytest.raises(sq.StepError, match=r"fill \(step 2\).*'city'.*text") as err:
        pipe.learn(frame)
    assert err.value.position == 2


def test_unknown_strategy_is_refused():
    """A strategy other than median or mean fails in ``__init__``."""
    with pytest.raises(sq.SqlearnError, match="mode"):
        sq.Impute(strategy="mode")


def test_settings_and_declaration():
    """Settings read back, and the static declaration matches the learning."""
    step = sq.Impute(strategy="mean", keep=True, suffix="f")
    assert step.settings() == {
        "cols": sq.numeric(),
        "strategy": "mean",
        "keep": True,
        "suffix": "f",
    }
    undeclared = type("Undeclared", (sq.Impute,), {"static": None})()
    assert classify(undeclared, [("a", DOUBLE)]) == "static"
    assert sq.Impute.static is True


def test_reserved_word_and_space_names_work_and_are_named_in_errors():
    """Columns called ``order`` and ``my col`` fill, and are named when refused."""
    frame = pd.DataFrame({"order": [1.0, np.nan, 3.0], "my col": [2.0, 4.0, np.nan]})
    got = sq.Pipeline([("fill", sq.Impute())]).learn(frame).apply(frame, out="pandas")
    assert got["order"].tolist() == [1.0, 2.0, 3.0]
    assert got["my col"].tolist() == [2.0, 4.0, 3.0]
    dead = pd.DataFrame({"order": [np.nan, np.nan], "my col": [np.nan, np.nan]})
    with pytest.raises(sq.StepError, match=r"fill \(step 1\).*'order'"):
        sq.Pipeline([("fill", sq.Impute(cols="order"))]).learn(dead)
    with pytest.raises(sq.StepError, match=r"fill \(step 1\).*'my col'"):
        sq.Pipeline([("fill", sq.Impute(cols="my col"))]).learn(dead)


def test_all_null_column_without_nan():
    """A column of real NULLs (not NaN) is refused, naming it."""
    rel = connection().sql("SELECT NULL::DOUBLE AS dead, 1.0 AS ok")
    with pytest.raises(sq.StepError, match=r"fill \(step 1\).*'dead'"):
        sq.Pipeline([("fill", sq.Impute())]).learn(rel)


def test_integer_nulls_are_filled():
    """A real NULL in an integer column is filled with the median, as DOUBLE."""
    rel = connection().sql("SELECT * FROM (VALUES (1), (NULL), (5), (9)) t(n)")
    pipe = sq.Pipeline([("fill", sq.Impute())]).learn(rel)
    assert pipe.apply(rel).fetchall() == [(1.0,), (5.0,), (5.0,), (9.0,)]


@pytest.mark.parametrize("strategy", ["median", "mean"])
def test_infinity_is_refused(strategy):
    """A column holding infinity is refused (the median would hide it)."""
    frame = pd.DataFrame({"a": [1.0, np.inf, 3.0, np.nan, 2.0]})
    pipe = sq.Pipeline([("fill", sq.Impute(strategy=strategy))])
    with pytest.raises(sq.StepError, match=r"fill \(step 1\).*'a'.*infinity"):
        pipe.learn(frame)
