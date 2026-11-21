"""Tests of `sq.explore.histogram`: equal-width bins, as numpy makes them."""

import importlib

import duckdb
import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError

# `sqlearn.explore.histogram` the attribute is the function; this is the module.
module = importlib.import_module("sqlearn.explore.histogram")

COLUMNS = ["column", "bin", "low", "high", "count"]


def test_bins_match_numpy():
    """Bins match numpy: edges within tolerance, counts exactly."""
    values = np.random.default_rng(0).normal(size=1000)
    rows = sq.explore.histogram(pd.DataFrame({"x": values}), bins=7).fetchall()
    counts, edges = np.histogram(values, bins=7)
    assert [r[1] for r in rows] == list(range(7))
    assert [r[4] for r in rows] == counts.tolist()
    assert [r[2] for r in rows] == edges[:-1].tolist()
    assert [r[3] for r in rows] == edges[1:].tolist()
    assert sum(r[4] for r in rows) == 1000
    assert rows[-1][4] >= 1  # the maximum is in the last bin


def test_the_result_has_the_documented_columns():
    """The result has the documented columns."""
    result = sq.explore.histogram(pd.DataFrame({"x": [1.0, 2.0]}))
    assert result.columns == COLUMNS


def test_integers_on_an_edge_fall_where_numpy_puts_them():
    """Integers on an edge fall where numpy puts them."""
    values = np.arange(0, 101)
    rows = sq.explore.histogram(pd.DataFrame({"x": values}), bins=10).fetchall()
    assert [r[4] for r in rows] == np.histogram(values, bins=10)[0].tolist()


def test_only_numeric_columns_by_default():
    """Only numeric columns are taken by default."""
    frame = pd.DataFrame({"n": [1, 2], "s": ["a", "b"], "b": [True, False]})
    rows = sq.explore.histogram(frame, bins=2).fetchall()
    assert {r[0] for r in rows} == {"n"}


def test_a_text_column_named_is_refused():
    """A text column named is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.histogram(pd.DataFrame({"s": ["a"]}), cols="s")


def test_a_boolean_column_named_is_refused():
    """A boolean column named is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.histogram(pd.DataFrame({"b": [True]}), cols=["b"])


def test_a_selector_choosing_nothing_gives_no_rows():
    """A selector choosing nothing gives no rows."""
    frame = pd.DataFrame({"a": ["x"]})
    assert sq.explore.histogram(frame, sq.cols.numeric()).fetchall() == []


def test_a_constant_column_has_one_bin():
    """A constant column has one bin holding every row."""
    rows = sq.explore.histogram(pd.DataFrame({"x": [3.0] * 4}), bins=5).fetchall()
    assert rows == [("x", 0, 3.0, 3.0, 4)]


def test_missing_and_infinite_values_are_left_out():
    """Missing and infinite values are left out."""
    connection().execute(
        "CREATE TABLE m AS SELECT * FROM (VALUES (1.0::DOUBLE), (NULL),"
        " ('NaN'::DOUBLE), ('inf'::DOUBLE), ('-inf'::DOUBLE), (3.0::DOUBLE)) v(x)"
    )
    rows = sq.explore.histogram("m", bins=2).fetchall()
    assert rows == [("x", 0, 1.0, 2.0, 1), ("x", 1, 2.0, 3.0, 1)]


def test_a_column_with_nothing_finite_gets_no_bins():
    """A column with nothing finite gets no bins."""
    connection().execute(
        "CREATE TABLE n AS SELECT * FROM (VALUES (NULL::DOUBLE), ('inf'::DOUBLE)) v(x)"
    )
    assert sq.explore.histogram("n").fetchall() == []


