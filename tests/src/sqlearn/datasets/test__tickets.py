"""Tests of the row numbers made from work tickets."""

import threading

import duckdb
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnWarning
from sqlearn.datasets._tickets import (
    ROW_GROUP,
    _make_table,
    _row_numbers,
    row_source,
    ticket_rows,
)


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


@pytest.mark.parametrize("before", [True, False])
def test_a_users_schema_named_like_the_tickets_database_is_not_in_the_way(before):
    """A schema meta_sqlearn made before or after a relation was built is fine."""
    con = duckdb.connect()
    sq.set_config(connection=con)
    if before:
        con.execute("CREATE SCHEMA meta_sqlearn")
    first = sq.datasets.blobs(rows=100)
    if not before:
        con.execute("CREATE SCHEMA meta_sqlearn")
    assert first.fetchall() == sq.datasets.blobs(rows=100, parallel=False).fetchall()
    assert sq.datasets.blobs(rows=100).fetchall() == first.fetchall()


def _source() -> str:
    sql = row_source(10, True)
    assert sql is not None
    return sql


def _ticket_tables(con) -> list[str]:
    return sorted(
        r[0]
        for r in con.sql(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE lower(database_name) = 'meta_sqlearn'"
        ).fetchall()
    )


def test_more_threads_add_a_larger_ticket_table():
    """A higher thread count adds a bigger ticket table beside the old one."""
    con = connection()
    con.execute("SET threads = 2")
    sq.datasets.blobs(rows=10).fetchall()
    assert _ticket_tables(con) == ["tickets_8"]
    con.execute("SET threads = 9")
    sq.datasets.blobs(rows=10).fetchall()
    assert _ticket_tables(con) == ["tickets_8", "tickets_9"]
    count = con.sql("SELECT count(*) FROM meta_sqlearn.tickets_9").fetchall()
    assert count == [(9 * ROW_GROUP,)]
    assert "tickets_9" in _source()


def test_a_relation_keeps_its_rows_when_threads_rise():
    """A relation built before the threads rose reads the same rows after."""
    con = connection()
    con.execute("SET threads = 2")
    rel = sq.datasets.blobs(rows=1_000, seed=4)
    before = rel.fetchall()
    con.execute("SET threads = 9")
    sq.datasets.blobs(rows=10).fetchall()
    assert rel.fetchall() == before


def test_a_transaction_that_cannot_see_a_new_table_still_gets_every_row(tmp_path):
    """Rows come from the largest table the transaction sees."""
    con = duckdb.connect(tmp_path / "work.duckdb")
    sq.set_config(connection=con)
    con.execute("SET threads = 2")
    sq.datasets.blobs(rows=10).fetchall()
    con.execute("BEGIN")
    con.sql("SELECT count(*) FROM meta_sqlearn.tickets_8").fetchall()
    con.execute("SET threads = 9")
    assert "tickets_8" in _source()
    assert "tickets_9" not in _source()
    rel = sq.datasets.blobs(rows=1_000_000, n_features=1, seed=5)
    plain = sq.datasets.blobs(rows=1_000_000, n_features=1, seed=5, parallel=False)
    assert rel.fetchall() == plain.fetchall()
    con.execute("ROLLBACK")
    assert "tickets_9" in _ticket_tables(con)


def test_two_python_threads_may_make_the_first_ticket_table_at_once():
    """Eight Python threads making the first ticket table meet no conflict.

    The threads share one connection, which refuses a second call while busy
    (even without tickets), so only the table-making is called at once.
    """
    con = duckdb.connect()
    start, errors = threading.Barrier(8), []

    def work():
        try:
            start.wait()
            _make_table(con)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert _ticket_tables(con) == ["tickets_8"]


def test_each_connection_has_its_own_meta_sqlearn():
    """Two connections make their own ticket tables and agree on the rows."""
    first, second = duckdb.connect(), duckdb.connect()
    sq.set_config(connection=first)
    rel = sq.datasets.blobs(rows=10, seed=1)
    sq.set_config(connection=second)
    other = sq.datasets.blobs(rows=10, seed=1)
    assert rel.fetchall() == other.fetchall()


