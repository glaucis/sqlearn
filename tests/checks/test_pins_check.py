"""`sq_check_pins()` in a scratch copy of `engine/cmake/`, run by `cmake -P`."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = "Fix: git submodule update --init --recursive"
NESTED = (
    "duckdb-python",
    "duckdb-python/external/duckdb",
    "third_party/catch2",
    "third_party/rapidcheck",
    "third_party/nanobench",
    "third_party/cpptrace",
)

pytestmark = pytest.mark.skipif(shutil.which("cmake") is None, reason="no cmake")


def _git(cwd, *args):
    """Run git in `cwd`, returning its output."""
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def scratch(tmp_path):
    """A copy of `engine/cmake/` beside empty submodule directories."""
    engine = tmp_path / "engine"
    shutil.copytree(REPO / "engine" / "cmake", engine / "cmake")
    for path in NESTED:
        (engine / path).mkdir(parents=True)
    (tmp_path / "check.cmake").write_text(
        f'include("{engine}/cmake/pins.cmake")\nsq_check_pins()\n'
    )
    return tmp_path


def _configure(root):
    """Run the check script; return the finished process."""
    return subprocess.run(
        ["cmake", "-P", str(root / "check.cmake")], capture_output=True, text=True
    )


def _repin(root):
    """Make each submodule path a repository, and pin its commit in the copy."""
    pins = root / "engine" / "cmake" / "pins.cmake"
    text = pins.read_text()
    names = {
        "duckdb-python": "SQ_DUCKDB_PYTHON_COMMIT",
        "duckdb-python/external/duckdb": "SQ_DUCKDB_COMMIT",
        "third_party/catch2": "SQ_CATCH2_COMMIT",
        "third_party/rapidcheck": "SQ_RAPIDCHECK_COMMIT",
        "third_party/nanobench": "SQ_NANOBENCH_COMMIT",
        "third_party/cpptrace": "SQ_CPPTRACE_COMMIT",
    }
    for path in NESTED:
        directory = root / "engine" / path
        _git(directory, "init", "-q")
        _git(directory, "commit", "-q", "--allow-empty", "-m", "x")
        commit = _git(directory, "rev-parse", "HEAD")
        text = re.sub(
            rf'set\({names[path]} "[^"]*"\)', f'set({names[path]} "{commit}")', text
        )
    pins.write_text(text)


def test_a_configure_without_submodules_names_the_fix(scratch):
    """An empty submodule path fails configure with the line that fixes it."""
    done = _configure(scratch)
    assert done.returncode != 0
    assert FIX in done.stderr


def test_a_configure_with_every_pin_matched_passes(scratch):
    """Each submodule at its pinned commit: configure goes on."""
    _repin(scratch)
    done = _configure(scratch)
    assert done.returncode == 0, done.stderr


def test_a_configure_at_another_commit_names_the_fix(scratch):
    """A submodule moved off its pin fails configure, naming it."""
    _repin(scratch)
    catch2 = scratch / "engine" / "third_party" / "catch2"
    _git(catch2, "commit", "-q", "--allow-empty", "-m", "moved")
    done = _configure(scratch)
    assert done.returncode != 0
    assert "engine/third_party/catch2" in done.stderr
    assert FIX in done.stderr


def test_duckdb_checked_out_off_its_pin_inside_duckdb_python_fails_configure(scratch):
    """DuckDB's commit, nested in duckdb-python, is checked as its own: a
    checkout off its pin fails configure even when duckdb-python's gitlink,
    the one the checks' digests read, is unchanged."""
    _repin(scratch)
    duckdb = scratch / "engine" / "duckdb-python" / "external" / "duckdb"
    _git(duckdb, "commit", "-q", "--allow-empty", "-m", "moved")
    done = _configure(scratch)
    assert done.returncode != 0
    assert "engine/duckdb-python/external/duckdb" in done.stderr
    assert FIX in done.stderr
