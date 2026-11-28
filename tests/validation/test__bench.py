"""The benchmarks' due list and the one run, on a scratch repository.

The stand-in benchmark writes ``ran.txt`` in the repository when it runs, so
what ran can be seen. Groups ``a`` and ``b`` are the conftest's; the stand-in
measures group ``a``.
"""

from typing import Any, cast

import pytest

from validation import _bench, _checks, _load

STANDIN = '''"""A stand-in benchmark."""

import time
from pathlib import Path

PAGE = "docs/benchmarks/standin.md"
GROUPS = ("a",)

if __name__ == "__main__":
    Path("ran.txt").write_text("ran")
    end = time.perf_counter() + 0.2
    total = 0
    while time.perf_counter() < end:
        total += 1
    print("measured")
'''


@pytest.fixture(autouse=True)
def _idle_machine(monkeypatch):
    """Run every test on an idle machine, whatever the real load is."""
    monkeypatch.setattr(_load, "now", lambda: 0.0)


def _install(scratch):
    folder = scratch.root / "validation" / "benchmarks"
    folder.mkdir(parents=True)
    (scratch.root / "validation" / "__init__.py").write_text("")
    (folder / "__init__.py").write_text("")
    (folder / "standin.py").write_text(STANDIN)


def test_due_lists_a_benchmark_never_run(scratch):
    """With no record, a benchmark is due and has no last numbers."""
    _install(scratch)
    [item] = _bench.due(scratch.root)
    assert item == _bench.Due("standin", "docs/benchmarks/standin.md", None, None, None)


def test_due_runs_nothing(scratch):
    """Listing what is due starts no benchmark."""
    _install(scratch)
    _bench.due(scratch.root)
    assert not (scratch.root / "ran.txt").exists()


def test_run_records_time_cores_memory_and_load(scratch):
    """A run keeps its wall time, cores, peak memory and the load around it."""
    _install(scratch)
    assert _bench.run(scratch.root, "standin") == 0
    assert (scratch.root / "ran.txt").exists()
    records: list[Any] = _checks.load(_checks.record_dir(scratch.root), "bench-standin")
    [record] = records
    assert record["seconds"] >= 0.2
    assert record["cores"] > 0
    assert record["peak_mb"] > 0
    assert record["uptime_before"] and record["uptime_after"]
    assert _bench.due(scratch.root) == []


def test_a_recorded_benchmark_is_not_due_until_its_group_changes(scratch):
    """Only a change to a group it measures, or one under it, makes it due."""
    _install(scratch)
    _bench.run(scratch.root, "standin")
    assert _bench.due(scratch.root) == []
    scratch.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return 2; }\n')
    assert _bench.due(scratch.root) == []
    scratch.write("a/one.cpp", '#include "a/one.hpp"\n// x\nint one() { return 2; }\n')
    [item] = _bench.due(scratch.root)
    assert item.name == "standin"
    assert item.last_seconds is not None and item.last_seconds >= 0.2
    assert item.last_cores is not None
    assert item.last_peak_mb is not None


def test_a_changed_script_is_due_again(scratch):
    """Editing the benchmark's own script makes it due."""
    _install(scratch)
    _bench.run(scratch.root, "standin")
    path = scratch.root / "validation" / "benchmarks" / "standin.py"
    path.write_text(STANDIN + "\n# edited\n")
    assert [item.name for item in _bench.due(scratch.root)] == ["standin"]


def test_a_program_a_group_claims_is_listed_by_its_group(scratch):
    """A C++ program a group's ``BENCH`` names is listed as ``bench_<name>``."""
    _install(scratch)
    manifest = scratch.build / "sq_groups.json"
    text = manifest.read_text().replace('"bench": []', '"bench": ["thing"]', 1)
    manifest.write_text(text)
    bench = scratch.root / "engine" / "bench"
    bench.mkdir(parents=True)
    (bench / "bench_thing.cpp").write_text("int main() {}\n")
    names = [i.name for i in _bench.due(scratch.root) if i.kind == "bench"]
    assert names == ["standin", "bench_thing"]


