"""Each check's record: the digest of its inputs when it passed, and its reruns."""

import dataclasses
import json
import platform
import subprocess
import sys
from pathlib import Path

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
if (here / "code").exists():
    sys.exit(int((here / "code").read_text()))
"""

# A tool outside uv.lock (Homebrew's clang-tidy): it prints the version the
# file beside it names.
VERSION = """\
import pathlib
print((pathlib.Path(__file__).parent / "version.txt").read_text(), end="")
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
            layout=("*.py",),
        ),
        "allowed": Task(
            name="allowed",
            inputs=("src",),
            config=("settings.toml",),
            steps=(Step((*command, "allowed"), ok=(0, 5)),),
            per_file=False,
        ),
        "selective": Task(
            name="selective",
            inputs=("src",),
            config=("settings.toml",),
            steps=(
                Step((*command, "selective"), everything=("--all",), always=True),
                Step((*command, "rest")),
            ),
            per_file=False,
        ),
        "tooled": Task(
            name="tooled",
            inputs=("src",),
            config=("settings.toml",),
            steps=(Step((*command, "tooled")),),
            per_file=False,
            tools=((sys.executable, str(tool.parent / "version.py")),),
        ),
        "tooled-lint": Task(
            name="tooled-lint",
            inputs=("*.py",),
            config=("settings.toml",),
            steps=(Step((*command, "py")),),
            per_file=True,
            tools=((sys.executable, str(tool.parent / "version.py")),),
        ),
        "none": Task(
            name="none",
            inputs=("*.rst",),
            config=("settings.toml",),
            steps=(Step((*command, "rst")),),
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
    (tmp_path / "version.py").write_text(VERSION)
    (tmp_path / "version.txt").write_text("tool 1.0\n")
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


def test_an_executable_bit_change_reruns_a_whole_task(scratch):
    """A file's mode is read by tests (the hooks): chmod alone reruns the task."""
    run("whole", scratch)
    _calls(scratch)
    (scratch / "src" / "a.py").chmod(0o755)
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_an_executable_bit_change_checks_that_file_again(scratch):
    """A per-file task counts the mode in each file's own digest."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "src" / "a.py").chmod(0o755)
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py"]]


def test_a_new_module_checks_every_file_again(scratch):
    """Import sorting depends on which modules exist: a new one relints all."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "src" / "c.py").write_text("c = 3\n")
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [
        ["py", "src/a.py", "src/b.py", "src/c.py"],
        ["md", "notes.md"],
    ]


def test_a_removed_module_checks_every_file_again(scratch):
    """A module gone changes what the imports of the others classify as."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "src" / "b.py").unlink()
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py"], ["md", "notes.md"]]


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
    assert changed_files(_checks.TASKS["lint"], scratch) == [Path("src/a.py")]
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py"]]
    assert run("lint", scratch) == 0
    assert _calls(scratch) == []
    assert "lint: unchanged since a passed run" in capsys.readouterr().out


def test_a_per_file_task_checks_a_new_file(scratch):
    """A file added under the inputs but not the layout is checked, alone."""
    run("lint", scratch)
    _calls(scratch)
    (scratch / "more.md").write_text("# More\n")
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [["md", "more.md"]]


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
        Path(s).parent == directory and t == directory / "whole.json" for s, t in moves
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


def test_everything_hands_a_step_its_own_all_arguments(scratch):
    """A step that selects within itself (the C++ groups) is told to run all."""
    assert run("selective", scratch) == 0
    assert run("selective", scratch, everything=True) == 0
    assert _calls(scratch) == [
        ["selective"],
        ["rest"],
        ["selective", "--all"],
        ["rest"],
    ]


def test_a_step_that_selects_within_itself_runs_on_an_unchanged_task(scratch, capsys):
    """It keeps records of its own, so it decides; the other steps are skipped."""
    assert run("selective", scratch) == 0
    _calls(scratch)
    capsys.readouterr()
    assert run("selective", scratch) == 0
    assert _calls(scratch) == [["selective"]]
    assert "selective: unchanged since a passed run" in capsys.readouterr().out
    (scratch.parent / "code").write_text("3")
    assert run("selective", scratch) == 3
    assert _calls(scratch) == [["selective"]]


def test_a_failing_step_does_not_hide_the_others(scratch):
    """Every step runs, and the task returns the first failure's exit code."""
    (scratch.parent / "fail").touch()
    assert run("lint", scratch) == 1
    assert _calls(scratch) == [["py", "src/a.py", "src/b.py"], ["md", "notes.md"]]


def test_an_exit_code_a_step_allows_is_a_pass(scratch):
    """A step's allowed exit (pytest's 5, no test collected) passes and records."""
    (scratch.parent / "code").write_text("5")
    assert run("allowed", scratch) == 0
    assert _calls(scratch) == [["allowed"]]
    assert run("allowed", scratch) == 0
    assert _calls(scratch) == []
    (scratch.parent / "code").write_text("3")
    (scratch / "src" / "a.py").write_text("a = 10\n")
    assert run("allowed", scratch) == 3


def test_everything_on_a_task_with_no_files_says_so(scratch, capsys):
    """``--all`` with no input file runs nothing and claims no passed run."""
    assert run("none", scratch, everything=True) == 0
    assert _calls(scratch) == []
    out = capsys.readouterr().out
    assert "none: no files to check" in out
    assert "unchanged" not in out


@pytest.mark.parametrize("content", ["{not json", "{}", "[1]", '[{"digest": 1}]'])
def test_a_malformed_record_file_counts_as_absent(scratch, content):
    """A record file that does not parse as records reruns the task, no crash."""
    directory = _checks.record_dir(scratch)
    directory.mkdir()
    (directory / "whole.json").write_text(content)
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]
    assert run("whole", scratch) == 0
    assert _calls(scratch) == []


