"""The sqlearn DuckDB extension: in every database, and nothing downloads."""

import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

import sqlearn as sq

VERSION = "SELECT sqlearn_version()"
AUTOINSTALL = "SELECT current_setting('autoinstall_known_extensions')"
REPO = Path(__file__).resolve().parents[2]
DUCKDB = REPO / "engine" / "duckdb-python" / "external" / "duckdb"
# The C extension API version the test extension is built for: the one
# DuckDB's header names by default (duckdb_extension.h).
CAPI = "v1.5.6"


def _user_extension(tmp_path: Path) -> Path:
    """Build tests/engine/data/answer.c as a user would: compiled, then given
    DuckDB's metadata footer (its platform, ABI and API version), unsigned."""
    if shutil.which("cc") is None or shutil.which("cmake") is None:
        pytest.skip("no cc or cmake to build the test extension")
    built = tmp_path / "sqlearn_test.duckdb_extension"
    compile_ = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    compile_ += ["-shared", "-fPIC", "-DDUCKDB_EXTENSION_NAME=sqlearn_test"]
    compile_ += [f"-I{DUCKDB / 'src' / 'include'}"]
    source = Path(__file__).parent / "data" / "answer.c"
    subprocess.run([*compile_, str(source), "-o", str(built)], check=True)
    platform = tmp_path / "platform"
    row = duckdb.connect().execute("PRAGMA platform").fetchone()
    assert row is not None
    platform.write_text(row[0])
    footer = [
        "-DABI_TYPE=C_STRUCT",
        f"-DEXTENSION={built}",
        f"-DPLATFORM_FILE={platform}",
        f"-DVERSION_FIELD={CAPI}",
        "-DEXTENSION_VERSION=v0.0.1",
        f"-DNULL_FILE={DUCKDB / 'scripts' / 'null.txt'}",
        "-P",
        str(DUCKDB / "scripts" / "append_metadata.cmake"),
    ]
    subprocess.run(["cmake", *footer], check=True)
    return built


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
    """autoinstall_known_extensions is false on a new connection and on the
    default one."""
    assert duckdb.connect().execute(AUTOINSTALL).fetchone() == (False,)
    default = duckdb.sql(AUTOINSTALL)
    assert default is not None
    assert default.fetchall() == [(False,)]


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


def test_an_extension_the_user_installs_loads(tmp_path):
    """INSTALL of an extension file the user has, then LOAD, works in
    sqlearn's DuckDB: its function answers, DuckDB records it as installed
    from the user's path, and nothing downloads. Built here, it is not
    signed by DuckDB, so the user allows unsigned extensions."""
    built = _user_extension(tmp_path)
    con = duckdb.connect(
        config={
            "allow_unsigned_extensions": True,
            "extension_directory": str(tmp_path / "extensions"),
        }
    )
    con.execute(f"INSTALL '{built}'")
    con.execute("LOAD sqlearn_test")
    assert con.execute("SELECT sqlearn_test_answer()").fetchall() == [(42,)]
    state = con.execute(
        "SELECT loaded, installed, install_mode FROM duckdb_extensions()"
        " WHERE extension_name = 'sqlearn_test'"
    ).fetchall()
    assert state == [(True, True, "CUSTOM_PATH")]
    assert con.execute(AUTOINSTALL).fetchone() == (False,)


def test_an_unsigned_extension_is_refused_unless_the_user_allows_it(tmp_path):
    """By default INSTALL refuses an extension DuckDB did not sign: sqlearn
    keeps DuckDB's default, and the user opts in (ADR 0046)."""
    built = _user_extension(tmp_path)
    con = duckdb.connect(config={"extension_directory": str(tmp_path / "extensions")})
    with pytest.raises(duckdb.IOException, match="valid signature"):
        con.execute(f"INSTALL '{built}'")
