"""What ``just sweep`` says: every check in full, compared with the selection."""

import datetime
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from validation import _affected, _checks, _sweep
from validation._affected import Verdict

TASKS = ("format", "lint", "test", "docs")
"""The stand-in table's tasks, in its order."""

REPO = Path(__file__).resolve().parents[2]

TREE = "0123456789abcdef0123456789abcdef01234567"


def _git(root, *args):
    """Run git in `root`."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Sweep:
    """Stand-ins for ``report`` and ``just full``, and what ``full`` ran."""

    def __init__(self, root):
        self.root = root
        self.verdicts = []
        self.codes = {}
        self.ran = []

    def report(self, root):
        """The stand-in for ``_affected.report``."""
        assert root == self.root
        return self.verdicts

    def full(self, task, root):
        """The stand-in for ``just full <task>``: its code from ``codes``."""
        assert root == self.root
        self.ran.append(task)
        return self.codes.get(task, 0)

    def say(self, **runs):
        """Set each verdict: ``runs`` for those named true, else unchanged."""
        self.verdicts = [
            Verdict(check=name, runs=runs.get(name, False), reasons=())
            for name in ("format", "lint", "docs")
        ]
        self.verdicts[2:2] = [
            Verdict(check=f"test: {k}", runs=runs.get(k, False), reasons=())
            for k in ("core", "tooling")
        ]


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    """A scratch repository, ``report`` and ``just full`` replaced by stand-ins."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    stand_in = Sweep(root)
    stand_in.say()
    monkeypatch.setattr(_checks, "TASKS", dict.fromkeys(TASKS))
    monkeypatch.setattr(_affected, "report", stand_in.report)
    monkeypatch.setattr(_sweep, "_full", stand_in.full)
    monkeypatch.setattr(_sweep, "_tree", lambda root: (TREE, True))
    return stand_in


def _saved(root):
    """Return the saved sweep, or None."""
    path = _checks.record_dir(root) / _sweep.SWEEP
    return json.loads(path.read_text()) if path.exists() else None


def test_a_check_called_unchanged_that_fails_is_a_missed_rerun(sweep, capsys):
    """A failure the selection would have skipped exits 1, naming the check."""
    sweep.say(format=True)
    sweep.codes = {"lint": 3}
    assert _sweep.run(sweep.root) == 1
    out = capsys.readouterr().out
    assert "lint: a missed rerun" in out
    assert f"{_sweep.FIX}\n" in out
    assert "Fix: run just affected, find the input the check reads but" in out
    assert _saved(sweep.root) is None


def test_a_test_failure_with_every_label_unchanged_is_a_missed_rerun(sweep, capsys):
    """``test`` is unchanged only when every ``test: ...`` verdict is."""
    sweep.codes = {"test": 2}
    assert _sweep.run(sweep.root) == 1
    assert "test: a missed rerun" in capsys.readouterr().out


def test_a_failure_of_a_check_that_would_run_is_no_missed_rerun(sweep, capsys):
    """Failures only of checks the report said would run: the first's code."""
    sweep.say(lint=True, tooling=True)
    sweep.codes = {"lint": 3, "test": 2}
    assert _sweep.run(sweep.root) == 3
    assert "missed rerun" not in capsys.readouterr().out
    assert _saved(sweep.root) is None


def test_every_check_runs_even_after_a_failure(sweep):
    """Each task runs in full, in the table's order, a failing one included."""
    sweep.say(format=True)
    sweep.codes = {"format": 1, "lint": 1}
    _sweep.run(sweep.root)
    assert sweep.ran == list(TASKS)


def test_a_passed_sweep_is_remembered_with_its_date(sweep):
    """A pass saves the tree and today's date in the records' directory."""
    assert _sweep.run(sweep.root) == 0
    today = datetime.date.today().isoformat()
    assert _saved(sweep.root) == {"tree": TREE, "date": today}


def test_an_uncommitted_tree_is_remembered_by_head_and_said(sweep, capsys, monkeypatch):
    """With no checkable tree, HEAD's tree is saved, and the output says so."""
    head = "fedcba9876543210fedcba9876543210fedcba98"
    monkeypatch.setattr(_sweep, "_tree", lambda root: (head, False))
    assert _sweep.run(sweep.root) == 0
    assert _saved(sweep.root)["tree"] == head
    assert "uncommitted" in capsys.readouterr().out


def _warning(root, today):
    """Return `stale`'s warning, which must be there."""
    warning = _sweep.stale(root, today)
    assert warning is not None
    return warning


def _remember(root, day):
    """Save a sweep of `day` in `root`'s records."""
    directory = _checks.record_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _sweep.SWEEP).write_text(
        json.dumps({"tree": TREE, "date": day.isoformat()})
    )


def test_an_old_sweep_warns_and_a_recent_one_does_not(sweep):
    """Older than the cadence, or none, warns with its fix; recent says nothing."""
    today = datetime.date(2026, 11, 28)
    assert "Fix: run just sweep" in _warning(sweep.root, today)
    _remember(sweep.root, today - datetime.timedelta(days=_sweep.CADENCE_DAYS + 1))
    assert "Fix: run just sweep" in _warning(sweep.root, today)
    _remember(sweep.root, today - datetime.timedelta(days=_sweep.CADENCE_DAYS - 1))
    assert _sweep.stale(sweep.root, today) is None


def test_an_unreadable_sweep_warns(sweep):
    """A ``sweep.json`` that does not parse counts as no sweep."""
    directory = _checks.record_dir(sweep.root)
    directory.mkdir(parents=True)
    (directory / _sweep.SWEEP).write_text("{not json")
    assert "Fix: run just sweep" in _warning(sweep.root, datetime.date.today())


def test_the_tree_is_the_checkable_one_else_heads(tmp_path):
    """A committed tree is the checkable one; an edited one gives HEAD's tree."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO / "justfile", root / "justfile")
    (root / "a.py").write_text("a = 1\n")
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert _sweep._tree(root) == (head, True)
    (root / "a.py").write_text("a = 2\n")
    assert _sweep._tree(root) == (head, False)
