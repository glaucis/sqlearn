"""Tests of the helpers the exploration functions share."""

import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._inputs import read
from sqlearn.errors import SqlearnError
from sqlearn.explore._common import answer, columns, missing_sql


def source(sql="SELECT 1 AS a, 'x' AS b, 2.5 AS c"):
    """Return `sql` read as a source."""
    return read(connection().sql(sql))


def test_no_cols_takes_every_column():
    """No cols takes every column."""
    assert columns(source(), None, function="profile") == ["a", "b", "c"]


def test_names_come_back_in_schema_order():
    """Names come back in schema order."""
    assert columns(source(), ["c", "a"], function="profile") == ["a", "c"]


def test_a_selector_choosing_nothing_is_empty():
    """A selector choosing nothing is empty."""
    assert (
        columns(source(), sq.cols.numeric() - sq.cols.numeric(), function="profile")
        == []
    )


def test_an_absent_name_is_refused_with_the_columns_listed():
    """An absent name is refused with the columns listed."""
    with pytest.raises(SqlearnError, match=r"cols='z'.*Fix: pass one of 'a', 'b'"):
        columns(source(), "z", function="profile")


def test_the_listed_names_stop_at_ten():
    """The listed names stop at ten."""
    sql = "SELECT " + ", ".join(f"1 AS c{i}" for i in range(12))
    with pytest.raises(SqlearnError, match=r"'c9', …\."):
        columns(source(sql), "z", function="profile")


def test_answer_is_a_table_that_survives_its_source():
    """Answer is a table that survives its source."""
    connection().execute("CREATE TABLE s AS SELECT 7 AS v")
    result = answer("SELECT v FROM s")
    connection().execute("DROP TABLE s")
    assert result.fetchall() == [(7,)]


def test_missing_sql_counts_nan_only_for_floats():
    """Missing sql counts nan only for floats."""
    con = connection()
    con.execute(
        "CREATE TABLE m AS SELECT 'NaN'::DOUBLE AS d, 'NaN'::FLOAT AS f, 1 AS i"
    )
    types = dict(source("SELECT * FROM m").schema)
    for name in ("d", "f"):
        assert con.sql(
            f"SELECT {missing_sql(name, types[name])} FROM m"
        ).fetchall() == [(True,)]
    assert con.sql(f"SELECT {missing_sql('i', types['i'])} FROM m").fetchall() == [
        (False,)
    ]
