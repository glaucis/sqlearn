"""Tests of the row numbers made from work tickets."""

import duckdb
import pytest

from sqlearn.datasets._tickets import _row_numbers, ticket_rows


@pytest.mark.parametrize("threads", [1, 2, 8])
@pytest.mark.parametrize(
    ("tickets", "rows"),
    [
        (983_040, n)
        for n in (1, 7, 122_879, 122_880, 122_881, 983_039, 983_040, 983_041, 3_000_001)
    ]
    + [(1, n) for n in (1, 4_096, 4_097, 16_777_216 // 8)]
    + [(8, n) for n in (8, 32_768, 32_769, 3_000_001)],
)
def test_work_tickets_number_every_row_once_in_order(threads, tickets, rows):
    """Every row is numbered once, in order, on any thread count."""
    con = duckdb.connect()
    con.execute(f"SET threads = {threads}")
    con.execute(f"CREATE TABLE t AS SELECT range AS ticket FROM range({tickets})")
    got = con.sql(ticket_rows(rows, "t", tickets)).fetchnumpy()["range"]
    assert got.tolist() == list(range(rows))


def test_the_largest_row_count_starts_at_zero():
    """At 2**63 - 1 rows the first rows are 0, 1, 2."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT range AS ticket FROM range(983040)")
    sql = ticket_rows(2**63 - 1, "t", 983_040)
    assert con.sql(f"{sql} LIMIT 3").fetchall() == [(0,), (1,), (2,)]


def test_the_largest_row_count_ends_on_its_last_row():
    """At 2**63 - 1 rows the last rows come out of the last block."""
    rows, tickets = 2**63 - 1, 983_040
    size = -(-rows // tickets)
    scan = f"SELECT {tickets - 1}::HUGEINT * {size} AS a, {size}::HUGEINT AS w"
    sql = _row_numbers(rows, scan, size, lambda s: f"list_reverse({s})")
    assert duckdb.connect().sql(f"{sql} LIMIT 2").fetchall() == [
        (rows - 1,),
        (rows - 2,),
    ]


@pytest.mark.parametrize("fan_out", [2, 3])
@pytest.mark.parametrize(("tickets", "rows"), [(3, 100), (4, 1_001), (5, 997)])
def test_a_small_fan_out_widens_in_several_steps_without_a_gap(
    monkeypatch, fan_out, tickets, rows
):
    """Blocks that do not divide evenly cross several widening steps in order."""
    monkeypatch.setattr("sqlearn.datasets._tickets.FAN_OUT", fan_out)
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t AS SELECT range AS ticket FROM range({tickets})")
    got = con.sql(ticket_rows(rows, "t", tickets)).fetchnumpy()["range"]
    assert got.tolist() == list(range(rows))
