"""Tests of `sq.explore.correlations`: pairwise Pearson, as pandas gives it."""

import importlib
import math

import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError

# `sqlearn.explore.correlations` the attribute is the function; this is the module.
module = importlib.import_module("sqlearn.explore.correlations")


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(rng.normal(size=(60, 4)), columns=list("abcd"))
    frame["d"] = frame["a"] * 0.5 + frame["d"]
    frame.loc[0:9, "a"] = np.nan
    frame.loc[5:14, "b"] = np.nan
    frame.loc[20:22, "c"] = np.nan
    return frame


def test_pearson_matches_pandas_pairwise():
    """Each pair matches DataFrame.corr, and rows is the complete count."""
    frame = _frame()
    rows = sq.explore.correlations(frame).fetchall()
    expected = frame.corr()
    names = list(frame.columns)
    assert len(rows) == 6
    assert [(r[0], r[1]) for r in rows] == [
        (a, b) for i, a in enumerate(names) for b in names[i + 1 :]
    ]
    for a, b, correlation, count in rows:
        assert math.isclose(correlation, expected.loc[a, b], rel_tol=1e-12)
        assert count == int(frame[[a, b]].dropna().shape[0])


def test_the_result_has_the_documented_columns():
    """The result has the documented columns and types."""
    result = sq.explore.correlations(_frame())
    assert result.columns == ["column_a", "column_b", "correlation", "rows"]
    assert [str(t) for t in result.types] == ["VARCHAR", "VARCHAR", "DOUBLE", "BIGINT"]


def test_a_constant_column_gives_null():
    """A column with no variance gives NULL for its pairs."""
    frame = pd.DataFrame({"a": [0.1] * 4, "b": [1.0, 2.0, 3.0, 5.0], "c": [2, 1, 4, 3]})
    rows = {(r[0], r[1]): r for r in sq.explore.correlations(frame).fetchall()}
    assert rows["a", "b"][2:] == (None, 4)
    assert rows["a", "c"][2] is None
    assert rows["b", "c"][2] is not None


def test_a_pair_constant_over_its_rows_gives_null():
    """Variance is judged over the pair's rows, not the column's."""
    frame = pd.DataFrame({"a": [1.0, 1.0, 9.0], "b": [1.0, 2.0, None]})
    (row,) = sq.explore.correlations(frame).fetchall()
    assert row == ("a", "b", None, 2)


def test_a_pair_with_fewer_than_two_rows_gives_null():
    """One complete row is not enough for a correlation."""
    frame = pd.DataFrame({"a": [1.0, None, 3.0], "b": [None, 2.0, 4.0]})
    (row,) = sq.explore.correlations(frame).fetchall()
    assert row == ("a", "b", None, 1)


def test_nan_is_left_out_of_a_pair():
    """NaN and infinity leave a row out of the pair, as NULL does."""
    connection().execute(
        "CREATE TEMP TABLE nan_t AS SELECT * FROM (VALUES "
        "(1.0::DOUBLE, 2.0::DOUBLE), (2.0, 4.5), (3.0, 5.0), (4.0, 8.5),"
        "('NaN'::DOUBLE, 1.0), (5.0, 'inf'::DOUBLE), (6.0, NULL)) AS v(a, b)"
    )
    (row,) = sq.explore.correlations("nan_t").fetchall()
    clean = pd.DataFrame({"a": [1.0, 2, 3, 4], "b": [2.0, 4.5, 5, 8.5]})
    assert row[3] == 4
    assert math.isclose(row[2], clean["a"].corr(clean["b"]), rel_tol=1e-12)


def test_integers_and_decimals_are_taken():
    """Integer and DECIMAL columns are cast to DOUBLE."""
    connection().execute(
        "CREATE TEMP TABLE int_t AS SELECT * FROM (VALUES "
        "(1, 2.5::DECIMAL(5,1)), (2, 3.5), (3, 7.5)) AS v(a, b)"
    )
    (row,) = sq.explore.correlations("int_t").fetchall()
    assert row[3] == 3
    assert math.isclose(row[2], np.corrcoef([1, 2, 3], [2.5, 3.5, 7.5])[0, 1])


def test_only_numeric_columns_by_default():
    """Text and boolean columns are not taken by default."""
    frame = pd.DataFrame(
        {
            "a": [1.0, 2, 4],
            "s": ["x", "y", "z"],
            "b": [True, False, True],
            "c": [3, 1, 2],
        }
    )
    rows = sq.explore.correlations(frame).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("a", "c")]


def test_a_text_column_named_is_refused():
    """A text column named is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.correlations(pd.DataFrame({"s": ["a"], "n": [1.0]}), cols=["s", "n"])


def test_a_boolean_column_named_is_refused():
    """A boolean column named is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.correlations(
            pd.DataFrame({"b": [True], "n": [1.0]}), cols=["b", "n"]
        )


def test_method_must_be_known():
    """An unknown method is refused with a Fix: naming the methods."""
    with pytest.raises(SqlearnError, match=r"(?s)Why:.*Fix:.*'pearson'"):
        sq.explore.correlations(_frame(), method="kendall")


def test_fewer_than_two_columns_gives_no_pairs():
    """One column, or none chosen, gives an empty result of the same shape."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "s": ["x", "y"]})
    result = sq.explore.correlations(frame)
    assert result.fetchall() == []
    assert result.columns == ["column_a", "column_b", "correlation", "rows"]
    text = pd.DataFrame({"s": ["x"], "t": ["y"]})
    assert sq.explore.correlations(text, sq.cols.numeric()).fetchall() == []


def test_no_rows_give_pairs_with_null_and_zero():
    """Columns without rows still pair: NULL correlation, rows 0."""
    empty = pd.DataFrame(
        {"a": pd.Series([], dtype=float), "b": pd.Series([], dtype=float)}
    )
    assert sq.explore.correlations(empty).fetchall() == [("a", "b", None, 0)]


def test_pairs_are_computed_in_chunks(monkeypatch):
    """A small chunk gives the same answer as one statement."""
    frame = _frame()
    whole = sq.explore.correlations(frame).fetchall()
    monkeypatch.setattr(module, "_PAIRS_PER_QUERY", 2)
    chunked = sq.explore.correlations(frame).fetchall()
    assert sorted(chunked) == sorted(whole)
    assert [(r[0], r[1]) for r in chunked] == [(r[0], r[1]) for r in whole]


def test_out_is_honoured():
    """out= hands the result back in that form."""
    result = sq.explore.correlations(_frame(), out="pandas")
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 6
