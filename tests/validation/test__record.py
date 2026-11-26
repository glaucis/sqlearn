"""A runner's record: what it imported, hashed, and whether it passed."""

import importlib
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from validation import _record as record_module
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


@pytest.fixture
def engine_repo(tmp_path, monkeypatch):
    """A scratch git repository with an engine source and a build table."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "a.cpp").write_text("int a;\n")
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["nanobind==3.1.0"]\n\n'
        '[project]\nname = "x"\n\n[tool.scikit-build]\nbuild-dir = "build"\n'
    )
    compiler = tmp_path / "cxx"
    compiler.write_text("#!/bin/sh\necho 'clang version 1'\n")
    compiler.chmod(0o755)
    monkeypatch.setenv("CXX", str(compiler))
    return tmp_path


def test_the_engine_digest_follows_what_the_module_is_built_from(engine_repo):
    """An engine source, a submodule's pin, the build table or the compiler."""
    first = record_module.engine(engine_repo)
    assert record_module.engine(engine_repo) == first
    pyproject = engine_repo / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('"x"', '"y"'))
    assert record_module.engine(engine_repo) == first, "outside the build table"

    source = engine_repo / "engine" / "a.cpp"
    source.write_text("int b;\n")
    assert record_module.engine(engine_repo) != first
    source.write_text("int a;\n")

    pyproject.write_text(pyproject.read_text().replace('"build"', '"other"'))
    assert record_module.engine(engine_repo) != first
    pyproject.write_text(pyproject.read_text().replace('"other"', '"build"'))

    compiler = engine_repo / "cxx"
    compiler.write_text("#!/bin/sh\necho 'clang version 2'\n")
    assert record_module.engine(engine_repo) != first
    compiler.write_text("#!/bin/sh\necho 'clang version 1'\n")
    assert record_module.engine(engine_repo) == first

    pin = "0123456789abcdef0123456789abcdef01234567"
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{pin},engine/sub"],
        cwd=engine_repo,
        check=True,
    )
    assert record_module.engine(engine_repo) != first


def test_a_build_requirement_bump_is_another_engine(engine_repo):
    """A pinned build requirement is an input: its bump changes the digest."""
    first = record_module.engine(engine_repo)
    pyproject = engine_repo / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace("3.1.0", "3.1.1"))
    assert record_module.engine(engine_repo) != first
    pyproject.write_text(pyproject.read_text().replace("3.1.1", "3.1.0"))
    assert record_module.engine(engine_repo) == first


def test_a_records_environment_holds_the_engine_digest(engine_repo):
    """The environment a record keeps is the base one, with the engine's."""
    environment = record_module.environment(dict(ENVIRONMENT), engine_repo)
    assert environment == {
        **ENVIRONMENT,
        "engine": record_module.engine(engine_repo),
    }
