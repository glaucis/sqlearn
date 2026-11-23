"""The package's DuckDB is the one built from the submodules, inside sqlearn."""

import importlib.metadata
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _duckdb
import duckdb
import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "engine" / "cmake" / "duckdb_package.cmake"
LINE = '__version__: str = _dist_version("duckdb")'
REFUSAL = (
    "duckdb/_version.py changed upstream: review the substitution in"
    " engine/cmake/duckdb_package.cmake"
)
OFFICIAL = ("core_functions", "json", "parquet", "icu")


def test_duckdb_is_sqlearns_build():
    """DuckDB is v2.0.1 from the pinned commit, and sqlearn's own files."""
    assert duckdb.__version__ == "2.0.1"
    assert duckdb.build_info()["duckdb_commit"].startswith("8d78114e90")
    from duckdb import _build_info

    assert duckdb.build_info()["duckdb_version"] == _build_info.DUCKDB_VERSION
    files = importlib.metadata.distribution("sqlearn").files or []
    assert "duckdb/__init__.py" in {f.as_posix() for f in files}
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.distribution("duckdb")


def test_the_official_extensions_are_compiled_in(tmp_path):
    """The four official extensions are linked in and answer without a LOAD."""
    con = duckdb.connect()
    rows = con.execute(
        "SELECT extension_name, loaded, install_mode FROM duckdb_extensions()"
        " WHERE extension_name IN ('core_functions', 'json', 'parquet', 'icu')"
    ).fetchall()
    assert sorted(rows) == sorted((n, True, "STATICALLY_LINKED") for n in OFFICIAL)
    assert con.execute("""SELECT json_extract('{"a":1}', '$.a')""").fetchone() == ("1",)
    path = (tmp_path / "t.parquet").as_posix()
    con.execute(f"COPY (SELECT 42 AS x) TO '{path}' (FORMAT parquet)")
    assert con.execute(f"SELECT x FROM read_parquet('{path}')").fetchall() == [(42,)]
    assert con.execute("SELECT now() AT TIME ZONE 'Europe/London'").fetchone()


def _substitute(tmp_path, text):
    """Run the substitution on a stand-in `_version.py` holding `text`."""
    source = tmp_path / "_version.py"
    source.write_text(text)
    out = tmp_path / "out" / "_version.py"
    script = tmp_path / "run.cmake"
    script.write_text(
        f'include("{PACKAGE.as_posix()}")\n'
        f'sq_duckdb_version_file("{source.as_posix()}" "{out.as_posix()}" "2.0.1")\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=False
    )
    return done, out


@pytest.mark.skipif(shutil.which("cmake") is None, reason="no cmake")
def test_the_version_substitution_refuses_a_changed_file(tmp_path):
    """The one line is replaced; a file without it, or with it twice, fails."""
    done, out = _substitute(tmp_path, f"import x\n{LINE}\nrest = 1\n")
    assert done.returncode == 0, done.stderr
    assert out.read_text() == 'import x\n__version__: str = "2.0.1"\nrest = 1\n'
    for text in ("import x\n", f"{LINE}\n{LINE}\n"):
        done, _ = _substitute(tmp_path, text)
        assert done.returncode != 0
        assert REFUSAL in " ".join(done.stderr.split())


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("otool") is None, reason="macOS only"
)
def test_the_module_and_the_wheel_target_macos_15():
    """The floor is macOS 15 (ADR 0062): the module's minos and the wheel tag."""
    done = subprocess.run(
        ["otool", "-l", _duckdb.__file__], capture_output=True, text=True, check=True
    )
    assert "cmd LC_BUILD_VERSION" in done.stdout, done.stdout[:500]
    build = done.stdout.split("cmd LC_BUILD_VERSION", 1)[1]
    assert re.search(r"^\s*minos 15\.0$", build, re.M), build[:200]
    wheel = importlib.metadata.distribution("sqlearn").read_text("WHEEL") or ""
    tags = re.findall(r"^Tag: (\S+)$", wheel, re.M)
    assert tags, wheel
    assert all(t.endswith("-macosx_15_0_arm64") for t in tags), tags
