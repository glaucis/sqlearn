"""The engine profile: the reading of DuckDB's profiles, and a probe's run."""

import json
from pathlib import Path
from typing import Any

from validation.benchmarks.engine_profile import _failure, parse_profiles, run
from validation.benchmarks.gram_batches import _write


def _profile(sql: str) -> dict[str, Any]:
    return {
        "query": {"sql": sql, "total_time": 0.5, "cpu_time": 0.4},
        "system": {"peak_buffer_memory": 10, "peak_temp_dir_size": 0},
        "operator": [
            {
                "type": "RESULT_COLLECTOR",
                "timing": 0.01,
                "children": [
                    {
                        "type": "HASH_GROUP_BY",
                        "timing": 0.3,
                        "children": [
                            {"type": "TABLE_SCAN", "timing": 0.1, "children": []}
                        ],
                    }
                ],
            }
        ],
    }


def test_profiles_are_read_in_order_with_their_operators():
    """Each profile in noisy text is read, in order, with operators by time."""
    text = (
        "noise\n"
        + json.dumps(_profile("SELECT 1"))
        + "\nmore\n"
        + json.dumps(_profile("SELECT 2"))
    )
    statements = parse_profiles(text)
    assert len(statements) == 2
    first = statements[0]
    assert first["sql"] == "SELECT 1"
    assert first["seconds"] == 0.5
    assert first["peak_buffer_bytes"] == 10
    assert first["operators"] == [
        ("HASH_GROUP_BY", 0.3),
        ("TABLE_SCAN", 0.1),
        ("RESULT_COLLECTOR", 0.01),
    ]
    assert statements[1]["sql"] == "SELECT 2"


def test_json_without_a_query_is_skipped():
    """JSON that is not a profile gives no statement."""
    assert parse_profiles('{"a": 1}') == []


def test_a_profiled_probe_reports_every_statement(tmp_path: Path):
    """A profiled run of scale splits its time between DuckDB and Python."""
    path = tmp_path / "d.parquet"
    _write(path, 1000, 3)
    result = run("scale", path, profiled=True)
    assert result["s"] > 0
    assert len(result["statements"]) >= 1
    assert 0 <= result["duckdb_s"] <= result["s"]
    assert len(result["python_top"]) <= 5
    assert result["python_s"] >= 0
    assert all(s["operators"] for s in result["statements"])
    assert not any("current_setting" in s["sql"] for s in result["statements"])


def test_a_failed_probe_is_reported_not_raised(tmp_path: Path):
    """A probe on a missing file gives a failure with its error, not a raise."""
    result = run("scale", tmp_path / "missing.parquet", profiled=False)
    assert result["s"] == "failed"
    # The error is cut to 80 characters, so a long path may not show: name
    # what is robust, the missing file.
    assert "No file matches" in result["error"]


def test_a_failure_names_the_error_not_the_profile_json():
    """The cause is the last line outside any profile JSON on stderr."""
    stderr = "Traceback\nValueError: boom\n" + json.dumps(
        _profile("SELECT 1"), indent=2
    )
    assert _failure(1, stderr) == "ValueError: boom"
    assert len(_failure(1, "x" * 200)) == 80
    assert _failure(1, "") == "no error"


def test_a_probe_killed_by_a_signal_is_named():
    """A negative return code is a signal, reported with its number."""
    assert _failure(-9, "") == "killed by signal 9"


def test_an_unprofiled_probe_reports_its_time(tmp_path: Path):
    """A timing run, with no profiling, finishes and reports its seconds."""
    path = tmp_path / "d.parquet"
    _write(path, 1000, 3)
    result = run("scale", path, profiled=False)
    assert result["s"] > 0
    assert result["peak_gb"] > 0


def test_a_failure_skips_nanobinds_leak_report_after_the_traceback():
    """DuckDB's leak lines come after the traceback; the exception is named."""
    stderr = (
        "Traceback (most recent call last):\n"
        "ValueError: boom\n"
        "nanobind: leaked 27 instances!\n"
        'nanobind: leaked 1 types!\n - leaked type "T"\n'
        ' - leaked function "__init__"\n'
        "nanobind: this is likely caused by a reference counting issue.\n"
        "See https://nanobind.readthedocs.io/en/latest/refleaks.html"
    )
    assert _failure(1, stderr) == "ValueError: boom"
    glued = (
        "ValueError: boom\nSee https://nanobind.readthedocs.io/en/latest/refleaks.html"
    )
    assert _failure(1, glued) == "ValueError: boom"
