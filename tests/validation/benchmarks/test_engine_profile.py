"""The engine profile: the reading of DuckDB's profiles, and a probe's run."""

import json
from pathlib import Path

from validation.benchmarks.engine_profile import parse_profiles, run
from validation.benchmarks.gram_batches import _write


def _profile(sql: str) -> dict[str, object]:
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


def test_a_failed_probe_is_reported_not_raised(tmp_path: Path):
    """A probe on a missing file gives a failure with its error, not a raise."""
    result = run("scale", tmp_path / "missing.parquet", profiled=False)
    assert result["s"] == "failed"
    assert result["error"]
