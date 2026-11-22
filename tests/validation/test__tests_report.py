"""The pytest plugin that writes tests.json: each test's area."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from validation._tests_report import area


@pytest.mark.parametrize(
    ("nodeid", "expected"),
    [
        (
            "tests/src/sqlearn/preprocessing/test_scale.py::test_x[a]",
            "sqlearn/preprocessing/scale",
        ),
        ("tests/src/sqlearn/test__compose.py::test_y", "sqlearn/_compose"),
        ("tests/validation/test__cases.py::test_z", "validation/_cases"),
        ("tests/test_environment.py::test_w", "environment"),
    ],
)
def test_area_is_the_mirrored_module(nodeid, expected):
    """A test's area is the module its file mirrors, without tests/ and src/."""
    assert area(nodeid) == expected


ROOT = Path(__file__).resolve().parents[2]


def _scratch(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a scratch project holding `files`, with the plugin's rootdir at it."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers = slow: slow\naddopts = -p no:cacheprovider -p no:testmon\n"
    )
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    return tmp_path


def _run(project: Path, *args: str) -> dict[str, str]:
    """Run pytest in `project` with the plugin; return outcome by node id."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "validation._tests_report", *args],
        cwd=project,
        env=env,
        check=False,
        capture_output=True,
    )
    return {t["name"]: t["outcome"] for t in _read(project)}


def _read(project: Path) -> list[dict[str, str]]:
    path = project / "validation" / "tests.json"
    tests: list[dict[str, str]] = (
        json.loads(path.read_text())["tests"] if path.exists() else []
    )
    return tests


def _seed(project: Path, entries: dict[str, str]) -> None:
    """Write a tests.json holding `entries` (node id to outcome)."""
    tests = [
        {"area": "a", "name": n, "outcome": o, "tier": "fast"}
        for n, o in entries.items()
    ]
    (project / "validation").mkdir(exist_ok=True)
    (project / "validation" / "tests.json").write_text(json.dumps({"tests": tests}))


def test_a_partial_run_keeps_the_entries_of_tests_not_run(tmp_path):
    """A run collecting only file x leaves the entries of file y as they were."""
    project = _scratch(
        tmp_path,
        {
            "test_x.py": "def test_a():\n    pass\n",
            "test_y.py": "def test_b():\n    pass\n",
        },
    )
    _seed(project, {"test_x.py::test_a": "failed", "test_y.py::test_b": "skipped"})
    assert _run(project, "test_x.py") == {
        "test_x.py::test_a": "passed",
        "test_y.py::test_b": "skipped",
    }


def test_a_deselected_test_keeps_its_outcome(tmp_path):
    """A test collected but deselected keeps the outcome of its last run."""
    project = _scratch(
        tmp_path,
        {"test_x.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"},
    )
    _seed(project, {"test_x.py::test_a": "failed", "test_x.py::test_b": "failed"})
    assert _run(project, "-k", "test_a") == {
        "test_x.py::test_a": "passed",
        "test_x.py::test_b": "failed",
    }


def test_a_test_removed_from_its_file_loses_its_entry(tmp_path):
    """A test no longer in a collected file is dropped from the record."""
    project = _scratch(tmp_path, {"test_x.py": "def test_a():\n    pass\n"})
    _seed(project, {"test_x.py::test_a": "passed", "test_x.py::test_gone": "passed"})
    assert _run(project) == {"test_x.py::test_a": "passed"}


def test_the_entries_of_a_deleted_file_are_dropped(tmp_path):
    """An entry of a file that is no longer there goes, though it was not collected."""
    project = _scratch(tmp_path, {"test_x.py": "def test_a():\n    pass\n"})
    _seed(project, {"test_old.py::test_a": "passed"})
    assert _run(project) == {"test_x.py::test_a": "passed"}


def test_a_parallel_run_writes_the_same_entries_as_a_serial_one(tmp_path):
    """Run with and without -n 2, a suite of slow, failing and passing tests writes equal files."""  # noqa: E501
    body = (
        "import pytest\n\n"
        "@pytest.mark.slow\ndef test_slow():\n    pass\n\n"
        "def test_fails():\n    assert False\n\n"
        "def test_passes():\n    pass\n"
    )
    outcomes = []
    for name, args in [("serial", ()), ("parallel", ("-n", "2"))]:
        (tmp_path / name).mkdir()
        project = _scratch(tmp_path / name, {"test_x.py": body})
        _run(project, "-m", "", *args)
        outcomes.append((project / "validation" / "tests.json").read_text())
    assert outcomes[0] == outcomes[1]
    assert '"failed"' in outcomes[0]
