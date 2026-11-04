"""A pytest plugin writing every test's outcome to ``validation/tests.json``.

Loaded with ``-p validation._tests_report`` (``just validate``). Each test
is recorded with its name (the node id), its area (the module it tests, as
``sqlearn/preprocessing/scale``), its tier (fast or slow) and its outcome;
no durations, so the file changes only when an outcome does (ADR 0025).
"""

from pathlib import Path

import pytest

from validation import _cases

_RESULTS: dict[str, dict[str, str]] = {}


def area(nodeid: str) -> str:
    """Return the module a test mirrors: ``tests/src/sqlearn/x/test_y.py`` gives ``sqlearn/x/y``."""  # noqa: E501
    path = Path(nodeid.split("::")[0])
    parts = list(path.parent.parts)
    if parts[:1] == ["tests"]:
        parts = parts[1:]
    if parts[:1] == ["src"]:
        parts = parts[1:]
    return "/".join([*parts, path.stem.removeprefix("test_")])


def _outcome(report: pytest.TestReport) -> str | None:
    if hasattr(report, "wasxfail"):
        return "xfailed" if report.skipped else "xpassed"
    if report.when == "call":
        return report.outcome
    if report.failed:
        return "error"
    if report.skipped:
        return "skipped"
    return None


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Note the test's outcome; a failing setup or teardown counts as an error."""
    outcome = _outcome(report)
    if outcome is None:
        return
    entry = _RESULTS.setdefault(
        report.nodeid,
        {
            "name": report.nodeid,
            "area": area(report.nodeid),
            "tier": "slow" if "slow" in report.keywords else "fast",
        },
    )
    if entry.get("outcome") not in {"failed", "error"}:
        entry["outcome"] = outcome


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Write the outcomes, sorted by name, to ``validation/tests.json``."""
    if not _RESULTS:
        return
    tests = [_RESULTS[name] for name in sorted(_RESULTS)]
    path = Path(session.config.rootpath) / "validation" / "tests.json"
    _cases.write_json(path, {"tests": tests})
