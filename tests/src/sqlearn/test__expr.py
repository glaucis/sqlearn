"""Tests of the expression helpers."""

import duckdb

import sqlearn as sq
from sqlearn._expr import quote


def test_printed_sql_of_each_form():
    """Each expression form prints as the DuckDB SQL the compositor relies on."""
    assert str(sq.fn.const(float("nan"))) == "'NaN'::DOUBLE"
    assert str(duckdb.ColumnExpression("l03_scale", "v0")) == '"l03_scale"."v0"'


def test_is_missing_catches_null_and_nan():
    """`is_missing` is true for NULL and for NaN, false otherwise."""
    con = duckdb.connect()
    rel = con.sql("SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE)) t(a)")
    out = rel.select(sq.fn.is_missing(duckdb.ColumnExpression("a"))).fetchall()
    assert out == [(False,), (True,), (True,)]


def test_quote_escapes_quotes_and_reserved_words():
    """quote() makes any name a safe identifier."""
    assert quote('a"b') == '"a""b"'
    assert quote("order") == '"order"'
