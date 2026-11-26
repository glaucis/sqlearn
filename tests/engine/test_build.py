"""The package's DuckDB is the one built from the submodules, inside sqlearn."""

import importlib.metadata
import os
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


STAMP = "engine/.compiler-stamp"


def _stamp(tmp_path, version):
    """Run the real compiler-stamp recipe in `tmp_path` with a c++ that prints
    `version`; return the stamp file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "c++").write_text(f"#!/bin/sh\necho '{version}'\n")
    (bin_dir / "c++").chmod(0o755)
    shutil.copy(REPO / "justfile", tmp_path / "justfile")
    env = {
        **{k: v for k, v in os.environ.items() if k != "CXX"},
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    subprocess.run(
        ["just", "compiler-stamp"], cwd=tmp_path, env=env, check=True, text=True
    )
    return tmp_path / STAMP


def test_a_compiler_change_is_a_cache_key_of_the_build(tmp_path):
    """uv rebuilds the module when the compiler changes: the stamp of its
    identity is one of pyproject's cache keys, git ignores it, and the recipe
    rewrites it only when the compiler changed, since uv keys a file on its
    modification time."""
    import tomllib

    keys = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["uv"][
        "cache-keys"
    ]
    assert {"file": STAMP} in keys
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", STAMP], cwd=REPO, check=False
    )
    assert ignored.returncode == 0
    stamp = _stamp(tmp_path, "clang version 21.0.0")
    assert "clang version 21.0.0" in stamp.read_text()
    before = stamp.stat().st_mtime_ns
    _stamp(tmp_path, "clang version 21.0.0")
    assert stamp.stat().st_mtime_ns == before
    _stamp(tmp_path, "clang version 22.0.0")
    assert "clang version 22.0.0" in stamp.read_text()


@pytest.mark.parametrize("recipe", ["setup", "done", "verify"])
def test_the_compiler_is_stamped_before_anything_builds(recipe):
    """setup, done and verify write the stamp first, so the build they start
    sees a compiler change."""
    justfile = (REPO / "justfile").read_text()
    body = justfile[justfile.index(f"\n{recipe}:") + 1 :]
    end = body.find("\n\n")
    lines = [x.strip() for x in body[: end if end >= 0 else None].splitlines()[1:]]
    skipped = ("#", "set ", "j=(")
    commands = [x for x in lines if x and not x.startswith(skipped)]
    assert "compiler-stamp" in commands[0], commands[:2]
