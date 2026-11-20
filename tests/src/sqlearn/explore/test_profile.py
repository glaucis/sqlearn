"""Tests of `sq.explore.profile`: the counts every column gets."""

import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError

COLUMNS = [
    "column", "type", "rows", "missing", "missing_share", "distinct",
    "distinct_share", "mean", "std", "min", "q25", "median", "q75", "max",
    "zeros", "negative", "infinite", "skewness", "kurtosis", "min_length",
    "max_length", "first", "last", "exact", "notes",
]  # fmt: skip


def test_a_profile_has_one_row_per_column_in_input_order():
    """A profile has one row per column in input order."""
    result = sq.explore.profile(pd.DataFrame({"b": [1, 2], "a": ["x", "y"]}))
    assert result.columns == COLUMNS
    assert [row[0] for row in result.fetchall()] == ["b", "a"]


def test_missing_counts_null_and_nan():
    """Missing counts null and nan."""
    con = connection()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1.0::DOUBLE), (NULL),"
                " ('NaN'::DOUBLE), (4.0::DOUBLE)) v(x)")  # fmt: skip
    row = dict(zip(COLUMNS, sq.explore.profile("t").fetchall()[0], strict=True))
    assert row["rows"] == 4
    assert row["missing"] == 2
    assert row["missing_share"] == 0.5
    assert row["distinct"] == 2
    assert row["distinct_share"] == 1.0
    assert row["type"] == "DOUBLE"
    assert row["exact"] is True
    assert row["notes"] == []


def test_columns_differing_only_by_case_each_get_a_row(tmp_path):
    """Columns differing only by case each get a row."""
    path = tmp_path / "case.csv"
    path.write_text("a,A\n1,2\n1,3\n")
    rows = sq.explore.profile(str(path)).fetchall()
    # DuckDB reads the second as A_1, the name sqlearn sees everywhere
    assert [row[0] for row in rows] == ["a", "A_1"]
    assert [row[COLUMNS.index("distinct")] for row in rows] == [1, 2]


def test_keyword_and_quoted_names_are_profiled():
    """Keyword and quoted names are profiled."""
    connection().execute("""CREATE TABLE k AS SELECT 1 AS "select", 'v' AS "it's" """)
    rows = sq.explore.profile("k").fetchall()
    assert [row[0] for row in rows] == ["select", "it's"]
    assert [row[2] for row in rows] == [1, 1]


def test_a_name_that_is_not_a_column_is_refused():
    """A name that is not a column is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.profile(pd.DataFrame({"a": [1]}), cols="nope")


def test_a_selector_choosing_nothing_gives_no_rows():
    """A selector choosing nothing gives no rows."""
    frame = pd.DataFrame({"a": ["x"]})
    assert sq.explore.profile(frame, sq.cols.numeric()).fetchall() == []


def test_no_rows_gives_zero_rows_and_null_shares():
    """No rows gives zero rows and null shares."""
    connection().execute("CREATE TABLE e (x INTEGER)")
    row = dict(zip(COLUMNS, sq.explore.profile("e").fetchall()[0], strict=True))
    assert row["rows"] == 0
    assert row["missing"] == 0
    assert row["missing_share"] is None
    assert row["distinct"] == 0
    assert row["distinct_share"] is None


def test_the_profile_outlives_its_frame():
    """The profile outlives its frame."""
    first = sq.explore.profile(pd.DataFrame({"a": [1, 2, 3]}))
    sq.explore.profile(pd.DataFrame({"z": [9]}))
    assert first.fetchall()[0][0] == "a"


def test_out_hands_back_the_form_named():
    """Out hands back the form named."""
    result = sq.explore.profile(pd.DataFrame({"a": [1]}), out="pandas")
    assert isinstance(result, pd.DataFrame)


def test_exact_false_says_so():
    """Exact false says so."""
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    rows = sq.explore.profile(frame, exact=False).fetchall()
    assert [row[COLUMNS.index("exact")] for row in rows] == [False, False]
