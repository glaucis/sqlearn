"""Tests of the memory budget: what a hand-over may use, and its estimate."""

import duckdb
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._memory import (
    allowance,
    budget,
    duckdb_limit,
    estimate,
    parse,
    physical,
)
from sqlearn.errors import SqlearnError


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
    assert allowance(con) == budget() - budget() // 2


def test_an_unlimited_connection_counts_as_half_the_budget():
    """An unlimited `memory_limit` counts as half the budget (Ruling R11)."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '-1'")
    sq.set_config(connection=con)
    assert allowance(con) == budget() - budget() // 2


def test_the_estimate_counts_eight_bytes_a_number():
    """Rows times eight bytes per number column."""
    rel = connection().sql("SELECT i::DOUBLE AS a, i AS b FROM range(1000) t(i)")
    assert estimate(rel, ["a", "b"]) == 1000 * 2 * 8


def test_the_estimate_counts_text_by_its_average_length():
    """A text value is 64 bytes plus its average length; a NULL as 64."""
    rel = connection().sql(
        "SELECT * FROM (VALUES ('ab', 1.0), ('abcd', 2.0), (NULL, 3.0)) v(s, a)"
    )
    assert estimate(rel, ["s", "a"]) == 3 * (64 + 3) + 3 * 8


def test_the_estimate_of_no_columns_or_no_rows_is_zero():
    """Nothing to hand over is nothing to hold."""
    rel = connection().sql("SELECT 'x' AS s, 1.0 AS a WHERE false")
    assert estimate(rel, ["s", "a"]) == 0
    assert estimate(rel, []) == 0
