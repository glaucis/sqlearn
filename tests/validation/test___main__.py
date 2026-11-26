"""The validation's entry point: runs what changed, records it, and gates."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from validation import __main__ as entry
from validation import _record

REPO = Path(__file__).resolve().parents[2]

GOOD = "validate_standin_good"
BAD = "validate_standin_bad"
ODD = "validate_standin_odd"
EDITOR = "validate_standin_editor"

# A runner that imports a helper, then edits the helper's source while it runs.
MAKER = "validate_standin_maker"

# A runner that writes a module beside it while it runs, then imports it.
MAKER_SOURCE = """\
import importlib
import pathlib

def cases():
    made = pathlib.Path(__file__).with_name("standin_made.py")
    made.write_text("Y = 2\\n")
    importlib.invalidate_caches()
    importlib.import_module("standin_made")
    return [{"step": "x", "reference": "sqlearn", "result": "pass"}]
"""

EDITOR_SOURCE = """\
import pathlib
import standin_helper

def cases():
    path = pathlib.Path(standin_helper.__file__)
    path.write_text(path.read_text() + "# edited while the runner ran\\n")
    return [{"step": "x", "reference": "sqlearn", "result": "pass"}]
"""


def _source(result: str) -> str:
    """A runner whose one case has the given result."""
    return (
        "def cases():\n"
        f'    return [{{"step": "x", "reference": "sqlearn", "result": "{result}"}}]\n'
    )


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A scratch git repository with three stand-in runners; its ``validation/``."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    standins = tmp_path / "standins"
    standins.mkdir()
    (standins / f"{GOOD}.py").write_text(_source("pass"))
    (standins / f"{BAD}.py").write_text(_source("fail"))
    (standins / f"{ODD}.py").write_text(_source("anomaly"))
    (standins / f"{EDITOR}.py").write_text(EDITOR_SOURCE)
    (standins / "standin_helper.py").write_text("X = 1\n")
    # the child runs in the scratch repository: it finds the stand-ins and
    # this repository's validation package on its path
    monkeypatch.setenv("PYTHONPATH", f"{standins}{os.pathsep}{REPO}")
    return tmp_path / "validation"


def _results(root: Path, name: str) -> Path:
    """Where the stand-in `name` writes its results."""
    return root.parent / "standins" / (name.removeprefix("validate_") + ".results.json")


def test_an_unchanged_runner_is_skipped_and_its_results_kept(root, capfd):
    """A second run with nothing changed reruns nothing and keeps the results."""
    assert entry.main([GOOD], root) == 0
    first = _results(root, GOOD).read_bytes()
    capfd.readouterr()
    assert entry.main([GOOD], root) == 0
    assert f"{GOOD}: unchanged since a passed run" in capfd.readouterr().out
    assert _results(root, GOOD).read_bytes() == first
    assert (root / "environment.json").is_file()


def test_a_changed_runner_reruns(root, capfd):
    """Touching one runner's source reruns that runner alone."""
    assert entry.main([GOOD, ODD], root) == 0
    source = root.parent / "standins" / f"{GOOD}.py"
    source.write_text(source.read_text() + "# touched\n")
    capfd.readouterr()
    assert entry.main([GOOD, ODD], root) == 0
    out = capfd.readouterr().out
    assert f"{GOOD}: {{'pass': 1}}" in out
    assert f"{ODD}: unchanged since a passed run" in out


def test_everything_reruns_every_runner(root, capfd):
    """``--all`` reruns a runner whose record matches."""
    assert entry.main([GOOD], root) == 0
    capfd.readouterr()
    assert entry.main([GOOD], root, everything=True) == 0
    assert f"{GOOD}: {{'pass': 1}}" in capfd.readouterr().out


def test_a_failing_runner_reruns_each_time_and_exits_1(root, capfd):
    """A sqlearn case outside its bound fails the run, and reruns every time."""
    assert entry.main([GOOD, BAD], root) == 1
    assert _results(root, BAD).is_file()
    capfd.readouterr()
    assert entry.main([GOOD, BAD], root) == 1
    out = capfd.readouterr().out
    assert f"{BAD}: {{'fail': 1}}" in out
    assert f"{GOOD}: unchanged since a passed run" in out


def test_an_anomaly_exits_zero_and_is_written(root):
    """An anomaly in a reference is reported, never a failure."""
    assert entry.main([ODD], root) == 0
    assert '"result": "anomaly"' in _results(root, ODD).read_text()


def test_one_runner_writes_its_results_and_its_record(root, monkeypatch):
    """``--one`` runs a runner here and records the source it imported."""
    monkeypatch.syspath_prepend(str(root.parent / "standins"))
    monkeypatch.delitem(sys.modules, GOOD, raising=False)
    repo = root.parent.resolve()
    try:
        assert entry.run_one(GOOD, repo) == 0
    finally:
        sys.modules.pop(GOOD, None)
    assert _results(root, GOOD).is_file()
    (record,) = _record.load(_record.record_dir(repo), GOOD)
    assert f"standins/{GOOD}.py" in record["depends"]
    assert record["counts"] == {"pass": 1}
    assert record["passed"]


def test_a_file_edited_while_the_runner_ran_is_not_recorded(root, capfd):
    """A module the runner imported, edited during its run: no record is saved,
    so the next run reruns it rather than trusting results of the old code."""
    assert entry.main([EDITOR], root) == 0
    out = capfd.readouterr().out
    assert f"{EDITOR}: not recorded" in out
    assert "standins/standin_helper.py" in out
    repo = root.parent.resolve()
    assert _record.load(_record.record_dir(repo), EDITOR) == []
    assert entry.main([EDITOR], root) == 0
    assert f"{EDITOR}: {{'pass': 1}}" in capfd.readouterr().out


def test_a_module_written_while_the_runner_ran_is_not_recorded(root, capfd):
    """A module the runner wrote, then imported, had no hash before the run: no
    record is saved."""
    (root.parent / "standins" / f"{MAKER}.py").write_text(MAKER_SOURCE)
    assert entry.main([MAKER], root) == 0
    out = capfd.readouterr().out
    assert f"{MAKER}: not recorded" in out
    assert "standins/standin_made.py" in out
    assert _record.load(_record.record_dir(root.parent.resolve()), MAKER) == []


def test_results_path_mirrors_the_runner():
    """validate_scale.py writes scale.results.json beside it."""
    module = types.ModuleType("x")
    module.__file__ = "/a/b/validate_scale.py"
    assert str(entry.results_path(module)) == "/a/b/scale.results.json"


def test_a_changed_engine_reruns_every_runner(root, capfd):
    """An edit under ``engine/`` rebuilds the module, so every runner reruns."""
    assert entry.main([GOOD, ODD], root) == 0
    (root.parent / "engine").mkdir()
    (root.parent / "engine" / "a.cpp").write_text("int a;\n")
    capfd.readouterr()
    assert entry.main([GOOD, ODD], root) == 0
    out = capfd.readouterr().out
    assert f"{GOOD}: {{'pass': 1}}" in out
    assert f"{ODD}: {{'anomaly': 1}}" in out
    assert "engine" not in json.loads((root / "environment.json").read_text())
