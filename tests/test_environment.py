"""Tests of the environment as a whole."""

import duckdb
import pytest


def test_duckdb_answers_a_query():
    """The one runtime dependency imports and computes in this environment."""
    assert duckdb.execute("select sum(range) from range(1000)").fetchone() == (499500,)


@pytest.mark.slow
def test_duckdb_spills_a_query_larger_than_its_memory_limit(tmp_path):
    """DuckDB finishes work larger than its memory limit by spilling to disk."""
    query = """
        select count(*), sum(n) from (
            select k, count(*) as n
            from (select i % 10000000 as k from range(20000000) t(i))
            group by k
        )
    """
    con = duckdb.connect()
    con.execute("set memory_limit = '64MB'")
    con.execute("set threads = 1")
    con.execute("set temp_directory = ''")
    with pytest.raises(duckdb.OutOfMemoryException):
        con.execute(query).fetchone()
    con.execute(f"set temp_directory = '{tmp_path}'")
    assert con.execute(query).fetchone() == (10000000, 20000000)
