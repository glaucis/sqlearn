"""Tests of the label checks shared by the label metrics."""

import duckdb
import pytest

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn.metrics._labels import check_labels, check_labels_with


def test_check_labels_returns_each_columns_type():
    """check_labels returns the DuckDB type name of each column."""
    con = connection()
    ok = con.sql("SELECT 1 AS y, 2.0 AS p")
    assert check_labels("accuracy", ok, "y", "p") == {
        "y": "INTEGER",
        "p": "DECIMAL(2,1)",
    }
    mixed = con.sql("SELECT 1 AS y, 'a' AS p")
    with pytest.raises(SqlearnError, match=r"holds number labels"):
        check_labels("accuracy", mixed, "y", "p")


def test_a_duckdb_error_from_an_extra_aggregate_passes_through():
    """Only a comparison failure is reworded; another DuckDB error is not."""
    con = connection()
    rel = con.sql("SELECT 1 AS y, 1 AS p")
    boom = duckdb.FunctionExpression("error", duckdb.ConstantExpression("boom"))
    with pytest.raises(duckdb.InvalidInputException, match="boom"):
        check_labels_with("accuracy", rel, "y", "p", [boom])


def test_an_incomparable_pair_names_duckdb_s_first_line_only():
    """DuckDB's reason is kept, its SQL and caret line are not."""
    con = connection()
    rel = con.sql("SELECT DATE '2020-01-01' AS y, 1 AS p")
    with pytest.raises(SqlearnError) as raised:
        check_labels("accuracy", rel, "y", "p")
    text = str(raised.value)
    assert "Conversion Error" in text
    assert "LINE" not in text
    assert "^" not in text
    assert "\n" not in text
    assert "Fix: cast one" in text


def test_a_type_neither_text_nor_number_is_named_as_it_is():
    """A UUID against text is named a UUID label, not a number label."""
    con = connection()
    rel = con.sql("SELECT gen_random_uuid() AS y, 'a' AS p")
    with pytest.raises(SqlearnError, match=r"holds UUID labels") as raised:
        check_labels("accuracy", rel, "y", "p")
    assert "number" not in str(raised.value)
