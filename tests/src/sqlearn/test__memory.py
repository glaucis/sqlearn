"""Tests of the memory budget: what a hand-over may use, and its estimate."""

import warnings

import duckdb
import pytest

import sqlearn as sq
from sqlearn import _memory
from sqlearn._config import connection
from sqlearn._memory import (
    allowance,
    budget,
    duckdb_limit,
    estimate,
    parse,
    physical,
)
from sqlearn.errors import SqlearnError, SqlearnWarning


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("61.0 MiB", 61 * 2**20),
        ("12.7 GiB", int(12.7 * 2**30)),
        ("16383.9 PiB", int(16383.9 * 2**50)),
        ("64MB", 64 * 10**6),
        ("8GB", 8 * 10**9),
        ("2 kb", 2000),
        ("3KiB", 3 * 1024),
        ("1TB", 10**12),
        ("512 bytes", 512),
        ("100B", 100),
    ],
)
def test_parse_reads_the_byte_strings_duckdb_reads_and_prints(text, size):
    """Powers of 1000 for KB to TB, of 1024 for KiB to PiB."""
    assert parse(text) == pytest.approx(size, rel=1e-9)


@pytest.mark.parametrize("text", ["", "lots", "8 XB", "-1GB", "GB"])
def test_parse_refuses_what_is_not_a_size(text):
    """A string that is not a size names the forms it takes."""
    with pytest.raises(SqlearnError, match="8GB"):
        parse(text)


def test_physical_memory_is_found():
    """The machine's memory, more than a gigabyte on any machine this runs on."""
    assert physical() > 10**9


def test_the_budget_is_four_fifths_of_physical_memory_by_default():
    """Without `memory=`, 80% of physical memory."""
    assert budget() == int(0.8 * physical())


def test_the_budget_is_the_configured_memory():
    """`set_config(memory=...)` is the budget."""
    sq.set_config(memory="4GB")
    assert budget() == 4 * 10**9


def test_duckdb_limit_reads_the_connections_memory_limit():
    """The connection's limit, as DuckDB prints it, in bytes."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '1GB'")
    assert duckdb_limit(con) == pytest.approx(10**9, rel=0.01)


def test_the_shared_connections_allowance_is_half_the_budget():
    """On sqlearn's own connection DuckDB takes half; the hand-over the rest."""
    sq.set_config(memory="4GB")
    assert allowance(connection()) == pytest.approx(2 * 10**9, rel=0.01)


def test_a_passed_connections_allowance_is_the_budget_minus_its_limit():
    """A smaller limit than half the budget leaves the hand-over the rest."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '32MB'")
    sq.set_config(connection=con, memory="64MB")
    assert allowance(con) == pytest.approx(32 * 10**6, rel=0.05)


def test_a_passed_default_connection_counts_as_half_the_budget():
    """DuckDB's own default limit (80%) counts as half the budget (Ruling R11)."""
    con = duckdb.connect()
    sq.set_config(connection=con)
    with pytest.warns(SqlearnWarning, match="memory_limit of about"):
        assert allowance(con) == budget() - budget() // 2


def test_an_unlimited_connection_counts_as_half_the_budget():
    """An unlimited `memory_limit` counts as half the budget (Ruling R11)."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '-1'")
    sq.set_config(connection=con)
    with pytest.warns(SqlearnWarning, match="no memory_limit"):
        assert allowance(con) == budget() - budget() // 2


def test_the_estimate_counts_a_number_twice_over():
    """A number is 8 bytes, counted twice: the fetch's peak holds two copies."""
    rel = connection().sql("SELECT i::DOUBLE AS a, i AS b FROM range(1000) t(i)")
    assert estimate(rel, ["a", "b"], "pandas") == 1000 * 2 * 16
    assert estimate(rel, ["a", "b"], "numpy") == 1000 * 2 * (16 + 1)


