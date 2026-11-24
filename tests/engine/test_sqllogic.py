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
    files = sorted(TESTS.glob("*.test"))
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


def test_every_sql_test_file_is_part_of_the_labels_identity() -> None:
    """Each .test file is a REQUIRED_FILES entry, which the checks hash, so an
    edited one reruns the label."""
    entry = _ctest_entry()
    required = {Path(p) for p in _property(entry, "REQUIRED_FILES")}
    assert required == set(TESTS.glob("*.test"))
