"""Tests of the expression helpers."""

import duckdb

import sqlearn as sq


def test_printed_sql_of_each_form():
    """Each expression form prints as the DuckDB SQL the compositor relies on."""
    x = duckdb.ColumnExpression("age")
    assert str(sq.avg(x)) == 'avg("age")'
    assert str(sq.stddev_pop(x)) == 'stddev_pop("age")'
    assert str(sq.median(x)) == 'median("age")'
    assert str(sq.count(x)) == 'count("age")'
    assert str(sq.distinct_values(x)) == 'list_sort(list_distinct(list("age")))'
    assert str(sq.const(float("nan"))) == "'NaN'::DOUBLE"
    assert str(duckdb.ColumnExpression("l03_scale", "v0")) == '"l03_scale"."v0"'


def test_is_missing_catches_null_and_nan():
    """`is_missing` is true for NULL and for NaN, false otherwise."""
    con = duckdb.connect()
    rel = con.sql("SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE)) t(a)")
    out = rel.select(sq.is_missing(duckdb.ColumnExpression("a"))).fetchall()
    assert out == [(False,), (True,), (True,)]


def test_quote_escapes_quotes_and_reserved_words():
    """quote() makes any name a safe identifier."""
    assert sq._expr.quote('a"b') == '"a""b"'
    assert sq._expr.quote("order") == '"order"'
