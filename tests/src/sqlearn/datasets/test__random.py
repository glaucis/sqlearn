"""Tests of SplitMix64 in SQL and its Python reference."""

import duckdb

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
    """One thread and eight give the same rows."""
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
