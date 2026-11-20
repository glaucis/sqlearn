"""Tests of `sq.explore.profile`: the counts every column gets."""

import math

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


def _row(sql, **kwargs):
    """Profile the single column x of a table built from VALUES `sql`."""
    con = connection()
    con.execute("DROP TABLE IF EXISTS s")
    con.execute(f"CREATE TABLE s AS SELECT * FROM (VALUES {sql}) v(x)")
    rows = sq.explore.profile("s", **kwargs).fetchall()
    return dict(zip(COLUMNS, rows[0], strict=True))


def _close(actual, expected):
    if expected == 0:
        assert math.isclose(actual, expected, abs_tol=1e-12)
    else:
        assert math.isclose(actual, expected, rel_tol=1e-12)


def test_numeric_statistics_follow_pandas():
    """Numeric statistics follow pandas."""
    row = _row("(1.0::DOUBLE), (2.0::DOUBLE), (2.0::DOUBLE), (9.0::DOUBLE), (NULL)")
    series = pd.Series([1.0, 2.0, 2.0, 9.0])
    described = series.describe()
    expected = {
        "mean": described["mean"], "std": described["std"],
        "min": described["min"], "q25": described["25%"],
        "median": described["50%"], "q75": described["75%"],
        "max": described["max"], "skewness": series.skew(),
        "kurtosis": series.kurt(),
    }  # fmt: skip
    for label, value in expected.items():
        _close(row[label], value)
    assert (row["zeros"], row["negative"], row["infinite"]) == (0, 0, 0)
    assert row["min_length"] is None
    assert row["first"] is None


def test_zeros_and_negatives_are_counted():
    """Zeros and negatives are counted."""
    row = _row("(0::DOUBLE), (-1::DOUBLE), (3::DOUBLE), (0::DOUBLE), (0::DOUBLE)")
    assert (row["zeros"], row["negative"]) == (3, 1)


def test_infinite_values_are_counted_and_left_out():
    """Infinite values are counted and left out of the statistics."""
    row = _row("(1.0::DOUBLE), ('inf'::DOUBLE), (3.0::DOUBLE), ('-inf'::DOUBLE)")
    assert row["infinite"] == 2
    assert row["missing"] == 0
    assert row["mean"] == 2.0
    assert row["max"] == 3.0
    assert row["min"] == 1.0
    assert row["negative"] == 0


def test_integers_and_decimals_are_numbers():
    """Integers and decimals are numbers."""
    con = connection()
    con.execute("CREATE TABLE n AS SELECT 1 AS i, 1.25::DECIMAL(10,2) AS d"
                " UNION ALL SELECT 2, 2.25::DECIMAL(10,2)")  # fmt: skip
    rows = {
        r[0]: dict(zip(COLUMNS, r, strict=True))
        for r in sq.explore.profile("n").fetchall()
    }
    assert rows["i"]["mean"] == 1.5
    assert rows["d"]["mean"] == 1.75
    assert rows["d"]["max"] == 2.25


def test_a_boolean_mean_is_its_share_true():
    """A boolean mean is its share true, and nothing else is numeric."""
    row = _row("(true), (false), (true), (NULL)")
    _close(row["mean"], 2 / 3)
    assert row["distinct"] == 2
    for label in ["std", "min", "q25", "median", "q75", "max", "zeros",
                  "negative", "infinite", "skewness", "kurtosis"]:  # fmt: skip
        assert row[label] is None


def test_text_gets_lengths_and_no_numbers():
    """Text gets lengths and no numbers."""
    row = _row("('a'), ('bcd'), (NULL)")
    assert (row["min_length"], row["max_length"]) == (1, 3)
    assert row["mean"] is None
    assert row["first"] is None


def test_dates_get_first_and_last_as_text():
    """Dates get first and last as text."""
    row = _row("(DATE '2024-03-01'), (DATE '2023-01-05'), (NULL)")
    assert (row["first"], row["last"]) == ("2023-01-05", "2024-03-01")
    assert row["mean"] is None
    zoned = _row("(TIMESTAMPTZ '2024-03-01 10:00:00+00')")
    assert zoned["first"] is not None


def test_one_value_has_null_std_and_shape():
    """One value has a null std and shape."""
    row = _row("(5.0::DOUBLE), (NULL)")
    assert row["mean"] == 5.0
    assert row["std"] is None
    assert row["skewness"] is None
    assert row["kurtosis"] is None


def test_an_all_missing_number_has_null_statistics():
    """An all-missing number has null statistics."""
    row = _row("(NULL::DOUBLE), ('NaN'::DOUBLE)")
    assert row["mean"] is None
    assert row["median"] is None
    assert row["zeros"] == 0


def test_approximate_quartiles_are_close():
    """Approximate quartiles are close when exact is False."""
    values = ", ".join(f"({float(i)!r}::DOUBLE)" for i in range(1, 101))
    row = _row(values, exact=False)
    assert abs(row["median"] - 50.5) < 2
    assert row["mean"] == 50.5


def test_the_distinct_share_never_exceeds_one():
    """The distinct share never exceeds one."""
    values = ", ".join(f"({i})" for i in range(50))
    row = _row(values, exact=False)
    assert row["distinct_share"] <= 1.0
