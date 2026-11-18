"""Tests of SplitMix64 in SQL and its Python reference."""

import duckdb
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.datasets._random import normal, random_columns, splitmix64, uniform

GOLDEN = 0x9E3779B97F4A7C15


def test_splitmix64_matches_its_published_values():
    """The first three outputs of a stream from state 0 are the published ones."""
    outputs = [splitmix64(k * GOLDEN % 2**64) for k in range(3)]
    assert outputs == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_sql_uniforms_equal_the_python_reference():
    """The SQL uniforms and normals equal the Python ones bit for bit."""
    rows = connection().sql(random_columns(7, 1000, {"u": 3}, {"n": 5})).fetchall()
    assert [r[0] for r in rows] == list(range(1000))
    assert [r[1] for r in rows] == [uniform(7, i, 3) for i in range(1000)]
    assert [r[2] for r in rows] == [normal(7, i, 5) for i in range(1000)]


def test_negative_and_large_seeds_match_the_python_reference():
    """A seed is taken modulo 2**64 in SQL as in Python, negatives included."""
    for seed in (-1, -(2**70), 2**64 + 3):
        rows = connection().sql(random_columns(seed, 5, {"u": 0}, {})).fetchall()
        assert [r[1] for r in rows] == [uniform(seed, i, 0) for i in range(5)]


def test_random_sql_grows_linearly():
    """The SQL's length grows in proportion to the columns, not faster."""

    def length(n: int) -> int:
        return len(random_columns(0, 10, {f"u{k}": k for k in range(n)}, {}))

    assert length(1) < length(10) < length(100)
    assert length(100) / length(10) < 12


def test_the_same_seed_gives_the_same_values_on_any_thread_count():
    """One thread and eight give the same rows.

    DuckDB's ``range()`` reads on one thread today, so this cannot fail yet: it
    guards a future parallel row source.
    """
    sql = random_columns(11, 100_000, {"u": 0, "v": 1}, {"n": 2})
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        one = con.sql(f"SELECT * FROM ({sql}) ORDER BY i").fetchall()
        con.execute("SET threads = 8")
        eight = con.sql(f"SELECT * FROM ({sql}) ORDER BY i").fetchall()
    finally:
        con.close()
    assert one == eight


def test_sq_datasets_is_a_group():
    """sq.datasets is importable and listed in sq.__all__."""
    assert "datasets" in sq.__all__
    assert sq.datasets.__name__ == "sqlearn.datasets"


def test_no_random_columns_give_the_rows_alone():
    """Empty mappings give a valid query of the row numbers alone."""
    assert connection().sql(random_columns(0, 3, {}, {})).fetchall() == [
        (0,),
        (1,),
        (2,),
    ]
    assert connection().sql(random_columns(0, 0, {}, {})).fetchall() == []


@pytest.mark.parametrize(
    ("uniforms", "normals", "message"),
    [
        ({"u": 4}, {"n": 2}, "stream 4"),
        ({"u": 5}, {"n": 2}, "stream 5"),
        ({"a": 1, "b": 1}, {}, "share stream 1"),
        ({}, {"a": 3, "b": 3}, "share stream 3"),
        ({"i": 0}, {}, "'i'"),
        ({}, {"i": 0}, "'i'"),
        ({"x": 0}, {"x": 1}, "'x'"),
        ({"u": -1}, {}, "stream -1"),
        ({"u": 2**64}, {}, "stream 18446744073709551616"),
        ({}, {"n": -1}, "stream -1"),
        ({}, {"n": 2**63}, "stream 9223372036854775808"),
    ],
)
def test_streams_breaking_the_contract_are_refused(uniforms, normals, message):
    """Colliding streams, repeated or reserved names, streams out of range."""
    with pytest.raises(ValueError, match=message):
        random_columns(0, 1, uniforms, normals)


def test_the_largest_normal_stream_matches_the_python_reference():
    """A normal stream of 2**63 - 1 uses streams up to 2**64 - 1, in range."""
    stream = 2**63 - 1
    rows = connection().sql(random_columns(1, 3, {}, {"n": stream})).fetchall()
    assert [r[1] for r in rows] == [normal(1, i, stream) for i in range(3)]


def test_a_row_source_gives_the_rows_of_range():
    """A row source standing for ``range`` changes no value."""
    con = connection()
    plain = random_columns(5, 1_000, {"u": 0}, {"n": 1})
    other = random_columns(
        5, 1_000, {"u": 0}, {"n": 1}, row_source="SELECT range FROM range(1000)"
    )
    assert con.sql(plain).fetchall() == con.sql(other).fetchall()


def test_without_a_row_source_the_sql_reads_range():
    """The default SQL is unchanged."""
    assert "FROM range(10)" in random_columns(0, 10, {"u": 0}, {})
