"""A user's DuckDB connection crossing into sqlearn's C++ and back."""

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

import sqlearn as sq
from sqlearn._native import count_rows, roundtrip

REPO = Path(__file__).resolve().parents[2]
STUB = "src/sqlearn/_native.pyi"


def test_the_stubs_match_the_engines_module(tmp_path):
    """nanobind's stubgen, formatted by ruff, gives the committed _native.pyi,
    so ty, mypy and editors see the module's functions as they are.

    What ``just check-stubs`` runs, here on the running interpreter with no
    uv, so it never syncs or rebuilds the environment the tests run in.
    """
    raw = tmp_path / "raw.pyi"
    stubgen = ["-m", "nanobind.stubgen", "-q", "-D", "-m", "sqlearn._native"]
    subprocess.run([sys.executable, *stubgen, "-o", str(raw)], cwd=REPO, check=True)
    formatted = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", STUB],
        cwd=REPO,
        input=raw.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    committed = (REPO / STUB).read_text(encoding="utf-8")
    assert formatted == committed, "Fix: just stubs"


@pytest.fixture
def con():
    """A connection holding t, five rows."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM range(5)")
    yield con
    con.close()


def test_a_users_connection_reaches_cpp_and_back(con):
    """count_rows reads the user's table through C++, on it or a cursor."""
    assert count_rows(con, "t") == 5
    assert count_rows(con.cursor(), "t") == 5
    assert roundtrip(con) is con


def test_a_connection_to_another_database_sees_its_own_tables(con):
    """Another database has no t: DuckDB's own catalog error."""
    other = duckdb.connect()
    with pytest.raises(duckdb.CatalogException, match="t"):
        count_rows(other, "t")


def test_a_closed_connection_raises_duckdbs_error(con):
    """A closed connection is DuckDB's ConnectionException, not a crash."""
    con.close()
    with pytest.raises(duckdb.ConnectionException):
        count_rows(con, "t")
    assert duckdb.connect().execute("SELECT 1").fetchone() == (1,)


def test_a_precondition_is_an_internal_error(con):
    """SQ_EXPECTS(!table.empty()) is sq.errors.InternalError with Why and Fix."""
    with pytest.raises(sq.errors.InternalError) as info:
        count_rows(con, "")
    message = str(info.value)
    assert "!table.empty()" in message
    assert "\nWhy: " in message
    assert "\nFix: " in message
    assert "connection.cpp" in message


def test_a_busy_connection_never_crashes(con):
    """An unfinished result on the connection: DuckDB 2.0.1 refuses the count.

    DuckDB's own ResourceInUseException, raised in C++ and passed through its
    translators; the result stays readable and the connection usable.
    """
    busy = con.execute("SELECT * FROM range(10)")
    with pytest.raises(duckdb.ResourceInUseException, match="open result"):
        count_rows(con, "t")
    assert busy.fetchall() == [(i,) for i in range(10)]
    assert count_rows(con, "t") == 5
