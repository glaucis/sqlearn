"""Each check's record: the digest of its inputs when it passed, and its reruns."""

import json
import subprocess
import sys

import pytest

from validation import _checks
from validation._checks import Step, Task, changed_files, digest, run

TOOL = """\
import json, pathlib, sys
here = pathlib.Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "edit":
    with open("src/a.py", "a") as source:
        source.write("# edited while the check ran\\n")
if (here / "fail").exists():
    sys.exit(1)
"""


def _table(tool):
    """A stand-in table: one whole task and one per-file task of two steps."""
    command = (sys.executable, str(tool))
    return {
        "whole": Task(
            name="whole",
            inputs=("src", "validation"),
            config=("settings.toml",),
            steps=(Step((*command, "whole")),),
            per_file=False,
        ),
        "edit": Task(
            name="edit",
            inputs=("src",),
            config=("settings.toml",),
            steps=(Step((*command, "edit")),),
            per_file=False,
        ),
        "lint": Task(
            name="lint",
            inputs=("*.py", "*.md"),
            config=("settings.toml",),
            steps=(
                Step((*command, "py"), files=("*.py",)),
                Step((*command, "md"), files=("*.md",)),
            ),
            per_file=True,
        ),
    }


def _git(root, *args):
    """Run git in `root`."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A scratch repository with two Python files, a note and a settings file."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("a = 1\n")
    (root / "src" / "b.py").write_text("b = 2\n")
    (root / "notes.md").write_text("# Notes\n")
    (root / "settings.toml").write_text("line-length = 88\n")
    (root / ".gitignore").write_text("build/\n")
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


def test_a_whole_task_runs_once_then_is_skipped(scratch, capsys):
    """Nothing changed since it passed: the second run runs nothing."""
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]
    assert run("whole", scratch) == 0
    assert _calls(scratch) == []
    assert "whole: unchanged since a passed run" in capsys.readouterr().out


def test_a_changed_input_reruns_a_whole_task(scratch):
    """One changed byte in an input runs the whole task again."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "src" / "a.py").write_text("a = 10\n")
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_a_new_file_reruns_a_whole_task(scratch):
    """A file added under the inputs, not yet tracked, runs it again."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "src" / "c.py").write_text("c = 3\n")
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_a_deleted_file_reruns_a_whole_task(scratch):
    """A tracked file gone from the working tree runs it again, no crash."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "src" / "b.py").unlink()
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_an_ignored_file_changes_nothing(scratch):
    """A git-ignored file under the inputs is no input: nothing reruns."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "src" / "build").mkdir()
    (scratch / "src" / "build" / "out.py").write_text("x = 0\n")
    assert run("whole", scratch) == 0
    assert _calls(scratch) == []


def test_the_checks_outputs_change_nothing(scratch):
    """``tests.json`` and the results files are outputs, not inputs."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "validation" / "sqlearn").mkdir(parents=True)
    (scratch / "validation" / "tests.json").write_text("{}\n")
    (scratch / "validation" / "environment.json").write_text("{}\n")
    (scratch / "validation" / "sqlearn" / "x.results.json").write_text("{}\n")
    assert run("whole", scratch) == 0
    assert _calls(scratch) == []


def test_a_failed_run_records_nothing(scratch):
    """A run that fails leaves no record: the next run runs again."""
    (scratch.parent / "fail").touch()
    assert run("whole", scratch) == 1
    (scratch.parent / "fail").unlink()
    _calls(scratch)
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_an_edit_during_the_run_is_not_recorded(scratch):
    """A file edited while the check ran is checked again on the next run."""
    run("edit", scratch)
    _calls(scratch)
    assert run("edit", scratch) == 0
    assert _calls(scratch) == [["edit"]]


def test_an_edit_undone_after_the_run_is_not_recorded(scratch):
    """The content before an edit during the run was not what passed: it reruns."""
    before = (scratch / "src" / "a.py").read_text()
    run("edit", scratch)
    _calls(scratch)
    (scratch / "src" / "a.py").write_text(before)
    assert run("edit", scratch) == 0
    assert _calls(scratch) == [["edit"]]


