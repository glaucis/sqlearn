"""Tests of `sq.explore.missing`: the commonest patterns of missing values."""

import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError


def test_patterns_match_a_pandas_group_by():
    """The (pattern, count) pairs match a pandas group-by of isna()."""
    frame = pd.DataFrame(
        {
            "a": [1, None, 3, None, None, 6, 7],
            "b": ["x", "y", None, None, None, "z", "w"],
            "c": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }
    )
    rows = sq.explore.missing(frame).fetchall()
    isna = frame.isna()
    names = isna.apply(lambda row: tuple(row.index[row]), axis=1)
    expected = names.value_counts().to_dict()
    assert {tuple(r[0]): r[1] for r in rows} == expected
    assert len(rows) == 4
    assert () in expected
    counts = [r[1] for r in rows]
    assert counts == sorted(counts, reverse=True)
    assert [r[2] for r in rows] == [n / len(frame) for n in counts]


def test_the_result_has_the_documented_columns():
    """The result has the documented columns and types."""
    result = sq.explore.missing(pd.DataFrame({"a": [None, 1]}))
    assert result.columns == ["missing", "count", "share"]
    assert [str(t) for t in result.types] == ["VARCHAR[]", "BIGINT", "DOUBLE"]


def test_ties_are_ordered_by_the_pattern():
    """Patterns with the same count come in a fixed order."""
    frame = pd.DataFrame({"a": [None, 1, 1], "b": [1, None, 1]})
    rows = sq.explore.missing(frame).fetchall()
    assert [(r[0], r[1]) for r in rows] == [([], 1), (["b"], 1), (["a"], 1)]


def test_patterns_caps_the_rows():
    """Patterns caps the rows; share stays a share of all rows."""
    frame = pd.DataFrame({"a": [None, 1, 1, 1], "b": [1, None, None, 1]})
    rows = sq.explore.missing(frame, patterns=2).fetchall()
    assert rows == [(["b"], 2, 0.5), ([], 1, 0.25)]


@pytest.mark.parametrize("patterns", [0, -1, 1.5, True, "3"])
def test_patterns_must_be_a_positive_integer(patterns):
    """Patterns must be a positive integer."""
    with pytest.raises(SqlearnError, match=r"patterns=.*Fix:"):
        sq.explore.missing(pd.DataFrame({"a": [1]}), patterns=patterns)


def test_more_than_64_columns_is_refused():
    """More than 64 chosen columns is refused, and cols= lifts it."""
    frame = pd.DataFrame({f"c{i}": [1, None] for i in range(65)})
    with pytest.raises(SqlearnError, match=r"Fix:.*cols="):
        sq.explore.missing(frame)
    assert sq.explore.missing(frame, cols=["c0", "c1"]).fetchall()


def test_nan_counts_as_missing():
    """NaN in a float column is missing, like NULL."""
    connection().execute(
        "CREATE TABLE mn AS SELECT * FROM (VALUES (1.0::DOUBLE), (NULL), "
        "('NaN'::DOUBLE), (1.0::DOUBLE)) v(x)"
    )
    rows = sq.explore.missing("mn").fetchall()
    assert rows == [([], 2, 0.5), (["x"], 2, 0.5)]


def test_no_rows_gives_no_patterns():
    """No rows, or a selector choosing nothing, gives an empty result."""
    empty = pd.DataFrame({"a": pd.Series([], dtype="float64")})
    assert sq.explore.missing(empty).fetchall() == []
    frame = pd.DataFrame({"a": ["x"]})
    assert sq.explore.missing(frame, sq.cols.numeric()).fetchall() == []


def test_out_is_honoured():
    """Out hands the result back in the format asked."""
    result = sq.explore.missing(pd.DataFrame({"a": [None]}), out="pandas")
    assert list(result["count"]) == [1]
