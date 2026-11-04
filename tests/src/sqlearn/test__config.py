"""Tests of the global configuration."""

import duckdb

from sqlearn import _config


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
