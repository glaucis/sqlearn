"""The sqlearn DuckDB extension: in every database, and nothing downloads."""

import duckdb
import pytest

import sqlearn as sq

VERSION = "SELECT sqlearn_version()"
AUTOINSTALL = "SELECT current_setting('autoinstall_known_extensions')"


def test_every_database_has_the_sqlearn_extension(tmp_path):
    """New, file and default databases answer sqlearn_version() with no LOAD."""
    line = (sq.version(),)
    assert duckdb.connect().execute(VERSION).fetchone() == line
    assert duckdb.connect(str(tmp_path / "a.db")).execute(VERSION).fetchone() == line
    default = duckdb.sql(VERSION)
    assert default is not None
    assert default.fetchall() == [line]
    rows = (
        duckdb.connect()
        .execute(
            "SELECT loaded, install_mode FROM duckdb_extensions()"
            " WHERE extension_name = 'sqlearn'"
        )
        .fetchall()
    )
    assert rows == [(True, "STATICALLY_LINKED")]


def test_nothing_downloads_by_itself():
    """autoinstall_known_extensions is false on a new connection."""
    assert duckdb.connect().execute(AUTOINSTALL).fetchone() == (False,)


def test_a_user_who_asks_for_downloads_keeps_them():
    """True at open, or SET later, stays true."""
    asked = duckdb.connect(config={"autoinstall_known_extensions": True})
    assert asked.execute(AUTOINSTALL).fetchone() == (True,)
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = true")
    assert con.execute(AUTOINSTALL).fetchone() == (True,)


def test_a_user_who_turns_downloads_off_keeps_that():
    """False at open is read as false, the user's choice and the default alike."""
    con = duckdb.connect(config={"autoinstall_known_extensions": False})
    assert con.execute(AUTOINSTALL).fetchone() == (False,)


def test_a_missing_local_extension_fails_at_its_path_and_nothing_downloads(tmp_path):
    """LOAD of an extension not in the user's extension directory fails naming
    that directory, and downloads nothing."""
    con = duckdb.connect(config={"extension_directory": str(tmp_path)})
    with pytest.raises(duckdb.IOException) as info:
        con.execute("LOAD spatial")
    message = str(info.value)
    assert str(tmp_path) in message
    assert "http" not in message.lower()
