"""Tests of `sq.explore.top`: the commonest values of each column."""

import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError


def test_the_commonest_values_match_value_counts():
    """The commonest values match value_counts, ties ordered by value."""
    values = [*"bbbaacddeNN", None, None]
    frame = pd.DataFrame({"t": values})
    rows = sq.explore.top(frame, k=3).fetchall()
    counts = frame["t"].value_counts(dropna=False)
    expected = sorted(
        counts.items(),
        key=lambda kv: (
            -kv[1],
            pd.isna(kv[0]),
            kv[0] if isinstance(kv[0], str) else "",
        ),
    )
    assert [(r[1], r[2]) for r in rows] == expected[:3]
    assert all(r[0] == "t" for r in rows)
    assert [r[3] for r in rows] == [n / len(values) for _, n in expected[:3]]


def test_the_result_has_the_documented_columns():
    """The result has the documented columns and types."""
    result = sq.explore.top(pd.DataFrame({"t": ["a"]}))
    assert result.columns == ["column", "value", "count", "share"]
    kinds = [str(t) for t in result.types]
    assert kinds == ["VARCHAR", "VARCHAR", "BIGINT", "DOUBLE"]


def test_missing_values_are_one_null_row():
    """NULL and NaN together are one row with a NULL value."""
    connection().execute(
        "CREATE TABLE tn AS SELECT * FROM (VALUES (1.0::DOUBLE), (NULL), "
        "('NaN'::DOUBLE), (1.0::DOUBLE)) v(x)"
    )
    rows = sq.explore.top("tn").fetchall()
    assert rows == [("x", "1.0", 2, 0.5), ("x", None, 2, 0.5)]


def test_k_caps_each_column():
    """K caps each column."""
    frame = pd.DataFrame({"a": [1, 2, 3, 4], "b": ["x", "y", "z", "z"]})
    rows = sq.explore.top(frame, k=2).fetchall()
    assert [r[0] for r in rows] == ["a", "a", "b", "b"]
    assert [r[1] for r in rows[2:]] == ["z", "x"]


@pytest.mark.parametrize("k", [0, -1, 1.5, True, "3"])
def test_k_must_be_a_positive_integer(k):
    """K must be a positive integer."""
    with pytest.raises(SqlearnError, match=r"k=.*Fix:"):
        sq.explore.top(pd.DataFrame({"a": [1]}), k=k)


def test_numbers_are_shown_as_duckdb_writes_them():
    """Numbers are shown as DuckDB writes them."""
    rows = sq.explore.top(pd.DataFrame({"a": [2.5]})).fetchall()
    assert rows == [("a", "2.5", 1, 1.0)]


def test_cols_chooses_columns():
    """Cols chooses columns, and a name that is not a column is refused."""
    frame = pd.DataFrame({"a": [1], "b": ["x"]})
    assert [r[0] for r in sq.explore.top(frame, "b").fetchall()] == ["b"]
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.top(frame, "zz")


def test_a_selector_choosing_nothing_is_empty():
    """A selector that chooses no column gives an empty result."""
    frame = pd.DataFrame({"b": ["x"]})
    assert sq.explore.top(frame, sq.cols.numeric()).fetchall() == []


def test_no_rows_is_an_empty_result():
    """No rows is an empty result."""
    frame = pd.DataFrame({"a": pd.Series([], dtype="int64")})
    assert sq.explore.top(frame).fetchall() == []


def test_out_is_honoured():
    """Out hands the result back in the format asked."""
    result = sq.explore.top(pd.DataFrame({"a": [1]}), out="pandas")
    assert list(result["count"]) == [1]