def test_building_a_generator_keeps_the_users_unfinished_result():
    """A result the user has begun to read is still there after a generator."""
    con = connection()
    con.execute("SELECT * FROM range(5)")
    assert con.fetchone() == (0,)
    sq.datasets.blobs(rows=10)
    assert con.fetchall() == [(1,), (2,), (3,), (4,)]


def _falls_back() -> None:
    with pytest.warns(SqlearnWarning) as caught:
        rel = sq.datasets.blobs(rows=100, seed=1)
    text = str(caught[0].message)
    assert all(w in text for w in ("meta_sqlearn", "Why:", "Fix:", "parallel=False"))
    assert "meta_sqlearn" not in rel.sql_query()
    assert (
        rel.fetchall() == sq.datasets.blobs(rows=100, seed=1, parallel=False).fetchall()
    )


@pytest.mark.parametrize(
    "table",
    [
        "SELECT 1 AS mine",
        "SELECT range AS ticket FROM range(5)",  # tickets_8 of the wrong size
        "SELECT 983039 - range AS ticket FROM range(983040)",  # reversed
        "SELECT range::INT AS ticket FROM range(983040)",  # of the wrong type
        "SELECT NULL::BIGINT AS ticket FROM range(983040)",  # all NULL
        "SELECT if(range % 2 = 0, range, NULL)::BIGINT AS ticket "
        "FROM range(983040)",  # partly NULL
    ],
)
def test_a_foreign_database_in_memory_is_left_alone(table):
    """An in-memory meta_sqlearn that is not sqlearn's is not read or written."""
    con = connection()
    con.execute("ATTACH ':memory:' AS meta_sqlearn")
    con.execute(f"CREATE TABLE meta_sqlearn.tickets_8 AS {table}")
    _falls_back()
    assert _ticket_tables(con) == ["tickets_8"]


def test_a_foreign_database_file_is_left_alone(tmp_path):
    """A file attached as meta_sqlearn is not written to."""
    con = connection()
    con.execute(f"ATTACH '{tmp_path / 'other.duckdb'}' AS meta_sqlearn")
    _falls_back()
    assert _ticket_tables(con) == []


@pytest.mark.parametrize("kind", ["attached file", "attached memory", "main file"])
def test_a_database_named_in_another_case_is_left_alone(tmp_path, kind):
    """DuckDB ignores case in database names: META_SQLEARN is not sqlearn's."""
    path = tmp_path / "META_SQLEARN.duckdb"
    if kind == "main file":
        con = duckdb.connect(path)
        sq.set_config(connection=con)
    else:
        con = connection()
        source = path if kind == "attached file" else ":memory:"
        con.execute(f"ATTACH '{source}' AS META_SQLEARN")
    _falls_back()
    assert _ticket_tables(con) == []


def test_a_failure_to_make_tickets_falls_back():
    """When DuckDB cannot make the table the generators run on one thread."""
    con = duckdb.connect()
    sq.set_config(connection=con)
    con.execute("SET temp_directory = ''; SET memory_limit = '1MB'")
    with pytest.warns(SqlearnWarning, match="meta_sqlearn") as caught:
        rel = sq.datasets.blobs(rows=100, seed=1)
    con.execute("SET memory_limit = '200MB'")
    assert "Fix:" in str(caught[0].message)
    assert "meta_sqlearn" not in rel.sql_query()


def test_after_a_detach_the_next_generator_attaches_again():
    """Detaching meta_sqlearn breaks old relations, not new generators."""
    con = connection()
    old = sq.datasets.blobs(rows=10)
    con.execute("DETACH meta_sqlearn")
    with pytest.raises(duckdb.Error):
        old.fetchall()
    assert sq.datasets.blobs(rows=10).count("*").fetchall() == [(10,)]


def test_a_connection_that_sees_no_ticket_table_falls_back():
    """A transaction begun before any ticket table gets the warning too."""
    con = duckdb.connect()
    sq.set_config(connection=con)
    con.execute("ATTACH ':memory:' AS meta_sqlearn")
    con.execute("BEGIN")
    con.sql("SELECT count(*) FROM duckdb_tables()").fetchall()
    _falls_back()
    con.execute("ROLLBACK")
