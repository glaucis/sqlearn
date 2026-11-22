"""A runner's record: what it imported, hashed, and whether it passed."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

from validation._record import Record, digest, load, loaded_files, matching, save

ENVIRONMENT = {"os_release": "27.2.1", "numpy": "2.3.0"}


def _record(
    root: Path, passed: bool = True, counts: dict[str, int] | None = None
) -> Record:
    """A record of `root`'s ``runner.py`` as it is now."""
    return Record(
        runner="validation.x.validate_y",
        depends=digest([root / "runner.py"], root),
        environment=dict(ENVIRONMENT),
        counts=counts or {"pass": 1},
        passed=passed,
    )


@pytest.fixture
def root(tmp_path):
    """A scratch repository holding one runner's source."""
    (tmp_path / "runner.py").write_text("def cases():\n    return []\n")
    return tmp_path


def test_a_record_matches_while_its_files_are_unchanged(root):
    """Nothing it imported changed: the record stands for a rerun."""
    record = _record(root)
    assert matching([record], root, dict(ENVIRONMENT)) == record


def test_a_changed_file_breaks_the_match(root):
    """One changed byte in a file it imported means it runs again."""
    record = _record(root)
    (root / "runner.py").write_text("def cases():\n    return [ ]\n")
    assert matching([record], root, dict(ENVIRONMENT)) is None


def test_a_deleted_file_breaks_the_match(root):
    """A file it imported that is gone means it runs again."""
    record = _record(root)
    (root / "runner.py").unlink()
    assert matching([record], root, dict(ENVIRONMENT)) is None


def test_a_changed_environment_breaks_the_match(root):
    """An OS update (27.2.1 to 27.3) means it runs again."""
    record = _record(root)
    later = {**ENVIRONMENT, "os_release": "27.3"}
    assert matching([record], root, later) is None


def test_a_failed_run_is_never_matched(root):
    """A run with a failing case reruns, even with nothing changed."""
    assert matching([_record(root, passed=False)], root, dict(ENVIRONMENT)) is None


def test_a_failed_run_cancels_an_earlier_pass_of_the_same_inputs(root):
    """A pass, then a fail with nothing changed: the newest decides, it reruns."""
    records = [_record(root), _record(root, passed=False)]
    assert matching(records, root, dict(ENVIRONMENT)) is None


def test_save_keeps_the_twenty_newest(root, tmp_path):
    """Each save adds a record; only the twenty newest are kept, oldest first."""
    records = tmp_path / "records"
    for i in range(25):
        save(records, _record(root, counts={"pass": i}))
    kept = load(records, "validation.x.validate_y")
    assert [r["counts"]["pass"] for r in kept] == list(range(5, 25))
    assert load(records, "validation.other") == []


@pytest.fixture
def scratch_module(tmp_path, monkeypatch):
    """Import a module from a scratch root; forget it afterwards."""
    (tmp_path / "scratch_record_module.py").write_text("X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("scratch_record_module")
    yield module
    sys.modules.pop("scratch_record_module", None)


def test_loaded_files_names_repo_modules_and_declared_data_only(
    tmp_path, scratch_module
):
    """Modules under the root, uv.lock and devdata's files; never numpy's."""
    (tmp_path / "uv.lock").write_text("lock\n")
    (tmp_path / "devdata" / "data").mkdir(parents=True)
    (tmp_path / "devdata" / "data" / "iris.csv").write_text("a\n1\n")
    names = {
        p.relative_to(tmp_path.resolve()).as_posix() for p in loaded_files(tmp_path)
    }
    assert names == {"scratch_record_module.py", "uv.lock", "devdata/data/iris.csv"}
    numpy = Path(np.__file__).resolve()
    assert numpy not in loaded_files(tmp_path)