@pytest.mark.parametrize("bins", [0, -1, 2.5, True])
def test_bins_must_be_a_positive_integer(bins):
    """Bins must be a positive integer."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.histogram(pd.DataFrame({"x": [1.0]}), bins=bins)


def test_no_rows_gives_no_bins():
    """No rows gives no bins."""
    connection().execute("CREATE TABLE e (x INTEGER)")
    assert sq.explore.histogram("e").fetchall() == []


def test_empty_bins_appear_with_zero_counts():
    """Empty bins appear with zero counts."""
    rows = sq.explore.histogram(pd.DataFrame({"x": [0, 0, 10]}), bins=5).fetchall()
    assert [r[4] for r in rows] == [2, 0, 0, 0, 1]


def test_each_column_is_binned_on_its_own_range():
    """Each column is binned on its own range."""
    frame = pd.DataFrame({"a": [0, 10], "b": [100, 200]})
    rows = sq.explore.histogram(frame, bins=2).fetchall()
    assert [(r[0], r[2], r[3]) for r in rows] == [
        ("a", 0.0, 5.0), ("a", 5.0, 10.0), ("b", 100.0, 150.0), ("b", 150.0, 200.0),
    ]  # fmt: skip


def test_a_name_with_a_quote_is_binned():
    """A name with a quote is binned."""
    connection().execute(
        """CREATE TABLE q AS SELECT * FROM (VALUES (1), (2)) v("it's")"""
    )
    assert sq.explore.histogram("q", bins=1).fetchall() == [("it's", 0, 1.0, 2.0, 2)]


def _wide() -> pd.DataFrame:
    """Five numeric columns of different ranges, with a missing value."""
    return pd.DataFrame(
        {
            "a": [0.0, 1.0, 2.0, 3.0],
            "b": [10, 20, 30, 40],
            "c": [-1.0, float("nan"), 1.0, 0.5],
            "d": [5.0, 5.0, 5.0, 5.0],
            "e": [1e6, 2e6, 3e6, 1.5e6],
        }
    )


def test_blocks_of_columns_give_the_same_bins_as_one_block(monkeypatch):
    """Blocks of 2 over 5 columns read 2 columns a statement, and match one."""
    monkeypatch.setattr(module, "_BLOCK_COLUMNS", 100)
    whole = sq.explore.histogram(_wide(), bins=3).fetchall()
    seen = []
    original = module._fetch

    def spy(source, sql):
        seen.append(sql)
        return original(source, sql)

    monkeypatch.setattr(module, "_fetch", spy)
    monkeypatch.setattr(module, "_BLOCK_COLUMNS", 2)
    blocked = sq.explore.histogram(_wide(), bins=3).fetchall()
    assert blocked == whole
    read = [{n for n in "abcde" if f'"{n}"' in sql} for sql in seen]
    # The extremes, then the counts, each in blocks of two columns.
    assert read == [{"a", "b"}, {"c", "d"}, {"e"}] * 2


def test_no_statement_filters_an_aggregate(monkeypatch):
    """Values are left out by CASE, not FILTER (see profile's test)."""
    seen = []
    original = module._fetch

    def spy(source, sql):
        seen.append(sql)
        return original(source, sql)

    monkeypatch.setattr(module, "_fetch", spy)
    sq.explore.histogram(_wide())
    assert seen
    assert not [sql for sql in seen if "FILTER" in sql]


@pytest.mark.parametrize("failing", [0, 1])
def test_running_out_of_memory_is_refused_with_a_fix(monkeypatch, failing):
    """An out-of-memory error at the extremes (0) or the counts (1) is refused.

    The error is forced by monkeypatching the statement runner to raise
    DuckDB's out-of-memory error: a real one depends on the machine.
    """
    calls = []
    original = module._fetch

    def fail(source, sql):
        calls.append(None)
        if len(calls) > failing:
            raise duckdb.OutOfMemoryException("Out of Memory Error: failed")
        return original(source, sql)

    monkeypatch.setattr(module, "_fetch", fail)
    with pytest.raises(
        SqlearnError, match=r"(?s)Why:.*Fix:.*cols=.*memory=.*threads"
    ) as info:
        sq.explore.histogram(_wide())
    assert "failed" in str(info.value)
    assert "`histogram`" in str(info.value)


@pytest.mark.parametrize(
    ("low", "high"),
    [(-1e308, 1e308), (-1.7e308, 1.7e308), (0.0, 5e-324), (0.0, 1e-323)],
)
def test_a_range_too_wide_or_narrow_for_its_bins_has_one_bin(low, high):
    """A range whose bins' width overflows or underflows gets one bin.

    numpy refuses it ("Too many bins for data range"); here the column gets
    one bin from its minimum to its maximum, holding every finite value.
    """
    connection().execute(
        f"CREATE TABLE r AS SELECT * FROM (VALUES ({low!r}::DOUBLE), "
        f"({high!r}::DOUBLE), (NULL)) v(x)"
    )
    assert sq.explore.histogram("r", bins=10).fetchall() == [("x", 0, low, high, 2)]


def test_a_subnormal_width_is_binned_as_numpy_bins_it():
    """A width that is small but not zero is binned as numpy bins it."""
    values = [0.0, 1e-310, 3e-311]
    rows = sq.explore.histogram(pd.DataFrame({"x": values}), bins=10).fetchall()
    counts, edges = np.histogram(values, bins=10)
    assert [r[4] for r in rows] == counts.tolist()
    assert [r[2] for r in rows] == edges[:-1].tolist()