def test_the_estimate_counts_text_by_its_average_length():
    """A text value is 64 bytes plus its average length, twice; a NULL too."""
    rel = connection().sql(
        "SELECT * FROM (VALUES ('ab', 1.0), ('abcd', 2.0), (NULL, 3.0)) v(s, a)"
    )
    assert estimate(rel, ["s", "a"], "pandas") == 3 * 2 * (64 + 3) + 3 * 16


def test_a_nested_column_is_counted_as_its_text():
    """A list, struct or blob is 64 bytes plus its text's length, twice; never 8."""
    rel = connection().sql(
        "SELECT [1, 2, 3] AS l, {'q': 10} AS st, 'ab'::BLOB AS bl FROM range(10)"
    )
    # [1, 2, 3] is 9 characters, {'q': 10} is 9, the blob 'ab' is 2.
    assert estimate(rel, ["l"], "pandas") == 10 * 2 * (64 + 9)
    assert estimate(rel, ["st"], "pandas") == 10 * 2 * (64 + 9)
    assert estimate(rel, ["bl"], "pandas") == 10 * 2 * (64 + 2)


def test_the_estimate_of_no_columns_or_no_rows_is_zero():
    """Nothing to hand over is nothing to hold."""
    rel = connection().sql("SELECT 'x' AS s, 1.0 AS a WHERE false")
    assert estimate(rel, ["s", "a"], "numpy") == 0
    assert estimate(rel, [], "numpy") == 0


def test_physical_memory_is_capped_by_the_cgroup_limit(tmp_path, monkeypatch):
    """In a container, cgroup v2's memory.max is the machine's memory."""
    limit = tmp_path / "memory.max"
    monkeypatch.setattr(_memory, "CGROUP", limit)
    machine = physical()  # no such file: the machine's own
    limit.write_text("1000000\n")
    assert physical() == 1_000_000
    limit.write_text(f"{machine * 2}\n")
    assert physical() == machine
    limit.write_text("max\n")
    assert physical() == machine


def test_the_estimate_counts_a_flat_mask_byte_for_numpy_and_the_stream():
    """numpy and the stream count one byte a value for a mask, NULL or not."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0, 1.0), (NULL, 2.0), (3.0, 3.0)) v(a, b)"
    )
    for feed in ("numpy", "stream"):
        assert estimate(rel, ["a", "b"], feed) == 3 * (16 + 1) * 2
    assert estimate(rel, ["a", "b"], "arrow") == 3 * 16 * 2


def test_a_number_only_estimate_reads_the_row_count_alone(monkeypatch):
    """With no text column, the estimate's query is count(*) and nothing else."""
    seen = []
    real = duckdb.DuckDBPyRelation.aggregate

    def spy(self, expressions, *args):
        seen.append([str(e) for e in expressions])
        return real(self, expressions, *args)

    monkeypatch.setattr(duckdb.DuckDBPyRelation, "aggregate", spy)
    rel = connection().sql("SELECT i::DOUBLE AS a, i AS b FROM range(10) t(i)")
    estimate(rel, ["a", "b"], "numpy")
    assert seen == [["count(*)"]]


def test_a_cgroup_limit_of_zero_is_no_limit(tmp_path, monkeypatch):
    """A memory.max of 0 is not a limit of no memory: the machine's is kept."""
    limit = tmp_path / "memory.max"
    monkeypatch.setattr(_memory, "CGROUP", limit)
    machine = physical()
    limit.write_text("0\n")
    assert physical() == machine


def test_a_passed_connection_above_half_the_budget_warns_once():
    """DuckDB's limit over half the budget: one warning per process, with a fix."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '3GB'")
    sq.set_config(connection=con, memory="4GB")
    with pytest.warns(SqlearnWarning, match=r"memory_limit.*SET memory_limit"):
        allowance(con)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        allowance(con)  # once per process: no second warning


def test_a_passed_connection_within_half_the_budget_does_not_warn():
    """A limit of half the budget or less is DuckDB's share as counted."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '1GB'")
    sq.set_config(connection=con, memory="4GB")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        allowance(con)
