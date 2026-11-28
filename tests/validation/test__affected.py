"""What ``just affected`` says: for each check, whether it would run and why."""

import json
import subprocess
import sys

import pytest

from validation import _affected, _checks, _ctest, _pytest_sets
from validation._affected import Verdict
from validation._checks import Step, Task, why

TOOL = """\
import json, pathlib, sys
with open(pathlib.Path(__file__).parent / "calls.log", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
"""

SETTINGS_CHANGED = "its settings, tools or the C++ module changed"


def _table(tool):
    """A stand-in table: one whole task and one per-file task."""
    command = (sys.executable, str(tool))
    return {
        "whole": Task(
            name="whole",
            inputs=("*.py",),
            config=("settings.toml",),
            steps=(Step((*command, "whole")),),
            per_file=False,
        ),
        "lint": Task(
            name="lint",
            inputs=("*.py",),
            config=("settings.toml",),
            steps=(Step((*command, "lint")),),
            per_file=True,
        ),
    }


def _git(root, *args):
    """Run git in `root`."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A committed scratch repository of two Python files and a settings file."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("a = 1\n")
    (root / "b.py").write_text("b = 2\n")
    (root / "settings.toml").write_text("line-length = 88\n")
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start")
    tool = tmp_path / "tool.py"
    tool.write_text(TOOL)
    monkeypatch.setattr(_checks, "TASKS", _table(tool))
    return root


def _calls(root):
    """Return and forget the tool's calls since the last look."""
    log = root.parent / "calls.log"
    if not log.exists():
        return []
    lines = log.read_text().splitlines()
    log.unlink()
    return [json.loads(line) for line in lines]


def _records(root):
    """Return each file of the records' directory with its bytes."""
    directory = _checks.record_dir(root)
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*"))}


@pytest.mark.parametrize("name", ["whole", "lint"])
def test_an_unchanged_tree_runs_nothing(scratch, name):
    """After a passed run and no edit, the task would not run."""
    assert _checks.run(name, scratch) == 0
    assert why(_checks.TASKS[name], scratch) == []


@pytest.mark.parametrize("name", ["whole", "lint"])
def test_an_edited_file_is_named(scratch, name):
    """An edited input is named as changed."""
    assert _checks.run(name, scratch) == 0
    (scratch / "a.py").write_text("a = 10\n")
    assert why(_checks.TASKS[name], scratch) == ["a.py: changed"]


@pytest.mark.parametrize("name", ["whole", "lint"])
def test_a_tree_with_no_records_says_never_passed_here(scratch, name):
    """A task with no record at all has never passed here."""
    assert why(_checks.TASKS[name], scratch) == ["never passed here"]


@pytest.mark.parametrize("name", ["whole", "lint"])
def test_a_settings_change_is_reported_as_such(scratch, name):
    """An edited settings file is named as the settings, not file by file."""
    assert _checks.run(name, scratch) == 0
    (scratch / "settings.toml").write_text("line-length = 100\n")
    assert why(_checks.TASKS[name], scratch) == [SETTINGS_CHANGED]


def test_a_whole_task_names_added_and_removed_files(scratch):
    """A file added and one removed are each named, sorted by path."""
    assert _checks.run("whole", scratch) == 0
    (scratch / "c.py").write_text("c = 3\n")
    (scratch / "b.py").unlink()
    assert why(_checks.TASKS["whole"], scratch) == ["b.py: removed", "c.py: added"]


def test_a_new_file_of_a_per_file_task_is_named_as_added(scratch):
    """A file no record ever held is added, not changed."""
    assert _checks.run("lint", scratch) == 0
    (scratch / "c.py").write_text("c = 3\n")
    assert why(_checks.TASKS["lint"], scratch) == ["c.py: added"]


def test_an_old_record_without_files_says_its_inputs_changed(scratch):
    """A whole task's record from before files were kept still reads."""
    task = _checks.TASKS["whole"]
    directory = _checks.record_dir(scratch)
    _checks.save(
        directory,
        "whole",
        _checks.Record(
            digest="an older digest", config=_checks._config(task, scratch), files={}
        ),
    )
    assert why(task, scratch) == ["its inputs changed"]


def test_the_report_runs_nothing(scratch, monkeypatch):
    """The report gives every check's verdict, writes no record, starts no step."""
    asked = []

    def ctest_due(preset, root):
        asked.append(("ctest", preset, root))
        return {"core": [], "raw": ["its test program, data or command changed"]}

    def pytest_due(root):
        asked.append(("pytest", root))
        return {"tooling": ["never passed here"]}

    monkeypatch.setattr(_ctest, "due", ctest_due)
    monkeypatch.setattr(_pytest_sets, "due", pytest_due)
    tasks = dict(_checks.TASKS)
    tasks["test"] = Task(
        name="test",
        inputs=("*.py",),
        config=("settings.toml",),
        steps=tasks["whole"].steps,
        per_file=False,
    )
    monkeypatch.setattr(_checks, "TASKS", tasks)
    assert _checks.run("whole", scratch) == 0
    assert _checks.run("lint", scratch) == 0
    (scratch / "a.py").write_text("a = 10\n")
    _calls(scratch)
    before = _records(scratch)
    verdicts = _affected.report(scratch)
    assert verdicts == [
        Verdict(check="whole", runs=True, reasons=("a.py: changed",)),
        Verdict(check="lint", runs=True, reasons=("a.py: changed",)),
        Verdict(check="test: core", runs=False, reasons=()),
        Verdict(
            check="test: raw",
            runs=True,
            reasons=("its test program, data or command changed",),
        ),
        Verdict(check="test: tooling", runs=True, reasons=("never passed here",)),
    ]
    assert asked == [("ctest", "dev", scratch), ("pytest", scratch)]
    assert _calls(scratch) == []
    assert _records(scratch) == before


def test_the_printout_gives_each_check_then_its_reasons(monkeypatch, capsys):
    """One line per check, runs or unchanged, each reason indented by two."""
    monkeypatch.setattr(
        _affected,
        "report",
        lambda root: [
            Verdict(check="format", runs=False, reasons=()),
            Verdict(check="lint", runs=True, reasons=("a.py: changed", "b.md: added")),
        ],
    )
    assert _affected.cli([]) == 0
    assert capsys.readouterr().out == (
        "format: unchanged\nlint: runs\n  a.py: changed\n  b.md: added\n"
    )


def test_what_the_checks_print_goes_to_standard_error(monkeypatch, capsys):
    """Only the verdicts reach standard output; the checks' messages do not."""

    def loud_why(task, root):
        print("why: a message")  # noqa: T201
        return []

    def loud_pytest_due(root):
        print("the C++ groups are unreadable")  # noqa: T201
        return {"tooling": []}

    monkeypatch.setattr(_checks, "TASKS", {"format": None, "test": None})
    monkeypatch.setattr(_checks, "why", loud_why)
    monkeypatch.setattr(_ctest, "due", lambda preset, root: {"core": []})
    monkeypatch.setattr(_pytest_sets, "due", loud_pytest_due)
    monkeypatch.setattr(_checks, "_root", lambda: "root")
    assert _affected.cli([]) == 0
    out, err = capsys.readouterr()
    assert out == "format: unchanged\ntest: core: unchanged\ntest: tooling: unchanged\n"
    assert "why: a message" in err
    assert "the C++ groups are unreadable" in err
