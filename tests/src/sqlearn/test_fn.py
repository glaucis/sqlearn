"""Tests of the column functions."""

import duckdb
import pytest

import sqlearn as sq
from sqlearn._config import connection

A = duckdb.ColumnExpression("a")


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (lambda: sq.fn.ln(A), 'ln("a")'),
        (lambda: sq.fn.log10(A), 'log10("a")'),
        (lambda: sq.fn.exp(A), 'exp("a")'),
        (lambda: sq.fn.sqrt(A), 'sqrt("a")'),
        (lambda: sq.fn.abs(A), 'abs("a")'),
        (lambda: sq.fn.least(A, 10), 'least("a", 10)'),
        (lambda: sq.fn.greatest(A, 0), 'greatest("a", 0)'),
        (lambda: sq.fn.lower(A), 'lower("a")'),
        (lambda: sq.fn.upper(A), 'upper("a")'),
        (lambda: sq.fn.coalesce(A, 0), 'COALESCE("a", 0)'),
    ],
)
def test_functions_build_the_expression(build, expected):
    """Each function builds its DuckDB call; plain values become constants."""
    assert str(build()) == expected


def test_functions_compute():
    """The expressions give the values DuckDB computes."""
    rel = connection().sql("SELECT * FROM (VALUES (4.0, 'Ab'), (NULL, 'cD')) t(a, s)")
    s = duckdb.ColumnExpression("s")
    out = rel.select(
        sq.fn.sqrt(A), sq.fn.least(A, 3), sq.fn.coalesce(A, 7), sq.fn.upper(s)
    ).fetchall()
    assert out == [(2.0, 3.0, 4.0, "AB"), (None, 3.0, 7.0, "CD")]


def test_const_and_is_missing_are_here():
    """`const` and `is_missing` live in the group."""
    assert str(sq.fn.const(3)) == "3"
    rel = connection().sql("SELECT * FROM (VALUES (1.0), (NULL)) t(a)")
    assert rel.select(sq.fn.is_missing(A)).fetchall() == [(False,), (True,)]
