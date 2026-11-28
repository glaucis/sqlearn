"""The sqlearn extension's SQL tests: DuckDB's own sqllogictest runner, built
by the sqllogic preset (engine/sqllogic), runs every engine/extension/test/sql
file, and the checks rerun it when one changes (validation/_ctest.py)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
BUILD = ENGINE / "build" / "sqllogic"
TESTS = ENGINE / "extension" / "test" / "sql"

# The suffixes DuckDB's runner takes, at any depth (its test_sqllogictest.cpp).
SUFFIXES = (".test", ".test_slow", ".test_coverage")


def _runner_files(root: Path) -> set[Path]:
    """Return every file under `root` the runner would run."""
    return {p for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES}


def _preset() -> dict[str, Any]:
    """Return the sqllogic configure preset."""
    data = json.loads((ENGINE / "CMakePresets.json").read_text())
    return next(p for p in data["configurePresets"] if p["name"] == "sqllogic")


def _ctest_entry() -> dict[str, Any]:
    """Return the CTest entry of the sqllogic build, skipping before it exists."""
    if not (BUILD / "CTestTestfile.cmake").exists():
        pytest.skip("no sqllogic build here yet: just test-sql makes one")
    listing = subprocess.run(
        ["ctest", "--test-dir", str(BUILD), "--show-only=json-v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tests = json.loads(listing)["tests"]
    assert [t["name"] for t in tests] == ["sqllogic"]
    entry: dict[str, Any] = tests[0]
    return entry


def _property(entry: dict[str, Any], name: str) -> list[str]:
    """Return the values of the CTest property `name`, empty without it."""
    for prop in entry.get("properties", []):
        if prop["name"] == name:
            value = prop["value"]
            return [str(v) for v in (value if isinstance(value, list) else [value])]
    return []


def test_the_sqllogic_preset_builds_the_sql_tests_alone() -> None:
    """The preset builds engine/sqllogic, not the groups or the wheel's module,
    with the wheel's release flags for our sources."""
    preset = _preset()
    assert "inherits" not in preset
    assert preset["cacheVariables"]["SQ_SQLLOGIC"] == "ON"
    assert preset["cacheVariables"]["SQ_FLAVOR"] == "release"
    assert preset["binaryDir"] == "${sourceDir}/build/${presetName}"


def test_the_extension_carries_an_sql_test() -> None:
    """At least one sqllogictest file, each requiring the extension it tests."""
    files = sorted(_runner_files(TESTS))
    assert files
    for path in files:
        assert "\nrequire sqlearn\n" in f"\n{path.read_text()}", path.name


def test_the_sql_label_runs_only_the_extensions_tests() -> None:
    """DuckDB's runner, labelled sql, reads engine/extension/test/sql and none of
    DuckDB's own suite, fails a skipped `require sqlearn` and an empty match."""
    entry = _ctest_entry()
    assert _property(entry, "LABELS") == ["sql"]
    command = entry["command"]
    assert Path(command[0]).name == "unittest"
    assert command[command.index("--test-dir") + 1] == str(ENGINE / "extension")
    assert command[command.index("--require") + 1] == "sqlearn"
    assert command[-1] == "test/sql/*"
    assert _property(entry, "FAIL_REGULAR_EXPRESSION") == ["No tests ran"]


def test_every_file_under_the_sql_tests_is_part_of_the_labels_identity() -> None:
    """Each file under the tests' directory, a data file a .test reads too, is
    a REQUIRED_FILES entry, which the checks hash, so an edited one reruns the
    label."""
    entry = _ctest_entry()
    required = {Path(p) for p in _property(entry, "REQUIRED_FILES")}
    assert required == {p for p in TESTS.rglob("*") if p.is_file()}


def test_the_test_set_takes_every_file_the_runner_runs(tmp_path: Path) -> None:
    """engine/cmake/sql_tests.cmake lists what the runner runs under a
    directory: .test, .test_slow and .test_coverage files, in subdirectories
    too, and nothing else."""
    names = [
        "a.test",
        "b.test_slow",
        "c.test_coverage",
        "sub/d.test",
        "sub/deeper/e.test_slow",
        "notes.md",
        "sub/data.csv",
    ]
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("require sqlearn\n")
    script = tmp_path / "list.cmake"
    script.write_text(
        f'include("{ENGINE / "cmake" / "sql_tests.cmake"}")\n'
        f'sq_sql_test_files(found "{tmp_path}")\n'
        'foreach(file IN LISTS found)\n  message(STATUS "${file}")\nendforeach()\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], check=False, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    listed = {
        Path(line.removeprefix("-- "))
        for line in done.stdout.splitlines()
        if line.startswith("-- ")
    }
    assert listed == _runner_files(tmp_path)
    assert tmp_path / "sub" / "deeper" / "e.test_slow" in listed


def test_the_test_data_takes_every_file_under_the_directory(tmp_path: Path) -> None:
    """engine/cmake/sql_tests.cmake lists every file under a directory, at any
    depth and hidden ones too, so a data file a .test reads is hashed."""
    tree = tmp_path / "tree"
    names = [
        "a.test",
        "sub/d.test",
        "sub/deeper/e.test_slow",
        "notes.md",
        "sub/data.csv",
        ".hidden",
    ]
    for name in names:
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text("require sqlearn\n")
    script = tmp_path / "list.cmake"
    script.write_text(
        f'include("{ENGINE / "cmake" / "sql_tests.cmake"}")\n'
        f'sq_sql_test_data(found "{tree}")\n'
        'foreach(file IN LISTS found)\n  message(STATUS "${file}")\nendforeach()\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], check=False, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    listed = {
        Path(line.removeprefix("-- "))
        for line in done.stdout.splitlines()
        if line.startswith("-- ")
    }
    assert listed == {tree / name for name in names}
