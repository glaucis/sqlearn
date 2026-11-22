"""Tests of the recipes that pick the tests a change affects, on scratch projects."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JUSTFILE = REPO / "justfile"
NO_TESTS_RAN = (
    0  # with xdist; plain pytest exits 5, which the recipe also counts as success
)


def just(*args):
    """Run just on the repository's justfile and return its stdout."""
    done = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def make_project(root):
    """Write the scratch project: two modules, a test for each, a conftest."""
    (root / "a.py").write_text("def one():\n    return 1\n")
    (root / "b.py").write_text("def two():\n    return 2\n")
    (root / "test_a.py").write_text(
        "from a import one\n\n\ndef test_a():\n    assert one() == 1\n"
    )
    (root / "test_b.py").write_text(
        "from b import two\n\n\ndef test_b():\n    assert two() == 2\n"
    )
    (root / "conftest.py").write_text("")
    (root / "uv.lock").write_text("lock\n")


def run_affected(root):
    """Run pytest as `just test` does, on the scratch project; return the process."""
    flags = just("--evaluate", "affected").split()
    env = just("test-env", str(root))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *flags,
            f"--testmon-env='{env}'",
            f"--rootdir={root}",
            "-p",
            "no:cacheprovider",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def project(tmp_path):
    """A scratch project whose first run has already filled testmon's data."""
    make_project(tmp_path)
    first = run_affected(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "2 passed" in first.stdout
    return tmp_path


def test_a_one_line_change_reruns_only_its_tests(project):
    """Editing a.py must rerun a's test and leave b's alone, or the saving is lost."""
    (project / "a.py").write_text("def one():\n    return 1 + 0\n")
    second = run_affected(project)
    assert "1 passed" in second.stdout, second.stdout


def test_nothing_changed_runs_nothing_and_succeeds(project):
    """With no change nothing is selected and the run still succeeds."""
    second = run_affected(project)
    assert second.returncode == NO_TESTS_RAN, second.stdout
    assert "no tests ran" in second.stdout


def test_a_markdown_change_runs_nothing(project):
    """A new README.md is not code, so it must not rerun any test."""
    (project / "README.md").write_text("# notes\n")
    second = run_affected(project)
    assert second.returncode == NO_TESTS_RAN, second.stdout
    assert "no tests ran" in second.stdout


@pytest.mark.parametrize(
    "declared", ["uv.lock", "conftest.py", "devdata/data/table.csv"]
)
def test_a_declared_dependency_reruns_every_test(project, declared):
    """A change to a declared file must change test-env and rerun every test."""
    before = just("test-env", str(project))
    path = project / declared
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.read_text() + "# changed\n" if path.exists() else "x\n")
    assert just("test-env", str(project)) != before
    second = run_affected(project)
    assert "2 passed" in second.stdout, second.stdout


def test_test_env_is_the_same_twice(tmp_path):
    """The digest must be stable, or every run would count as a change."""
    make_project(tmp_path)
    first = just("test-env", str(tmp_path))
    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert just("test-env", str(tmp_path)) == first