def _program(scratch):
    manifest = scratch.build / "sq_groups.json"
    text = manifest.read_text().replace('"bench": []', '"bench": ["thing"]', 1)
    manifest.write_text(text)
    bench = scratch.root / "engine" / "bench"
    bench.mkdir(parents=True)
    (bench / "bench_thing.cpp").write_text("int main() {}\n")
    binary = scratch.root / "engine" / "build" / "release" / "bench" / "bench_thing"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


def test_a_library_edit_makes_a_recorded_script_due(scratch):
    """Editing a module under src/ makes the script that times it due."""
    _install(scratch)
    module = scratch.root / "src" / "sqlearn" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("X = 1\n")
    _bench.run(scratch.root, "standin")
    assert _bench.due(scratch.root) == []
    module.write_text("X = 2\n")
    assert [item.name for item in _bench.due(scratch.root)] == ["standin"]


def test_a_helper_edit_makes_a_recorded_script_due(scratch):
    """Editing a helper under validation/ makes the script that imports it due."""
    _install(scratch)
    helper = scratch.root / "validation" / "helper.py"
    helper.write_text("X = 1\n")
    _bench.run(scratch.root, "standin")
    assert _bench.due(scratch.root) == []
    helper.write_text("X = 2\n")
    assert [item.name for item in _bench.due(scratch.root)] == ["standin"]


def test_a_program_is_due_again_when_its_binary_changes(scratch):
    """A record of a C++ program holds its binary: a rebuilt one is due."""
    _install(scratch)
    binary = _program(scratch)
    _bench.run(scratch.root, "bench_thing")
    benches = [i.name for i in _bench.due(scratch.root) if i.kind == "bench"]
    assert "bench_thing" not in benches
    binary.write_text("#!/bin/sh\nexit 0\n# rebuilt\n")
    benches = [i.name for i in _bench.due(scratch.root) if i.kind == "bench"]
    assert "bench_thing" in benches


def test_a_stale_bench_program_is_refused_with_a_fix(scratch, capsys):
    """A program whose build is out of date is not run, nor rebuilt here."""
    _install(scratch)
    binary = _program(scratch)
    (binary.parent.parent / "stale").write_text("")
    assert _bench.run(scratch.root, "bench_thing") != 0
    out = capsys.readouterr().out
    assert "out of date" in out
    assert "Fix: just bench bench_thing" in out
    assert _checks.load(_checks.record_dir(scratch.root), "bench-bench_thing") == []
    (binary.parent.parent / "stale").unlink()
    assert _bench.run(scratch.root, "bench_thing") == 0


def test_a_missing_bench_build_is_refused_with_the_same_fix(scratch, capsys):
    """No build directory at all: refused, not run."""
    _install(scratch)
    binary = _program(scratch)
    binary.unlink()
    binary.parent.rmdir()
    binary.parent.parent.rmdir()
    assert _bench.run(scratch.root, "bench_thing") != 0
    assert "Fix: just bench bench_thing" in capsys.readouterr().out


def test_a_run_under_load_is_recorded_as_loaded(scratch, monkeypatch):
    """A run that ends on a busy machine keeps ``loaded`` true in its record."""
    _install(scratch)
    monkeypatch.setattr(_load, "now", lambda: 99.0)
    assert _bench.run(scratch.root, "standin") == 0
    records: list[Any] = _checks.load(_checks.record_dir(scratch.root), "bench-standin")
    [record] = records
    assert record["loaded"] is True
    assert not _bench.clean(record)


def test_a_loaded_record_leaves_the_benchmark_due(scratch, monkeypatch):
    """Only a clean record clears ``due``, and a loaded one gives no last numbers."""
    _install(scratch)
    monkeypatch.setattr(_load, "now", lambda: 99.0)
    _bench.run(scratch.root, "standin")
    [item] = _bench.due(scratch.root)
    assert item == _bench.Due("standin", "docs/benchmarks/standin.md", None, None, None)


