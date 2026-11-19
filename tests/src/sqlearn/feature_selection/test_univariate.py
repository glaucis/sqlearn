"""Tests of sq.select.best against scikit-learn's SelectKBest."""

import warnings

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_selection import SelectKBest, SelectPercentile, chi2, f_classif

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError, SqlearnWarning, StepError


def data(seed=5, rows=80):
    """Return 6 numeric columns, some related to the class, and the class."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, rows)
    frame = pd.DataFrame(
        {
            "a": rng.normal(0, 1, rows) + y,
            "b": rng.normal(0, 1, rows),
            "c": rng.uniform(0, 1, rows) + 2 * y,
            "d": rng.normal(5, 2, rows),
            "e": rng.normal(0, 1, rows) + 0.5 * y,
            "f": rng.integers(0, 4, rows).astype("int64"),
        }
    )
    return frame, y


def learn(step, frame, y):
    """Learn a pipeline of `step` on `frame` with the target `y`."""
    return sq.Pipeline([step]).learn(frame.assign(y=y), target="y")


@pytest.mark.parametrize("k", [1, 3, 6, "all"])
def test_best_keeps_the_columns_scikit_learn_keeps(k):
    """The same columns are kept, in their own order, unchanged."""
    frame, y = data()
    sk = SelectKBest(f_classif, k=k).fit(frame, y)
    kept = list(sk.get_feature_names_out())
    pipe = learn(sq.select.best(k=k), frame, y)
    assert pipe.columns_out_ == kept
    out = pipe.apply(frame, out="pandas")
    pd.testing.assert_frame_equal(out, frame[kept])


def test_ties_keep_the_later_column():
    """Equal scores: the later column is kept, as scikit-learn's stable sort."""
    frame, y = data()
    frame = frame.assign(twin=frame["c"])
    sk = SelectKBest(f_classif, k=1).fit(frame, y)
    pipe = learn(sq.select.best(k=1), frame, y)
    assert pipe.columns_out_ == list(sk.get_feature_names_out()) == ["twin"]


