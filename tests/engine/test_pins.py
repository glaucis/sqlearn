"""The submodules sit at the commits `engine/cmake/pins.cmake` pins."""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PINS = REPO / "engine" / "cmake" / "pins.cmake"

PATHS = {
    "SQ_DUCKDB_PYTHON_COMMIT": "engine/duckdb-python",
    "SQ_CATCH2_COMMIT": "engine/third_party/catch2",
    "SQ_RAPIDCHECK_COMMIT": "engine/third_party/rapidcheck",
    "SQ_NANOBENCH_COMMIT": "engine/third_party/nanobench",
    "SQ_CPPTRACE_COMMIT": "engine/third_party/cpptrace",
}


def _pins() -> dict[str, str]:
    """Return the `set(NAME "value")` lines of pins.cmake."""
    return dict(re.findall(r'^set\((\w+) "([^"]*)"\)', PINS.read_text(), re.M))


def _gitlinks(cwd: Path, *paths: str) -> dict[str, str]:
    """Return the commit each gitlink under `paths` records in `cwd`'s index."""
    out = subprocess.run(
        ["git", "ls-files", "-s", *paths],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    links = {}
    for line in out.splitlines():
        info, name = line.split("\t")
        mode, commit, _ = info.split(" ")
        if mode == "160000":
            links[name] = commit
    return links


def test_each_pin_is_the_submodules_commit():
    """Every submodule's recorded commit is its pin, and each is pinned."""
    pins = _pins()
    links = _gitlinks(REPO, "engine")
    nested = _gitlinks(REPO / "engine" / "duckdb-python", "external/duckdb")
    assert set(links) == set(PATHS.values())
    for name, path in PATHS.items():
        assert pins[name] == links[path], name
    assert pins["SQ_DUCKDB_COMMIT"] == nested["external/duckdb"]


def test_duckdb_python_pins_duckdb_v2_0_1():
    """The DuckDB inside duckdb-python is the v2.0.1 release's commit."""
    nested = _gitlinks(REPO / "engine" / "duckdb-python", "external/duckdb")
    assert pins_tag() == "v2.0.1"
    assert nested["external/duckdb"] == "8d78114e90a53823803660bf821f6073ac87da8c"


def pins_tag() -> str:
    """Return the DuckDB tag pins.cmake names."""
    return _pins()["SQ_DUCKDB_TAG"]


def _submodule(tmp_path: Path) -> tuple[Path, str]:
    """Make a scratch repository standing in for a submodule; return it and
    its commit."""
    repo = tmp_path / "fake"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q")
    (repo / "source.cpp").write_text("int answer() { return 42; }\n")
    git("add", "source.cpp")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    return repo, git("rev-parse", "HEAD")


def _check(tmp_path: Path, repo: Path, pinned: str) -> subprocess.CompletedProcess[str]:
    """Run sq_check_submodule on `repo` in CMake's script mode."""
    script = tmp_path / "check.cmake"
    script.write_text(
        f'include("{PINS.as_posix()}")\n'
        f'sq_check_submodule("{repo.as_posix()}" "engine/fake" "{pinned}")\n'
    )
    return subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=False
    )


def test_a_clean_submodule_at_its_pin_passes(tmp_path):
    """A submodule at its pinned commit with nothing changed passes."""
    repo, commit = _submodule(tmp_path)
    done = _check(tmp_path, repo, commit)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("edit", ["tracked", "untracked"])
def test_a_submodule_with_local_edits_fails_the_configure(tmp_path, edit):
    """A submodule at its pin but with a file edited, or a new file, fails,
    naming the submodule, the file and the fix: submodules are never edited."""
    repo, commit = _submodule(tmp_path)
    if edit == "tracked":
        (repo / "source.cpp").write_text('int answer() { puts("x"); return 42; }\n')
        name = "source.cpp"
    else:
        (repo / "added.cpp").write_text("int more() { return 1; }\n")
        name = "added.cpp"
    done = _check(tmp_path, repo, commit)
    assert done.returncode == 1
    assert "engine/fake has local edits" in done.stderr
    assert name in done.stderr
    assert "Fix:" in done.stderr
    assert "git -C engine/fake" in done.stderr


@pytest.mark.parametrize("name", sorted(PATHS))
def test_a_pin_is_a_full_commit_hash(name):
    """A pin is a 40-digit hash, never a tag or branch that can move."""
    assert re.fullmatch(r"[0-9a-f]{40}", _pins()[name])
