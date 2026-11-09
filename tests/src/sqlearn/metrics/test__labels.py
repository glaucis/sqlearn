"""Tests of the label checks shared by the label metrics."""

import pytest

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn.metrics._labels import check_labels


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
