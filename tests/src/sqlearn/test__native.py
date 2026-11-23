"""sqlearn._native: the engine, loaded from DuckDB's binary at import."""

import importlib
import importlib.machinery
import subprocess
import sys
import textwrap
from pathlib import Path

import _duckdb
import duckdb
import pytest

import sqlearn as sq
from sqlearn import _native

REPO = Path(__file__).resolve().parents[3]
DUCKDB_COMMIT = "8d78114e90"
STUB = "src/sqlearn/_native.pyi"


def test_version_answers_from_cpp():
    """sq.version() names sqlearn, DuckDB and its commit, as the SQL does."""
    line = sq.version()
    assert sq.__version__ in line
    assert f"DuckDB {duckdb.__version__} ({DUCKDB_COMMIT})" in line
    assert duckdb.connect().execute("SELECT sqlearn_version()").fetchone() == (line,)


def test_the_build_identity_is_the_pinned_build():
    """build_identity() holds the five fields describe() is made from."""
    identity = _native.build_identity()
    assert identity["sqlearn_version"] == sq.__version__
    assert identity["duckdb_version"] == duckdb.__version__
    assert identity["duckdb_commit"].startswith(DUCKDB_COMMIT)
    assert len(identity["duckdb_commit"]) == 40
    assert identity["compiler"] and identity["build_type"]
    assert sq.version() == (
        f"sqlearn {identity['sqlearn_version']}, DuckDB {identity['duckdb_version']}"
        f" ({identity['duckdb_commit'][:10]}), {identity['compiler']},"
        f" {identity['build_type']}"
    )


def test_the_engine_is_in_duckdbs_binary():
    """load() takes the engine from _duckdb's own file, under sqlearn's name."""
    module = _native.load(_duckdb.__file__)
    assert module.__name__ == "sqlearn._native"
    assert module.__file__ == _duckdb.__file__
    assert _native.describe() == module.describe()


def test_a_file_without_the_engine_is_refused():
    """load() of another extension module raises ImportError with Why and Fix."""
    path = importlib.import_module("numpy._core._multiarray_umath").__file__
    assert path is not None
    with pytest.raises(ImportError, match="Why: the duckdb module is not") as info:
        _native.load(path)
    message = str(info.value)
    assert f"({path})" in message
    assert "Fix: uv sync --reinstall-package sqlearn" in message
    assert "environment of its own" in message
    assert isinstance(info.value.__cause__, ImportError)


def test_the_official_duckdb_is_refused():
    """import sqlearn, with a _duckdb that is not sqlearn's, exits with Why/Fix."""
    script = textwrap.dedent(
        """
        import sys, types
        import numpy._core._multiarray_umath as other
        fake = types.ModuleType("_duckdb")
        fake.__file__ = other.__file__
        sys.modules["_duckdb"] = fake
        import sqlearn
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert done.returncode not in (0, -11, -6), done.stderr
    assert done.returncode == 1, done.stderr
    assert "ImportError" in done.stderr
    assert "Why: the duckdb module is not sqlearn's build" in done.stderr
    assert "Fix: uv sync --reinstall-package sqlearn" in done.stderr


def test_the_stubs_match_the_module(tmp_path):
    """nanobind's stubgen, formatted by ruff, gives the committed _native.pyi.

    What ``just check-stubs`` runs, here on the running interpreter with no
    uv, so it never syncs or rebuilds the environment the tests run in.
    """
    raw = tmp_path / "raw.pyi"
    stubgen = ["-m", "nanobind.stubgen", "-q", "-D", "-m", "sqlearn._native"]
    subprocess.run(
        [sys.executable, *stubgen, "-o", str(raw)],
        cwd=REPO,
        check=True,
    )
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


def test_the_module_is_an_extension_module():
    """The engine is native code, loaded by the extension loader."""
    assert isinstance(
        _native.load(_duckdb.__file__).__loader__,
        importlib.machinery.ExtensionFileLoader,
    )
