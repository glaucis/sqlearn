"""Tests of the expression helpers."""

import duckdb
import pytest

import sqlearn as sq

NAN = float("nan")


def test_printed_sql_of_each_form():
    """Each expression form prints as the DuckDB SQL the compositor relies on."""
    x = duckdb.ColumnExpression("age")
    assert str(sq.avg(x)) == 'favg("age")'
    assert str(sq.stddev_pop(x)) == 'stddev_pop("age")'
    assert str(sq.median(x)) == '__sqlearn_median("age")'
    assert str(sq.count(x)) == 'count("age")'
    assert (
        str(sq.distinct_values(x))
        == 'COALESCE(list_sort(map_keys(histogram("age"))), [])'
    )
    assert str(sq.fn.const(float("nan"))) == "'NaN'::DOUBLE"
    assert str(duckdb.ColumnExpression("l03_scale", "v0")) == '"l03_scale"."v0"'


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        ("('b'), ('a'), (NULL), ('b'), ('NULL')", ["NULL", "a", "b"]),
        ("(2.0), ('NaN'::DOUBLE), (-0.0), (0.0), ('NaN'::DOUBLE)", [0.0, 2.0, NAN]),
        ("(NULL::VARCHAR)", []),
    ],
)
def test_distinct_values_are_sorted_without_null(rows, want):
    """Each value once, sorted; NULL is not a value, NaN is one value."""
    con = duckdb.connect()
    rel = con.sql(f"SELECT * FROM (VALUES {rows}) t(x)")
    got = rel.aggregate([sq.distinct_values(duckdb.ColumnExpression("x"))])
    assert str(got.fetchall()) == str([(want,)])


def test_distinct_values_of_no_rows_is_empty():
    """No rows, no values: an empty list, not NULL."""
    rel = duckdb.connect().sql("SELECT 'a' AS x WHERE false")
    got = rel.aggregate([sq.distinct_values(duckdb.ColumnExpression("x"))])
    assert got.fetchall() == [([],)]


def test_distinct_values_need_memory_for_the_values_not_the_rows():
    """Five million rows of three categories are learned within 16 MB.

    Collecting every row into a list first (``list(x)``) needs about 80 MB
    here and fails.
    """
    con = duckdb.connect()
    con.execute("SET memory_limit = '16MB'")
    con.execute("SET threads = 1")
    rel = con.sql("SELECT (i % 3)::VARCHAR AS x FROM range(5000000) t(i)")
    got = rel.aggregate([sq.distinct_values(duckdb.ColumnExpression("x"))])
    assert got.fetchall() == [(["0", "1", "2"],)]
    with pytest.raises(duckdb.OutOfMemoryException):
        rel.aggregate("list(x)").fetchall()


def test_is_missing_catches_null_and_nan():
    """`is_missing` is true for NULL and for NaN, false otherwise."""
    con = duckdb.connect()
    rel = con.sql("SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE)) t(a)")
    out = rel.select(sq.fn.is_missing(duckdb.ColumnExpression("a"))).fetchall()
    assert out == [(False,), (True,), (True,)]


def test_quote_escapes_quotes_and_reserved_words():
    """quote() makes any name a safe identifier."""
    assert sq._expr.quote('a"b') == '"a""b"'
    assert sq._expr.quote("order") == '"order"'