def test_an_unreadable_record_file_counts_as_absent(scratch):
    """A record file that cannot be read reruns the task, no crash."""
    directory = _checks.record_dir(scratch)
    directory.mkdir()
    path = directory / "whole.json"
    path.write_text("[]")
    path.chmod(0)
    try:
        assert _checks.load(directory, "whole") == []
        assert run("whole", scratch) == 0
    finally:
        path.chmod(0o644)
    assert _calls(scratch) == [["whole"]]


def test_a_failed_save_leaves_no_temporary_file(scratch, monkeypatch):
    """A write that fails leaves the records' directory as it was."""

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(_checks.json, "dump", broken)
    with pytest.raises(OSError, match="disk full"):
        run("whole", scratch)
    directory = _checks.record_dir(scratch)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize(
    ("owner", "name", "value"),
    [
        (sys, "version", "3.99.0 (another build)"),
        (platform, "platform", lambda: "another-os-1.0"),
        (platform, "machine", lambda: "another-cpu"),
    ],
)
def test_a_new_place_to_run_reruns_every_task(scratch, monkeypatch, owner, name, value):
    """Another Python, platform or machine reruns a whole task and every file."""
    run("whole", scratch)
    run("lint", scratch)
    _calls(scratch)
    monkeypatch.setattr(owner, name, value)
    assert run("whole", scratch) == 0
    assert run("lint", scratch) == 0
    assert _calls(scratch) == [
        ["whole"],
        ["py", "src/a.py", "src/b.py"],
        ["md", "notes.md"],
    ]


SETTINGS = {"pyproject.toml", "uv.lock", ".python-version", "justfile"}


def test_the_task_table_names_every_check():
    """The table holds each check the helper records; validate keeps its own."""
    assert set(_checks.TASKS) == {
        "format",
        "lint",
        "docstrings",
        "types",
        "test",
        "docs",
        "tidy",
    }
    assert all(name == task.name for name, task in _checks.TASKS.items())


def test_every_task_declares_the_settings_files():
    """A change to the settings every tool reads reruns each task in full."""
    for task in _checks.TASKS.values():
        assert set(task.config) >= SETTINGS, task.name


def test_only_the_serial_pass_may_collect_nothing():
    """Exit 5 passes the serial pass alone: a broken marker elsewhere must fail."""
    steps = [s for s in _checks.TASKS["test"].steps if s.command[0] == "pytest"]
    passes = [s.command[s.command.index("-m") + 1] for s in steps]
    assert passes == ["not slow and not serial", "serial and not slow", "slow", ""]
    assert [s.ok for s in steps] == [(0,), (0, 5), (0,), (0,)]


def test_the_lint_task_keys_its_config_to_the_python_layout():
    """Ruff's import sorting depends on which modules exist."""
    assert "*.py" in _checks.TASKS["lint"].layout


def test_the_place_is_printed_as_one_word_that_names_python(monkeypatch, capsys):
    """``--place`` prints one hash, another for another Python; it runs nothing."""
    assert _checks.cli(["--place"]) == 0
    here = capsys.readouterr().out.strip()
    assert len(here) == 64
    assert int(here, 16) >= 0
    monkeypatch.setattr(sys, "version", "3.99.0 (another build)")
    assert _checks.cli(["--place"]) == 0
    assert capsys.readouterr().out.strip() not in {"", here}


