"""Tests of the row numbers made from work tickets."""

import duckdb
import pytest

import sqlearn as sq
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


def _on_file(path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS mine (a INT)")
    sq.set_config(connection=con)
    return con


def test_a_database_file_is_left_as_it_was(tmp_path):
    """Generating on a file writes nothing to it."""
    path = tmp_path / "work.duckdb"
    con = _on_file(path)
    con.execute("CHECKPOINT")
    size = path.stat().st_size
    sq.datasets.blobs(rows=100).fetchall()
    con.execute("CHECKPOINT")
    assert path.stat().st_size == size
    con.close()
    tables = duckdb.connect(path).sql("SELECT table_name FROM duckdb_tables()")
    assert tables.fetchall() == [("mine",)]


def test_generators_work_on_a_read_only_database(tmp_path):
    """A read-only connection still gets generated rows."""
    path = tmp_path / "work.duckdb"
    _on_file(path).close()
    sq.set_config(connection=duckdb.connect(path, read_only=True))
    assert sq.datasets.blobs(rows=100).fetchall() == (
        sq.datasets.blobs(rows=100, parallel=False).fetchall()
    )


@pytest.mark.parametrize("wrote_first", [False, True])
@pytest.mark.parametrize(("end", "kept"), [("COMMIT", True), ("ROLLBACK", False)])
def test_an_open_transaction_is_left_alone(tmp_path, wrote_first, end, kept):
    """Generating inside a transaction neither joins nor ends it."""
    con = _on_file(tmp_path / "work.duckdb")
    con.execute("BEGIN")
    if wrote_first:
        con.execute("INSERT INTO mine VALUES (1)")
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]
    con.execute("INSERT INTO mine VALUES (2)")
    con.execute(end)
    count = con.sql("SELECT count(*) FROM mine").fetchall()[0][0]
    assert count == ((1 + wrote_first) if kept else 0)
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]


def test_a_users_own_tickets_table_is_not_read(tmp_path):
    """A table named tickets_8 in the user's database is not the tickets."""
    con = _on_file(tmp_path / "work.duckdb")
    con.execute("CREATE TABLE tickets_8 AS SELECT 'no' AS ticket")
    con.execute("CREATE SCHEMA other; USE work.other")
    assert sq.datasets.blobs(rows=100).fetchall() == (
        sq.datasets.blobs(rows=100, parallel=False).fetchall()
    )


def test_a_cursor_may_be_sqlearns_connection():
    """A cursor works as sqlearn's connection."""
    sq.set_config(connection=duckdb.connect().cursor())
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]


def test_tickets_are_in_order_whatever_the_users_settings():
    """A table made with insertion order off and many threads still reads in order."""
    con = duckdb.connect()
    con.execute("SET threads = 4")
    con.execute("SET preserve_insertion_order = false")
    sq.set_config(connection=con)
    first = sq.datasets.blobs(rows=300_000)
    con.execute("SET preserve_insertion_order = true")
    assert (
        first.fetchall() == sq.datasets.blobs(rows=300_000, parallel=False).fetchall()
    )