def test_a_constant_column_ranks_last_and_is_warned_about():
    """f_classif of a constant column is NaN: it ranks lowest, and is named."""
    frame, y = data()
    frame = frame.assign(flat=1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # its own: constant, divide by 0
        sk = SelectKBest(f_classif, k=6).fit(frame, y)
    with pytest.warns(SqlearnWarning, match="column 'flat' is constant") as caught:
        pipe = learn(sq.select.best(k=6), frame, y)
    assert len([w for w in caught if "flat" in str(w.message)]) == 1
    assert "Fix:" in str(caught[0].message)
    assert np.isnan(pipe["best"].scores_["flat"])
    assert pipe.columns_out_ == list(sk.get_feature_names_out())
    assert "flat" not in pipe.columns_out_


def test_several_constant_columns_are_named_in_one_warning():
    """One warning names every constant column."""
    frame, y = data()
    frame = frame.assign(flat=1.0, level=0.0)
    with pytest.warns(SqlearnWarning, match="columns 'flat', 'level' are constant"):
        learn(sq.select.best(k=2), frame, y)


def test_k_above_the_column_count_keeps_all_and_warns():
    """k=9 of 6 columns keeps all 6, with scikit-learn's warning."""
    frame, y = data()
    with pytest.warns(SqlearnWarning, match="k=9") as caught:
        pipe = learn(sq.select.best(k=9), frame, y)
    assert "Fix:" in str(caught[0].message)
    assert pipe.columns_out_ == list(frame.columns)


def test_k_zero_keeps_none_and_warns():
    """k=0 keeps none of its columns; a text column passes beside them."""
    frame, y = data()
    frame = frame.assign(city="x")
    with pytest.warns(SqlearnWarning, match="k=0") as caught:
        pipe = learn(sq.select.best(k=0), frame, y)
    assert "Fix:" in str(caught[0].message)
    assert pipe.columns_out_ == ["city"]


@pytest.mark.filterwarnings("ignore::sqlearn.errors.SqlearnWarning")
def test_learn_raises_when_no_column_would_remain():
    """k=0 with no other column: a table needs a column, so learn raises."""
    frame, y = data()
    with pytest.raises(StepError, match="no column") as e:
        learn(sq.select.best(k=0), frame, y)
    assert "Fix:" in str(e.value)


def test_chi2_refuses_a_negative_value():
    """As scikit-learn's chi2 refuses it, naming the column."""
    frame, y = data()
    with pytest.raises(ValueError, match="non-negative"):
        chi2(frame, y)
    with pytest.raises(StepError, match="'a'") as e:
        learn(sq.select.best(k=2, score="chi2"), frame, y)
    assert "Fix:" in str(e.value)
    assert "sq.scale.minmax" in str(e.value)


@pytest.mark.parametrize("score", ["f_classif", "f_regression", "chi2"])
def test_the_scores_refuse_a_missing_value(score):
    """NULL from pandas, NaN and infinity from a DuckDB table: refused."""
    frame, y = data()
    frame = frame.abs()
    holed = frame.astype({"b": "float64"})
    holed.loc[3, "b"] = None
    with pytest.raises(StepError, match=r"'b'.*missing") as e:
        learn(sq.select.best(k=2, score=score), holed, y)
    assert "sq.impute" in str(e.value)
    con = connection()
    con.execute(
        "CREATE OR REPLACE TABLE holed AS SELECT * FROM (VALUES "
        "(1.0, 'NaN'::DOUBLE, 0), (2.0, 1.0, 1), (3.0, 2.0, 0), (4.0, 0.5, 1)) "
        "t(a, b, y)"
    )
    with pytest.raises(StepError, match=r"'b'.*missing") as e:
        sq.Pipeline([sq.select.best(k=1, score=score)]).learn("holed", target="y")
    assert "Fix:" in str(e.value)
    con.execute(
        "CREATE OR REPLACE TABLE holed AS SELECT * FROM (VALUES "
        "(1.0, 'inf'::DOUBLE, 0), (2.0, 1.0, 1), (3.0, 2.0, 0), (4.0, 0.5, 1)) "
        "t(a, b, y)"
    )
    with pytest.raises(StepError, match=r"'b'.*infinite") as e:
        sq.Pipeline([sq.select.best(k=1, score=score)]).learn("holed", target="y")
    assert "Fix:" in str(e.value)


@pytest.mark.parametrize("score", ["f_classif", "f_regression", "chi2"])
def test_a_missing_target_is_refused(score):
    """A NULL target value is refused, as scikit-learn refuses NaN in y."""
    frame, y = data()
    target = y.astype(float)
    target[7] = np.nan
    with pytest.raises(StepError, match="target") as e:
        learn(sq.select.best(k=2, score=score), frame.abs(), target)
    assert "Fix:" in str(e.value)


@pytest.mark.parametrize("bad", [{"k": -1}, {"k": 2.5}, {"k": True}, {"score": "f"}])
def test_best_refuses_a_bad_k_or_score(bad):
    """At the call, as scikit-learn's parameter check (True is refused too)."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.select.best(**bad)


def wide(seed=9, rows=90):
    """Return 13 numeric columns, some related to the class, and the class."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 3, rows)
    frame = pd.DataFrame(
        {f"c{i:02d}": rng.normal(0, 1, rows) + (i % 5) * 0.2 * y for i in range(13)}
    )
    return frame, y


@pytest.mark.parametrize("percentile", [5, 10, 50, 99, 100])
def test_percentile_keeps_the_columns_scikit_learn_keeps(percentile):
    """The same columns are kept, in their own order, unchanged."""
    frame, y = wide()
    sk = SelectPercentile(f_classif, percentile=percentile).fit(frame, y)
    kept = list(sk.get_feature_names_out())
    pipe = learn(sq.select.percentile(percentile=percentile), frame, y)
    assert pipe.columns_out_ == kept
    pd.testing.assert_frame_equal(pipe.apply(frame, out="pandas"), frame[kept])


def test_percentile_ties_keep_the_earlier_columns():
    """Equal scores at the threshold: the earliest are kept, as scikit-learn's."""
    frame, y = wide()
    frame = frame.assign(twin=frame["c03"], twin2=frame["c03"])
    for percentile in (20, 40, 60):
        sk = SelectPercentile(f_classif, percentile=percentile).fit(frame, y)
        pipe = learn(sq.select.percentile(percentile=percentile), frame, y)
        assert pipe.columns_out_ == list(sk.get_feature_names_out())


def test_percentile_zero_keeps_none_and_warns():
    """percentile=0 keeps none of its columns; a text column passes beside them."""
    frame, y = wide()
    frame = frame.assign(city="x")
    with pytest.warns(SqlearnWarning, match="percentile=0") as caught:
        pipe = learn(sq.select.percentile(percentile=0), frame, y)
    assert "Fix:" in str(caught[0].message)
    assert pipe.columns_out_ == ["city"]


@pytest.mark.filterwarnings("ignore::sqlearn.errors.SqlearnWarning")
def test_percentile_zero_with_no_other_column_raises():
    """Nothing would remain: learn raises, with a Fix line."""
    frame, y = wide()
    with pytest.raises(StepError, match="no column") as e:
        learn(sq.select.percentile(percentile=0), frame, y)
    assert "Fix:" in str(e.value)


@pytest.mark.parametrize("bad", [-1, 100.5, True, float("nan"), "10"])
def test_percentile_refuses_a_value_outside_0_to_100(bad):
    """At the call, as scikit-learn's parameter check."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.select.percentile(percentile=bad)


def test_percentile_is_an_output_setting_and_shares_the_scores():
    """Its repr, name and scores follow best's."""
    frame, y = wide()
    step = sq.select.percentile(percentile=30, score="f_classif")
    assert repr(step) == "sq.select.percentile(percentile=30)"
    assert step.default_name() == "percentile"
    assert step.output_settings == frozenset({"percentile"})
    pipe = learn(step, frame, y)
    assert (
        pipe["percentile"].scores_ == learn(sq.select.best(), frame, y)["best"].scores_
    )


@pytest.mark.parametrize(
    ("make", "value", "setting"),
    [
        (sq.select.best, np.int64(3), "k"),
        (sq.select.percentile, np.int64(10), "percentile"),
        (sq.select.percentile, np.float64(12.5), "percentile"),
    ],
)
def test_numpy_numbers_are_taken_as_scikit_learn_takes_them(make, value, setting):
    """A numpy number is a number, as scikit-learn's Interval checks; kept plain."""
    step = make(**{setting: value})
    got = getattr(step, setting)
    assert got == value
    assert type(got) in (int, float)
    frame, y = wide()
    sk_class = SelectKBest if setting == "k" else SelectPercentile
    sk = sk_class(f_classif, **{setting: value}).fit(frame, y)
    pipe = learn(step, frame, y)
    assert pipe.columns_out_ == list(sk.get_feature_names_out())


@pytest.mark.parametrize("bad", [np.float64(2.0), np.bool_(True), np.int64(-1)])
def test_best_refuses_a_numpy_value_scikit_learn_refuses(bad):
    """A numpy float or bool is not a whole number, nor a negative one."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.select.best(k=bad)


@pytest.mark.parametrize("bad", [np.bool_(True), np.float64("nan"), np.int64(101)])
def test_percentile_refuses_a_numpy_value_outside_0_to_100(bad):
    """A numpy bool, NaN, or a number above 100 is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.select.percentile(percentile=bad)


@pytest.mark.parametrize("percentile", [10, 30, 50, 80, 95])
def test_percentile_ranks_a_nan_score_lowest_as_scikit_learn(percentile):
    """A constant column scores NaN under f_classif: it is the last kept."""
    frame, y = wide()
    frame = frame.assign(flat=1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # both warn of the constant column
        sk = SelectPercentile(f_classif, percentile=percentile).fit(frame, y)
        pipe = learn(sq.select.percentile(percentile=percentile), frame, y)
    assert np.isnan(pipe["percentile"].scores_["flat"])
    assert pipe.columns_out_ == list(sk.get_feature_names_out())


@pytest.mark.parametrize("columns", [["c04"], ["c04", "c01"]])
@pytest.mark.parametrize("percentile", [1, 49, 50, 51, 99, 100])
def test_percentile_of_one_or_two_columns_keeps_scikit_learns(columns, percentile):
    """With one or two columns the threshold is a column's own score."""
    frame, y = wide()
    frame = frame[columns]
    sk = SelectPercentile(f_classif, percentile=percentile).fit(frame, y)
    pipe = learn(sq.select.percentile(percentile=percentile), frame.assign(t="x"), y)
    assert pipe.columns_out_ == [*sk.get_feature_names_out(), "t"]