@pytest.mark.parametrize(
    "config", ["ruff.toml", ".ruff.toml", "src/ruff.toml", "_typos.toml", "ty.toml"]
)
def test_a_new_tool_config_file_reruns_lint_on_every_file(scratch, config):
    """A tool's own configuration file, added at the root or deeper, governs
    every file it reaches: the real lint task checks every file again."""
    lint = _checks._table()["lint"]
    files = _checks._hashes(_checks._listed(lint.inputs, scratch), scratch)
    _checks.save(
        _checks.record_dir(scratch),
        "lint",
        _checks.Record(digest="", config=_checks._config(lint, scratch), files=files),
    )
    assert changed_files(lint, scratch) == []
    (scratch / config).write_text("line-length = 79\n")
    assert set(changed_files(lint, scratch)) >= {Path(n) for n in files}


def test_a_submodule_bump_reruns_a_whole_task(scratch, tmp_path):
    """A gitlink is a directory, not a file: its pinned commit still counts."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _git(sub, "init", "--quiet")
    commit = ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q")
    _git(sub, *commit, "--allow-empty", "-m", "one")
    _git(sub, *commit, "--allow-empty", "-m", "two")

    def rev(name):
        return subprocess.run(
            ["git", "rev-parse", name],
            cwd=sub,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    first, second = rev("HEAD~1"), rev("HEAD")
    _git(
        scratch,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(sub),
        "src/sub",
    )
    _git(scratch / "src" / "sub", "checkout", "-q", first)
    _git(scratch, "add", "src/sub")
    before = digest(_checks.TASKS["whole"], scratch)
    run("whole", scratch)
    _calls(scratch)
    _git(scratch / "src" / "sub", "checkout", "-q", second)
    _git(scratch, "add", "src/sub")
    assert digest(_checks.TASKS["whole"], scratch) != before
    assert run("whole", scratch) == 0
    assert _calls(scratch) == [["whole"]]


def test_the_test_task_runs_the_changed_cxx_groups_before_python():
    """The C++ groups go first, on dev, and all of them under ``--all``."""
    first = _checks.TASKS["test"].steps[0]
    assert first.command == ("just", "test-engine-changed", "dev")
    assert first.everything == ("--all",)


def test_a_tool_upgrade_reruns_a_whole_task(scratch):
    """A tool outside uv.lock is part of the configuration: a new version of it,
    with no input changed, runs the task again."""
    run("tooled", scratch)
    _calls(scratch)
    assert run("tooled", scratch) == 0
    assert _calls(scratch) == []
    (scratch.parent / "version.txt").write_text("tool 2.0\n")
    assert run("tooled", scratch) == 0
    assert _calls(scratch) == [["tooled"]]


def test_a_tool_upgrade_checks_every_file_again(scratch):
    """A per-file task checks every file again under a new version of its tool."""
    run("tooled-lint", scratch)
    _calls(scratch)
    (scratch.parent / "version.txt").write_text("tool 2.0\n")
    assert run("tooled-lint", scratch) == 0
    assert _calls(scratch) == [["py", "src/a.py", "src/b.py"]]


def test_a_missing_tool_is_part_of_the_configuration(scratch):
    """A tool that is not installed hashes as absent, never a crash: its
    task's own step then fails and names it."""
    task = _checks.TASKS["tooled"]
    before = _checks._config(task, scratch)
    missing = dataclasses.replace(task, tools=(("no-such-tool-here", "--version"),))
    assert _checks._config(missing, scratch) != before


def test_the_engine_tasks_name_their_homebrew_tools():
    """clang-tidy, include-what-you-use and clang-format come from Homebrew,
    not uv.lock: their versions rerun the tasks that use them."""
    tidy = {t[0].rsplit("/", 1)[-1] for t in _checks.TASKS["tidy"].tools}
    fmt = {t[0].rsplit("/", 1)[-1] for t in _checks.TASKS["format"].tools}
    assert {"clang-tidy", "include-what-you-use"} <= tidy
    assert "clang-format" in fmt


def test_the_tidy_task_reads_our_cxx_and_not_the_submodules():
    """tidy's inputs are our sources, its settings and the submodules' commits."""
    tidy = _checks.TASKS["tidy"]
    assert not tidy.per_file
    for path in (
        "engine/src",
        "engine/tests",
        "engine/bench",
        "engine/extension",
        "engine/cmake",
        "engine/.clang-tidy",
        "engine/src/raw/.clang-tidy",
        "engine/iwyu.imp",
    ):
        assert path in tidy.inputs, path
