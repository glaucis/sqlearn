"""Tests of the relation helper the table and curve metrics share."""

import duckdb

from sqlearn.metrics._relations import SOURCE, select


def test_select_runs_on_the_relations_own_connection():
    """The result joins with the relation: it never moves to another connection."""
    con = duckdb.connect()
    rel = con.sql("SELECT 1 AS a")
    got = select(rel, f"SELECT a + 1 AS b FROM {SOURCE}")
    assert got.fetchall() == [(2,)]
    assert got.set_alias("g").join(rel.set_alias("r"), "1=1").fetchall() == [(2, 1)]
