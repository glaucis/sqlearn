"""The benchmarks' due list and the one run, on a scratch repository.

The stand-in benchmark writes ``ran.txt`` in the repository when it runs, so
what ran can be seen. Groups ``a`` and ``b`` are the conftest's; the stand-in
measures group ``a``.
"""

from typing import Any

from validation import _bench, _checks

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
    names = [item.name for item in _bench.due(scratch.root)]
    assert names == ["standin", "bench_thing"]
