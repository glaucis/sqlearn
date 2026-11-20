"""Tests of the environment as a whole."""

import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest


def test_duckdb_answers_a_query():
    """The one runtime dependency imports and computes in this environment."""
    assert duckdb.execute("select sum(range) from range(1000)").fetchone() == (499500,)


def test_the_runtime_dependencies_are_duckdb_and_numpy():
    """The package asks for duckdb and numpy and nothing else (ADR 0057)."""
    requirements = importlib.metadata.requires("sqlearn") or []
    names = [
        re.split(r"[^A-Za-z0-9_.-]", r, maxsplit=1)[0].lower()
        for r in requirements
        if "extra ==" not in r
    ]
    assert sorted(names) == ["duckdb", "numpy"]


@pytest.mark.slow
def test_duckdb_spills_a_query_larger_than_its_memory_limit(tmp_path):
    """DuckDB finishes work larger than its memory limit by spilling to disk."""
    query = """
        select count(*), sum(n) from (
            select k, count(*) as n
            from (select i % 10000000 as k from range(20000000) t(i))
            group by k
        )
    """
    con = duckdb.connect()
    con.execute("set memory_limit = '64MB'")
    con.execute("set threads = 1")
    con.execute("set temp_directory = ''")
    with pytest.raises(duckdb.OutOfMemoryException):
        con.execute(query).fetchone()
    con.execute(f"set temp_directory = '{tmp_path}'")
    assert con.execute(query).fetchone() == (10000000, 20000000)


def test_the_linter_refuses_a_private_function_defined_twice(tmp_path):
    """Ruff's F811 sees `_name` too, not only public names.

    Its default `dummy-variable-rgx` takes any name starting with `_` for a
    throwaway and skips it, and almost every helper here starts with `_`.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""Probe."""\n\n\ndef _helper() -> None:\n    """One."""\n\n\n'
        'def _helper() -> None:\n    """Two."""\n'
    )
    root = Path(__file__).parents[1]
    found = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            root / "pyproject.toml",
            "--select",
            "F811",
            "--output-format",
            "concise",
            probe,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "F811" in found.stdout, found.stdout + found.stderr
