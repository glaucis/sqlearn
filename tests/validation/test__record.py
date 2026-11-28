"""A runner's record: what it imported, hashed, and whether it passed."""

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from validation import _record as record_module
from validation._record import (
    SELECTION,
    Record,
    digest,
    load,
    loaded_files,
    matching,
    save,
)

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


def test_loaded_files_names_repo_modules_and_the_lock_only(tmp_path, scratch_module):
    """Modules under the root and uv.lock; never numpy's."""
    (tmp_path / "uv.lock").write_text("lock\n")
    names = {
        p.relative_to(tmp_path.resolve()).as_posix() for p in loaded_files(tmp_path)
    }
    assert names == {"scratch_record_module.py", "uv.lock"}
    numpy = Path(np.__file__).resolve()
    assert numpy not in loaded_files(tmp_path)


def test_loaded_files_leave_out_the_selection_machinery():
    """The modules that decide what runs are no part of a runner's identity;
    a runner's own helpers still are."""
    from validation import _cases, _groups  # noqa: F401

    repo = Path(__file__).resolve().parents[2]
    names = {p.relative_to(repo).as_posix() for p in loaded_files(repo)}
    assert not {f"{m.replace('.', '/')}.py" for m in SELECTION} & names
    assert "validation/_cases.py" in names


@pytest.mark.parametrize(
    "content", ["", '[{"runner": "validation.x', "{}", "[1]", '[{"runner": 1}]']
)
def test_a_corrupt_or_partial_record_file_counts_as_absent(tmp_path, content):
    """A record file cut short or not of records loads as none, no crash."""
    (tmp_path / "validation.x.validate_y.json").write_text(content)
    assert load(tmp_path, "validation.x.validate_y") == []


def test_an_unreadable_record_file_counts_as_absent(tmp_path):
    """A record file that cannot be read loads as none, no crash."""
    path = tmp_path / "validation.x.validate_y.json"
    path.write_text("[]")
    path.chmod(0)
    try:
        assert load(tmp_path, "validation.x.validate_y") == []
    finally:
        path.chmod(0o644)


def test_a_failed_save_leaves_no_temporary_file(root, tmp_path, monkeypatch):
    """A write that fails leaves the records' directory as it was."""

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(record_module.json, "dump", broken)
    records = tmp_path / "records"
    with pytest.raises(OSError, match="disk full"):
        save(records, _record(root))
    assert list(records.iterdir()) == []


def _claim(scratch, claims):
    """Rewrite the manifest so each group of `claims` has these runners."""
    path = scratch.build / "sq_groups.json"
    data = json.loads(path.read_text())
    for group in data["groups"]:
        group["validation"] = claims.get(group["name"], [])
    path.write_text(json.dumps(data))


def test_a_comment_edit_keeps_every_runners_record(scratch):
    """``// x`` becoming ``// y`` in a group moves no fingerprint."""
    first = record_module.engine(scratch.root, "validate_x")
    scratch.write("a/one.cpp", '#include "a/one.hpp"\n// y\nint one() { return 1; }\n')
    assert record_module.engine(scratch.root, "validate_x") == first


def test_a_claimed_runner_reruns_for_its_group_alone(scratch):
    """``b`` claims GOOD, which also reads ``a`` (``b`` depends on it); ODD,
    claimed by none, reads every group; ``a``'s own runner ignores ``b``."""
    _claim(scratch, {"b": ["validate_good"], "a": ["validate_alone"]})
    good, odd, alone = (
        record_module.engine(scratch.root, name)
        for name in ("validate_good", "validate_odd", "validate_alone")
    )
    scratch.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return 2; }\n')
    assert record_module.engine(scratch.root, "validate_good") != good
    assert record_module.engine(scratch.root, "validate_odd") != odd
    assert record_module.engine(scratch.root, "validate_alone") == alone
    scratch.write("a/one.hpp", "#pragma once\nint one();\nint other();\n")
    assert record_module.engine(scratch.root, "validate_good") != good
    assert record_module.engine(scratch.root, "validate_alone") != alone


def test_a_runner_is_named_by_its_modules_last_part(scratch):
    """The manifest names ``validate_pca``, the runner is its dotted module."""
    _claim(scratch, {"a": ["validate_pca"]})
    name = "validation.sqlearn.decomposition.validate_pca"
    first = record_module.engine(scratch.root, name)
    scratch.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return 2; }\n')
    assert record_module.engine(scratch.root, name) == first


def test_an_unreadable_build_reruns_every_runner(scratch, capsys):
    """No manifest: the reason is printed, and no record matches."""
    (scratch.build / "sq_groups.json").unlink()
    environment = {**ENVIRONMENT, "groups": record_module.engine(scratch.root, "x")}
    assert environment["groups"] == "unreadable"
    assert "sq_groups.json" in capsys.readouterr().out
    record = Record(
        runner="x",
        depends={},
        environment=environment,
        counts={"pass": 1},
        passed=True,
    )
    assert matching([record], scratch.root, environment) is None


def test_a_record_from_before_the_groups_is_rerun_once(scratch):
    """A record keeping the old ``engine`` digest is no match; once the runner
    ran again, its new record is."""
    environment = {**ENVIRONMENT, "groups": record_module.engine(scratch.root, "x")}
    old = Record(
        runner="x",
        depends={},
        environment={**ENVIRONMENT, "engine": "0" * 64},
        counts={"pass": 1},
        passed=True,
    )
    assert matching([old], scratch.root, environment) is None
    new = Record(
        runner="x", depends={}, environment=environment, counts={"pass": 1}, passed=True
    )
    assert matching([old, new], scratch.root, environment) == new


def test_forgetting_passes_keeps_the_failures_of_the_identity(root, tmp_path):
    """Only the passed record under the identity goes; a failure stays."""
    directory = tmp_path / "records"
    environment = {**ENVIRONMENT, "groups": "g1"}
    for passed in (True, False):
        save(directory, {**_record(root, passed), "environment": environment})
    record_module.forget_passes(directory, "validation.x.validate_y", "g1")
    kept = load(directory, "validation.x.validate_y")
    assert [r["passed"] for r in kept] == [False]
