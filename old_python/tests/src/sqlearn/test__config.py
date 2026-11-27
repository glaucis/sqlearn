"""Tests of the global configuration."""

import duckdb
import pytest

from sqlearn import _config
from sqlearn._memory import duckdb_limit, physical
from sqlearn.errors import SqlearnError


def test_connection_is_opened_once_and_reused():
    """Without a configured connection, one in-memory connection is reused."""
    assert _config.connection() is _config.connection()


def test_set_config_connection_is_used():
    """A configured connection is the one `connection()` returns."""
    con = duckdb.connect()
    _config.set_config(connection=con)
    assert _config.connection() is con
    assert _config.get_config().connection is con


def test_set_config_out_keeps_the_connection():
    """Setting one field leaves the other as it was."""
    con = duckdb.connect()
    _config.set_config(connection=con)
    _config.set_config(out="pandas")
    assert _config.get_config().out == "pandas"
    assert _config.connection() is con


def test_config_is_reset_between_tests():
    """The autouse fixture leaves a fresh config for each test."""
    assert _config.get_config().out is None
    assert _config.get_config().connection is None
    assert _config.get_config().memory is None


def limit(con):
    """Return a connection's memory_limit as DuckDB prints it."""
    return con.sql("SELECT current_setting('memory_limit')").fetchall()[0][0]


def test_memory_is_kept_in_bytes():
    """`memory=` takes bytes or a string DuckDB reads; None is the default."""
    _config.set_config(memory=2_000_000)
    assert _config.get_config().memory == 2_000_000
    _config.set_config(memory="8GB")
    assert _config.get_config().memory == 8 * 10**9
    _config.set_config(memory=None)
    assert _config.get_config().memory is None


@pytest.mark.parametrize("memory", [0, -5, True, 1.5, "lots"])
def test_memory_that_is_not_a_size_is_refused(memory):
    """Not a positive number of bytes nor a size string: refused, naming the forms."""
    with pytest.raises(SqlearnError, match="8GB"):
        _config.set_config(memory=memory)


def test_a_passed_connection_is_never_changed():
    """sqlearn reads a passed connection's limit and never sets it."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '1GB'")
    _config.set_config(connection=con, memory="4GB")
    _config.connection()
    _config.set_config(memory="8GB")
    assert limit(con) == "953.6 MiB"


def test_the_shared_connection_takes_half_the_budget():
    """sqlearn's own connection is opened with half the budget as its limit."""
    _config.set_config(connection=None, memory="4GB")
    assert duckdb_limit(_config.connection()) == pytest.approx(2 * 10**9, rel=0.01)


def test_the_shared_connection_follows_a_new_budget():
    """Changing the budget re-applies the limit on the shared connection (R3)."""
    con = _config.connection()
    _config.set_config(memory="2GB")
    assert duckdb_limit(con) == pytest.approx(10**9, rel=0.01)
    _config.set_config(memory=None)
    assert duckdb_limit(con) == pytest.approx(0.4 * physical(), rel=0.01)