def test_a_loaded_record_newer_than_a_clean_one_gives_the_clean_numbers(
    scratch, monkeypatch
):
    """Last numbers come from the newest clean record, not a newer loaded one."""
    _install(scratch)
    _bench.run(scratch.root, "standin")
    records: list[Any] = _checks.load(_checks.record_dir(scratch.root), "bench-standin")
    [clean_record] = records
    scratch.write("a/one.cpp", '#include "a/one.hpp"\n// x\nint one() { return 2; }\n')
    monkeypatch.setattr(_load, "now", lambda: 99.0)
    _bench.run(scratch.root, "standin")
    [item] = _bench.due(scratch.root)
    assert item.last_seconds == clean_record["seconds"]
    assert item.last_cores == clean_record["cores"]


def _profile_binary(scratch, text="#!/bin/sh\nexit 0\n"):
    binary = scratch.root / "engine" / "build" / "profile" / "bench" / "bench_thing"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(text)
    return binary


def _save_profile(scratch, loaded=False):
    record = {
        "digest": _bench.profile_identity(scratch.root, "bench_thing"),
        "config": "bench_thing",
        "files": {},
        "seconds": 1.2,
        "loaded": loaded,
    }
    _checks.save(
        _checks.record_dir(scratch.root),
        "profile-bench_thing",
        cast("_checks.Record", record),
    )


def _profiles(scratch):
    return [i for i in _bench.due(scratch.root) if i.kind == "profile"]


def test_a_program_never_profiled_has_its_profile_due(scratch):
    """A program with no profile record is listed after the benchmarks."""
    _install(scratch)
    _program(scratch)
    listed = _bench.due(scratch.root)
    assert [(i.name, i.kind) for i in listed] == [
        ("standin", "bench"),
        ("bench_thing", "bench"),
        ("bench_thing", "profile"),
    ]
    assert _bench.programs(scratch.root) == ["bench_thing"]
    [profile] = _profiles(scratch)
    assert profile.last_seconds is None
    assert _bench._line(profile) == "profile bench_thing  never run"


def test_a_profile_is_due_while_its_benchmark_is_not(scratch):
    """A clean benchmark record does not clear the profile."""
    _install(scratch)
    _program(scratch)
    _bench.run(scratch.root, "bench_thing")
    listed = [(i.name, i.kind) for i in _bench.due(scratch.root)]
    assert ("bench_thing", "bench") not in listed
    assert ("bench_thing", "profile") in listed


def test_a_clean_profile_record_clears_the_profile(scratch):
    """A clean record with the current identity leaves nothing due for it."""
    _install(scratch)
    _program(scratch)
    _profile_binary(scratch)
    _save_profile(scratch)
    assert _profiles(scratch) == []


def test_a_loaded_profile_record_leaves_the_profile_due(scratch):
    """A loaded record clears nothing and gives no last numbers."""
    _install(scratch)
    _program(scratch)
    _profile_binary(scratch)
    _save_profile(scratch, loaded=True)
    [profile] = _profiles(scratch)
    assert profile.last_seconds is None


def test_a_profile_is_due_again_when_its_binary_changes(scratch):
    """The record holds the profile binary: a rebuilt one is due, with its time."""
    _install(scratch)
    _program(scratch)
    binary = _profile_binary(scratch)
    _save_profile(scratch)
    assert _profiles(scratch) == []
    binary.write_text("#!/bin/sh\nexit 0\n# rebuilt\n")
    [profile] = _profiles(scratch)
    assert profile.last_seconds == 1.2
    assert _bench._line(profile) == "profile bench_thing  last 1.2 s"


def test_a_script_has_no_profile_due(scratch):
    """The stand-in script lists only its benchmark."""
    _install(scratch)
    assert [(i.name, i.kind) for i in _bench.due(scratch.root)] == [
        ("standin", "bench")
    ]