def test_a_per_file_task_checks_only_the_changed_files(scratch, capsys):
    """One changed Python file: only it is checked, by the Python step only."""
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py", "src/b.py"], ["md", "notes.md"]]
    (scratch / "src" / "a.py").write_text("a = 10\n")
    assert changed_files(_checks.TASKS["lint"], scratch) == [_checks.Path("src/a.py")]
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py"]]
    assert run("lint", scratch) == 0
    assert _calls(scratch) == []
    assert "lint: unchanged since a passed run" in capsys.readouterr().out


def test_a_per_file_task_checks_a_new_file(scratch):
    """A file added under the inputs is checked, alone."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "src" / "c.py").write_text("c = 3\n")
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/c.py"]]


def test_a_per_file_task_checks_a_file_restored_to_an_earlier_pass(scratch):
    """A file back to content that passed is still unchanged, by any kept record."""
    run("lint", scratch)
    (scratch / "src" / "a.py").write_text("a = 10\n")
    run("lint", scratch)
    (scratch / "src" / "a.py").write_text("a = 1\n")
    _calls(scratch)
    assert run("lint", scratch) == 0
    assert _calls(scratch) == []


def test_a_config_change_checks_every_file(scratch):
    """A changed settings file checks every input file again."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "settings.toml").write_text("line-length = 79\n")
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py", "src/b.py"], ["md", "notes.md"]]


def test_a_config_change_reruns_a_whole_task(scratch):
    """A changed settings file runs a whole task again."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "settings.toml").write_text("line-length = 79\n")
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_everything_runs_the_whole_task_and_records(scratch):
    """``--all`` runs despite a passed record, and its pass is recorded."""
    run("whole", scratch)
    run("lint", scratch)
    _calls(scratch)
    assert run("whole", scratch, everything=True) == 0
    assert run("lint", scratch, everything=True) == 0
    assert _calls(scratch) == [
        ["whole"],
        ["py", "src/a.py", "src/b.py"],
        ["md", "notes.md"],
    ]
    (scratch / "src" / "c.py").write_text("c = 3\n")
    assert run("whole", scratch, everything=True) == 0
    _calls(scratch)
    assert run("whole", scratch) == 0
    assert _calls(scratch) == []


def test_records_are_kept_twenty_and_replaced_atomically(scratch, monkeypatch):
    """25 passes keep the 20 newest, each written whole then moved into place."""
    moves = []
    replace = _checks.os.replace

    def spy(source, target):
        moves.append((source, target))
        replace(source, target)

    monkeypatch.setattr(_checks.os, "replace", spy)
    for i in range(25):
        (scratch / "src" / "a.py").write_text(f"a = {i}\n")
        assert run("whole", scratch) == 0
    directory = _checks.record_dir(scratch)
    records = json.loads((directory / "whole.json").read_text())
    assert len(records) == 20
    assert records[-1]["digest"] == digest(_checks.TASKS["whole"], scratch)
    assert len(moves) == 25
    assert all(
        _checks.Path(s).parent == directory and t == directory / "whole.json"
        for s, t in moves
    )
    assert sorted(p.name for p in directory.iterdir()) == ["whole.json"]
    assert directory.parent == (scratch / ".git").resolve()


def test_the_command_line_runs_a_task(scratch, monkeypatch, capsys):
    """``python -m validation._checks <task> [--all]`` runs it from the repository."""
    monkeypatch.chdir(scratch / "src")
    assert _checks.cli(["whole"]) == 0
    assert _checks.cli(["whole"]) == 0
    assert _checks.cli(["whole", "--all"]) == 0
    assert _calls(scratch) == [["whole"], ["whole"]]
    assert "whole: unchanged since a passed run" in capsys.readouterr().out
