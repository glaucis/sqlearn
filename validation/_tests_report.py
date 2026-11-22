"""A pytest plugin writing every test's outcome to ``validation/tests.json``.

Loaded with ``-p validation._tests_report`` (``just test``). Each test
is recorded with its name (the node id), its area (the module it tests, as
``sqlearn/preprocessing/scale``), its tier (fast or slow) and its outcome;
no durations, so the file changes only when an outcome does (ADR 0025).
A run merges into the file: tests not run keep their entries.
"""

import json
from pathlib import Path

import pytest

_RESULTS: dict[str, dict[str, str]] = {}
_COLLECTED: set[str] = set()


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


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Note every collected test before a deselection (-k, -m, testmon) removes any."""
    _COLLECTED.update(item.nodeid for item in items)
    output = getattr(config, "workeroutput", None)
    if output is not None:  # an xdist worker hands its list to the controller
        output["collected"] = sorted(_COLLECTED)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object, error: object) -> None:
    """Take the tests an xdist worker collected, deselected ones included."""
    output = getattr(node, "workeroutput", None) or {}
    _COLLECTED.update(output.get("collected", ()))


def _merge(root: Path, old: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return the old entries updated by this run's.

    A collected file's entries are rebuilt from its collected tests: one run
    keeps its new outcome, one deselected keeps its old, one no longer in its
    file goes. A file not collected keeps its entries unless it is gone.
    """
    collected_files = {name.split("::")[0] for name in _COLLECTED}
    merged = dict(_RESULTS)
    for entry in old:
        name = entry["name"]
        file = name.split("::")[0]
        if name in merged:
            continue
        if file in collected_files:
            if name in _COLLECTED:
                merged[name] = entry
        elif (root / file).exists():
            merged[name] = entry
    return [merged[name] for name in sorted(merged)]


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Merge the outcomes into ``validation/tests.json``, sorted by name.

    An xdist worker writes nothing: the controller sees every report.
    """
    if hasattr(session.config, "workerinput") or not _RESULTS:
        return
    # Local: _cases imports sqlearn, which must load after coverage starts.
    from validation import _cases

    root = Path(session.config.rootpath)
    path = root / "validation" / "tests.json"
    old = json.loads(path.read_text())["tests"] if path.exists() else []
    _cases.write_json(path, {"tests": _merge(root, old)})
