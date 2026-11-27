"""The validation's entry point: runs what changed, records it, and gates."""

import json
import os
import sys
import types
from pathlib import Path

import pytest

from validation import __main__ as entry
from validation import _groups, _record

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


# A runner that edits a C++ group's source while it runs.
GROUP_EDITOR = "validate_standin_group_editor"
GROUP_EDITOR_SOURCE = """\
import pathlib

def cases():
    source = pathlib.Path(__file__).parents[1] / "engine" / "src" / "b" / "two.cpp"
    source.write_text(source.read_text() + "int moved();\\n")
    return [{"step": "x", "reference": "sqlearn", "result": "pass"}]
"""


def _source(result: str) -> str:
    """A runner whose one case has the given result."""
    return (
        "def cases():\n"
        f'    return [{{"step": "x", "reference": "sqlearn", "result": "{result}"}}]\n'
    )


@pytest.fixture
def root(scratch, monkeypatch):
    """The scratch repository with three stand-in runners; its ``validation/``."""
    tmp_path = scratch.root
    standins = tmp_path / "standins"
    standins.mkdir()
    (standins / f"{GOOD}.py").write_text(_source("pass"))
    (standins / f"{BAD}.py").write_text(_source("fail"))
    (standins / f"{ODD}.py").write_text(_source("anomaly"))
    (standins / f"{EDITOR}.py").write_text(EDITOR_SOURCE)
    (standins / "standin_helper.py").write_text("X = 1\n")
    manifest = scratch.build / "sq_groups.json"
    data = json.loads(manifest.read_text())
    data["groups"][1]["validation"] = [GOOD]
    manifest.write_text(json.dumps(data))
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


def test_a_changed_group_reruns_every_runner_that_uses_it(root, capfd):
    """An edit of ``b``'s source reruns GOOD (which ``b`` claims) and ODD
    (claimed by none, so it uses every group)."""
    assert entry.main([GOOD, ODD], root) == 0
    (root.parent / "engine" / "src" / "b" / "two.cpp").write_text(
        '#include "a/one.hpp"\nint two() { return 2; }\n'
    )
    capfd.readouterr()
    assert entry.main([GOOD, ODD], root) == 0
    out = capfd.readouterr().out
    assert f"{GOOD}: {{'pass': 1}}" in out
    assert f"{ODD}: {{'anomaly': 1}}" in out
    assert "groups" not in json.loads((root / "environment.json").read_text())


def test_a_change_outside_a_runners_groups_keeps_its_record(root, capfd):
    """ODD claims ``a`` alone: an edit of ``b``, which depends on ``a`` and
    not the other way round, reruns nothing."""
    manifest = root.parent / _groups.WHEEL_BUILD / "sq_groups.json"
    data = json.loads(manifest.read_text())
    data["groups"][0]["validation"] = [ODD]
    data["groups"][1]["validation"] = []
    manifest.write_text(json.dumps(data))
    assert entry.main([ODD], root) == 0
    (root.parent / "engine" / "src" / "b" / "two.cpp").write_text(
        '#include "a/one.hpp"\nint two() { return 2; }\n'
    )
    capfd.readouterr()
    assert entry.main([ODD], root) == 0
    assert f"{ODD}: unchanged since a passed run" in capfd.readouterr().out


def test_an_unreadable_build_reruns_every_runner(root, capfd):
    """No manifest: every runner reruns, each time, with the reason printed."""
    (root.parent / _groups.WHEEL_BUILD / "sq_groups.json").unlink()
    for _ in range(2):
        assert entry.main([GOOD, ODD], root) == 0
        out = capfd.readouterr().out
        assert "sq_groups.json" in out
        assert f"{GOOD}: {{'pass': 1}}" in out
        assert f"{ODD}: {{'anomaly': 1}}" in out


def test_the_fingerprints_are_computed_once_a_run(root, monkeypatch):
    """Two runners rerun, one computation: the child gets the identity."""
    real = entry._groups.fingerprints
    calls = []

    def counted(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(entry._groups, "fingerprints", counted)
    assert entry.main([GOOD, ODD], root) == 0
    assert len(calls) == 1


def test_a_group_edited_while_the_runner_ran_is_not_recorded(root, capfd):
    """The group a runner uses changing during its run (a rebuild under it)
    saves no pass: the record would stand for code it did not run against."""
    (root.parent / "standins" / f"{GROUP_EDITOR}.py").write_text(GROUP_EDITOR_SOURCE)
    manifest = root.parent / _groups.WHEEL_BUILD / "sq_groups.json"
    data = json.loads(manifest.read_text())
    data["groups"][1]["validation"] = [GROUP_EDITOR]
    manifest.write_text(json.dumps(data))
    assert entry.main([GROUP_EDITOR], root) == 0
    out = capfd.readouterr().out
    assert f"{GROUP_EDITOR}: not recorded" in out
    assert "C++ groups" in out
    repo = root.parent.resolve()
    assert _record.load(_record.record_dir(repo), GROUP_EDITOR) == []


def test_each_runner_is_named_by_a_last_part_no_other_has():
    """A group claims a runner by the last part of its module name
    (``validate_pca``): two runners sharing one would share its claims."""
    last = [name.rsplit(".", 1)[-1] for name in entry.RUNNERS]
    assert len(set(last)) == len(last)


def test_an_unreadable_build_records_no_pass(root):
    """A runner run while the groups cannot be read saves no record: one
    under an unreadable identity stands for no build."""
    (root.parent / _groups.WHEEL_BUILD / "sq_groups.json").unlink()
    assert entry.main([GOOD], root) == 0
    repo = root.parent.resolve()
    assert _record.load(_record.record_dir(repo), GOOD) == []
