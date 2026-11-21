"""Tests of `sq.explore.profile`: the counts every column gets."""

import importlib
import math

import duckdb
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._memory import duckdb_limit
from sqlearn.errors import SqlearnError

# `sqlearn.explore.profile` the attribute is the function; this is the module.
module = importlib.import_module("sqlearn.explore.profile")

COLUMNS = [
    "column", "type", "rows", "missing", "missing_share", "distinct",
    "distinct_share", "mean", "std", "min", "q25", "median", "q75", "max",
    "zeros", "negative", "infinite", "skewness", "kurtosis", "min_length",
    "max_length", "first", "last", "exact", "notes",
]  # fmt: skip


def test_a_profile_has_one_row_per_column_in_input_order():
    """A profile has one row per column in input order."""
    result = sq.explore.profile(pd.DataFrame({"b": [1, 2], "a": ["x", "y"]}))
    assert result.columns == COLUMNS
    assert [row[0] for row in result.fetchall()] == ["b", "a"]


def test_missing_counts_null_and_nan():
    """Missing counts null and nan."""
    con = connection()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1.0::DOUBLE), (NULL),"
                " ('NaN'::DOUBLE), (4.0::DOUBLE)) v(x)")  # fmt: skip
    row = dict(zip(COLUMNS, sq.explore.profile("t").fetchall()[0], strict=True))
    assert row["rows"] == 4
    assert row["missing"] == 2
    assert row["missing_share"] == 0.5
    assert row["distinct"] == 2
    assert row["distinct_share"] == 1.0
    assert row["type"] == "DOUBLE"
    assert row["exact"] is True
    assert row["notes"] == []


def test_columns_differing_only_by_case_each_get_a_row(tmp_path):
    """Columns differing only by case each get a row."""
    path = tmp_path / "case.csv"
    path.write_text("a,A\n1,2\n1,3\n")
    rows = sq.explore.profile(str(path)).fetchall()
    # DuckDB reads the second as A_1, the name sqlearn sees everywhere
    assert [row[0] for row in rows] == ["a", "A_1"]
    assert [row[COLUMNS.index("distinct")] for row in rows] == [1, 2]


def test_keyword_and_quoted_names_are_profiled():
    """Keyword and quoted names are profiled."""
    connection().execute("""CREATE TABLE k AS SELECT 1 AS "select", 'v' AS "it's" """)
    rows = sq.explore.profile("k").fetchall()
    assert [row[0] for row in rows] == ["select", "it's"]
    assert [row[2] for row in rows] == [1, 1]


def test_a_name_that_is_not_a_column_is_refused():
    """A name that is not a column is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.explore.profile(pd.DataFrame({"a": [1]}), cols="nope")


def test_a_selector_choosing_nothing_gives_no_rows():
    """A selector choosing nothing gives no rows."""
    frame = pd.DataFrame({"a": ["x"]})
    assert sq.explore.profile(frame, sq.cols.numeric()).fetchall() == []


def test_no_rows_gives_zero_rows_and_null_shares():
    """No rows gives zero rows and null shares."""
    connection().execute("CREATE TABLE e (x INTEGER)")
    row = dict(zip(COLUMNS, sq.explore.profile("e").fetchall()[0], strict=True))
    assert row["rows"] == 0
    assert row["missing"] == 0
    assert row["missing_share"] is None
    assert row["distinct"] == 0
    assert row["distinct_share"] is None


def test_the_profile_outlives_its_frame():
    """The profile outlives its frame."""
    first = sq.explore.profile(pd.DataFrame({"a": [1, 2, 3]}))
    sq.explore.profile(pd.DataFrame({"z": [9]}))
    assert first.fetchall()[0][0] == "a"


def test_out_hands_back_the_form_named():
    """Out hands back the form named."""
    result = sq.explore.profile(pd.DataFrame({"a": [1]}), out="pandas")
    assert isinstance(result, pd.DataFrame)


def test_exact_false_says_so():
    """Exact false says so."""
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    rows = sq.explore.profile(frame, exact=False).fetchall()
    assert [row[COLUMNS.index("exact")] for row in rows] == [False, False]


def _row(sql, **kwargs):
    """Profile the single column x of a table built from VALUES `sql`."""
    con = connection()
    con.execute("DROP TABLE IF EXISTS s")
    con.execute(f"CREATE TABLE s AS SELECT * FROM (VALUES {sql}) v(x)")
    rows = sq.explore.profile("s", **kwargs).fetchall()
    return dict(zip(COLUMNS, rows[0], strict=True))


def _close(actual, expected):
    if expected == 0:
        assert math.isclose(actual, expected, abs_tol=1e-12)
    else:
        assert math.isclose(actual, expected, rel_tol=1e-12)


def test_numeric_statistics_follow_pandas():
    """Numeric statistics follow pandas."""
    row = _row("(1.0::DOUBLE), (2.0::DOUBLE), (2.0::DOUBLE), (9.0::DOUBLE), (NULL)")
    series = pd.Series([1.0, 2.0, 2.0, 9.0])
    described = series.describe()
    expected = {
        "mean": described["mean"], "std": described["std"],
        "min": described["min"], "q25": described["25%"],
        "median": described["50%"], "q75": described["75%"],
        "max": described["max"], "skewness": series.skew(),
        "kurtosis": series.kurt(),
    }  # fmt: skip
    for label, value in expected.items():
        _close(row[label], value)
    assert (row["zeros"], row["negative"], row["infinite"]) == (0, 0, 0)
    assert row["min_length"] is None
    assert row["first"] is None


def test_zeros_and_negatives_are_counted():
    """Zeros and negatives are counted."""
    row = _row("(0::DOUBLE), (-1::DOUBLE), (3::DOUBLE), (0::DOUBLE), (0::DOUBLE)")
    assert (row["zeros"], row["negative"]) == (3, 1)


def test_infinite_values_are_counted_and_left_out():
    """Infinite values are counted and left out of the statistics."""
    row = _row("(1.0::DOUBLE), ('inf'::DOUBLE), (3.0::DOUBLE), ('-inf'::DOUBLE)")
    assert row["infinite"] == 2
    assert row["missing"] == 0
    assert row["mean"] == 2.0
    assert row["max"] == 3.0
    assert row["min"] == 1.0
    assert row["negative"] == 0


def test_integers_and_decimals_are_numbers():
    """Integers and decimals are numbers."""
    con = connection()
    con.execute("CREATE TABLE n AS SELECT 1 AS i, 1.25::DECIMAL(10,2) AS d"
                " UNION ALL SELECT 2, 2.25::DECIMAL(10,2)")  # fmt: skip
    rows = {
        r[0]: dict(zip(COLUMNS, r, strict=True))
        for r in sq.explore.profile("n").fetchall()
    }
    assert rows["i"]["mean"] == 1.5
    assert rows["d"]["mean"] == 1.75
    assert rows["d"]["max"] == 2.25


def test_a_boolean_mean_is_its_share_true():
    """A boolean mean is its share true, and nothing else is numeric."""
    row = _row("(true), (false), (true), (NULL)")
    _close(row["mean"], 2 / 3)
    assert row["distinct"] == 2
    for label in ["std", "min", "q25", "median", "q75", "max", "zeros",
                  "negative", "infinite", "skewness", "kurtosis"]:  # fmt: skip
        assert row[label] is None


def test_text_gets_lengths_and_no_numbers():
    """Text gets lengths and no numbers."""
    row = _row("('a'), ('bcd'), (NULL)")
    assert (row["min_length"], row["max_length"]) == (1, 3)
    assert row["mean"] is None
    assert row["first"] is None


def test_dates_get_first_and_last_as_text():
    """Dates get first and last as text."""
    row = _row("(DATE '2024-03-01'), (DATE '2023-01-05'), (NULL)")
    assert (row["first"], row["last"]) == ("2023-01-05", "2024-03-01")
    assert row["mean"] is None
    zoned = _row("(TIMESTAMPTZ '2024-03-01 10:00:00+00')")
    assert zoned["first"] is not None


def test_one_value_has_null_std_and_shape():
    """One value has a null std and shape."""
    row = _row("(5.0::DOUBLE), (NULL)")
    assert row["mean"] == 5.0
    assert row["std"] is None
    assert row["skewness"] is None
    assert row["kurtosis"] is None


def test_an_all_missing_number_has_null_statistics():
    """An all-missing number has null statistics."""
    row = _row("(NULL::DOUBLE), ('NaN'::DOUBLE)")
    assert row["mean"] is None
    assert row["median"] is None
    assert row["zeros"] == 0


def test_approximate_quartiles_are_close():
    """Approximate quartiles are close when exact is False."""
    values = ", ".join(f"({float(i)!r}::DOUBLE)" for i in range(1, 101))
    row = _row(values, exact=False)
    assert abs(row["median"] - 50.5) < 2
    assert row["mean"] == 50.5


def test_the_distinct_share_never_exceeds_one():
    """The distinct share never exceeds one."""
    values = ", ".join(f"({i})" for i in range(50))
    row = _row(values, exact=False)
    assert row["distinct_share"] <= 1.0


def _notes(sql: str, **settings) -> list[list[str]]:
    """Return each column's notes for a table built by `sql`."""
    con = connection()
    con.execute("DROP TABLE IF EXISTS n")
    con.execute(f"CREATE TABLE n AS {sql}")
    return [row[-1] for row in sq.explore.profile("n", **settings).fetchall()]


def test_a_constant_column_is_noted():
    """A constant column is noted."""
    assert _notes("SELECT 1 AS a FROM range(3)") == [["constant"]]
    assert _notes("SELECT 1 AS a FROM range(2) UNION ALL SELECT NULL") == [["constant"]]
    assert _notes("SELECT i % 2 AS a FROM range(4) t(i)") == [[]]


def test_all_missing_is_noted_not_constant():
    """All missing is noted, not constant."""
    assert _notes("SELECT NULL::INTEGER AS a FROM range(3)") == [["all-missing"]]
    assert _notes("SELECT 'NaN'::DOUBLE AS a FROM range(3)") == [["all-missing"]]


def test_no_rows_gets_no_notes():
    """No rows gets no notes."""
    assert _notes("SELECT 1 AS a WHERE false") == [[]]


def test_an_integer_key_is_id_like():
    """An integer key is id-like."""
    assert _notes("SELECT i AS a FROM range(20) t(i)") == [["id-like"]]


def test_nineteen_rows_are_not_id_like():
    """Nineteen rows are not id-like."""
    assert _notes("SELECT i AS a FROM range(19) t(i)") == [[]]


def test_id_rows_counts_non_missing_rows():
    """`id_rows` counts non-missing rows."""
    sql = "SELECT i AS a FROM range(19) t(i) UNION ALL SELECT NULL"
    assert _notes(sql) == [[]]


def test_a_float_column_is_never_id_like():
    """A float column is never id-like."""
    assert _notes("SELECT i * 0.5::DOUBLE AS a FROM range(20) t(i)") == [[]]
    assert _notes("SELECT i::DECIMAL(9, 2) AS a FROM range(20) t(i)") == [[]]


def test_repeats_are_not_id_like():
    """Repeats are not id-like."""
    assert _notes("SELECT i // 2 AS a FROM range(40) t(i)") == [[]]


def test_many_distinct_texts_are_high_cardinality():
    """Many distinct texts are high-cardinality."""
    sql = "SELECT 't' || (i % 51) AS a FROM range(100) t(i)"
    assert _notes(sql) == [["high-cardinality"]]


def test_fifty_distinct_texts_are_not():
    """Fifty distinct texts are not high-cardinality."""
    assert _notes("SELECT 't' || (i % 50) AS a FROM range(100) t(i)") == [[]]


def test_texts_mostly_repeated_are_not_high_cardinality():
    """Texts with at most half the rows distinct are not high-cardinality."""
    assert _notes("SELECT 't' || (i % 51) AS a FROM range(200) t(i)") == [[]]


def test_a_text_key_is_id_like_not_high_cardinality():
    """A text key is id-like, not high-cardinality."""
    assert _notes("SELECT 't' || i AS a FROM range(100) t(i)") == [["id-like"]]


def test_an_integer_is_never_high_cardinality():
    """An integer is never high-cardinality."""
    assert _notes("SELECT i % 51 AS a FROM range(100) t(i)") == [[]]


def test_the_thresholds_are_settings():
    """The thresholds are settings."""
    ids = "SELECT i AS a FROM range({}) t(i)"
    assert _notes(ids.format(5), id_rows=5) == [["id-like"]]
    assert _notes(ids.format(4), id_rows=5) == [[]]
    texts = "SELECT 't' || (i % {}) AS a FROM range(6) t(i)"
    assert _notes(texts.format(4), high_cardinality=3) == [["high-cardinality"]]
    assert _notes(texts.format(3), high_cardinality=3) == [[]]


@pytest.mark.parametrize("setting", ["id_rows", "high_cardinality"])
@pytest.mark.parametrize("value", [-1, 2.5, "5", True, None])
def test_a_bad_threshold_is_refused(setting, value):
    """A threshold that is not a non-negative integer is refused."""
    with pytest.raises(SqlearnError, match=r"Why:.*Fix:"):
        sq.explore.profile(pd.DataFrame({"a": [1]}), **{setting: value})


def test_notes_are_listed_in_one_order():
    """Notes are listed in one order."""
    assert _notes("SELECT 'k' AS a FROM range(1)", id_rows=1) == [
        ["constant", "id-like"]
    ]


@pytest.mark.parametrize("exact", [True, False])
def test_moments_far_from_zero_keep_their_precision(exact):
    """The shape of values far from 0 is that of the same values near 0.

    Moments from deviations about the mean do not cancel as one-pass power
    sums do (DuckDB's own drift by about 4e-9 at an offset of 1e9).
    """
    near = pd.Series([0.0, 1.0, 2.0, 3.0, 10.0, 4.0, float("nan"), float("inf")])
    far = near + 1e9
    row = sq.explore.profile(pd.DataFrame({"x": far}), exact=exact, out="pandas").iloc[
        0
    ]
    finite = near[near.abs() < math.inf]
    assert math.isclose(row["mean"], finite.mean() + 1e9, rel_tol=1e-15)
    assert math.isclose(row["std"], finite.std(), rel_tol=1e-12)
    assert math.isclose(row["skewness"], finite.skew(), rel_tol=1e-12)
    assert math.isclose(row["kurtosis"], finite.kurt(), rel_tol=1e-12)


def _mixed() -> pd.DataFrame:
    """Five columns of four kinds, with repeats, missing and infinite values."""
    return pd.DataFrame(
        {
            "n": [1.5, 2.0, float("nan"), 2.0, -3.0, float("inf")],
            "k": [1, 2, 3, 4, 5, 6],
            "t": ["a", "b", None, "b", "cc", "a"],
            "f": [True, False, True, None, True, False],
            "d": pd.to_datetime(
                ["2020-01-01", "2021-06-01", None, "2020-01-01", "2019-03-04", None]
            ),
        }
    )


def test_groups_give_the_same_profile_as_one_group(monkeypatch):
    """Groups of 2 over 5 columns (the last group partial) match one group."""
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 100)
    whole = sq.explore.profile(_mixed()).fetchall()
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 2)
    grouped = sq.explore.profile(_mixed()).fetchall()
    assert len(whole) == 5
    assert grouped == whole


def test_an_exact_statement_reads_one_group_of_columns(monkeypatch):
    """No statement holds the exact aggregates of more than a group's columns."""
    seen = []
    original = module._fetch

    def spy(source, aggregates):
        joined = ", ".join(aggregates)
        seen.append(joined.count("quantile_cont(") + joined.count("count(DISTINCT"))
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", spy)
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 2)
    sq.explore.profile(_mixed())
    # The scan holds none; three groups hold the 5 distinct counts and the
    # quartiles of the two numbers ("n" and "k" share the first group).
    assert seen == [0, 4, 2, 1]


@pytest.mark.parametrize("exact", [True, False])
def test_scan_blocks_give_the_same_profile_as_one_scan(monkeypatch, exact):
    """Scan blocks of 2 over 5 columns read 2 columns each, and match one."""
    monkeypatch.setattr(module, "_SCAN_COLUMNS", 100)
    whole = sq.explore.profile(_mixed(), exact=exact).fetchall()
    seen = []
    original = module._fetch

    def spy(source, aggregates):
        seen.append(aggregates)
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", spy)
    monkeypatch.setattr(module, "_SCAN_COLUMNS", 2)
    blocked = sq.explore.profile(_mixed(), exact=exact).fetchall()
    assert blocked == whole
    # The scan's statements: neither exact groups nor the deviations' pass.
    scans = [s for s in seen if "count(DISTINCT" not in ", ".join(s)]
    scans = [s for s in scans if "fsum(" not in ", ".join(s)]
    read = [{n for n in "nktfd" if f'"{n}"' in ", ".join(s)} for s in scans]
    assert read == [{"n", "k"}, {"t", "f"}, {"d"}]


def test_a_group_holds_the_columns_the_memory_limit_holds(monkeypatch):
    """A group's columns times rows times bytes a value fit the limit."""
    seen = []
    original = module._fetch

    def spy(source, aggregates):
        joined = ", ".join(aggregates)
        seen.append(joined.count("count(DISTINCT"))
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", spy)
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 100)
    # Six rows of a value this size: the limit holds two columns, not three.
    limit = duckdb_limit(connection())
    monkeypatch.setattr(module, "_VALUE_BYTES", limit // 12)
    sq.explore.profile(_mixed())
    assert seen == [0, 2, 2, 1]
    monkeypatch.setattr(module, "_VALUE_BYTES", limit)
    seen.clear()
    sq.explore.profile(_mixed())
    assert seen == [0, 1, 1, 1, 1, 1]  # at least one column a group


@pytest.mark.parametrize("exact", [True, False])
def test_no_statement_filters_an_aggregate(monkeypatch, exact):
    """Aggregates leave values out by CASE, not FILTER.

    DuckDB gives each filtered aggregate of a statement its own copy of the
    statement's inputs, so a statement's memory, outside memory_limit,
    grows with the square of its columns.
    """
    seen = []
    original = module._fetch

    def spy(source, aggregates):
        seen.extend(aggregates)
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", spy)
    sq.explore.profile(_mixed(), exact=exact)
    assert seen
    assert not [a for a in seen if "FILTER" in a]


def test_an_approximate_profile_is_a_scan_and_its_deviations(monkeypatch):
    """With exact=False the estimates keep a small state: the scan holds them.

    The one statement after the scan sums the numbers' deviations.
    """
    seen = []
    original = module._fetch

    def spy(source, aggregates):
        seen.append(aggregates)
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", spy)
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 2)
    approximate = sq.explore.profile(_mixed(), exact=False).fetchall()
    assert len(seen) == 2
    assert "approx_count_distinct(" in ", ".join(seen[0])
    assert all(a.startswith("fsum(") for a in seen[1])
    exact = sq.explore.profile(_mixed()).fetchall()
    # Five columns this small are counted exactly either way; the estimated
    # quartiles (10:13) interpolate otherwise.
    assert [r[:10] + r[13:-2] for r in approximate] == [
        r[:10] + r[13:-2] for r in exact
    ]


@pytest.mark.parametrize("failing", [0, 1, 2])
def test_running_out_of_memory_is_refused_with_a_fix(monkeypatch, failing):
    """An out-of-memory error in any statement has a Why and a Fix.

    The error is forced by monkeypatching the statement runner to raise
    DuckDB's out-of-memory error at the scan (0) or at a group (1, 2): a
    real one depends on the machine's memory.
    """
    calls = []
    original = module._fetch

    def fail(source, aggregates):
        calls.append(None)
        if len(calls) > failing:
            raise duckdb.OutOfMemoryException("Out of Memory Error: failed")
        return original(source, aggregates)

    monkeypatch.setattr(module, "_fetch", fail)
    monkeypatch.setattr(module, "_EXACT_COLUMNS", 2)
    with pytest.raises(
        SqlearnError, match=r"(?s)Why:.*Fix:.*exact=False.*memory=.*threads.*cols="
    ) as info:
        sq.explore.profile(_mixed())
    assert "failed" in str(info.value)
    assert "`profile`" in str(info.value)


@pytest.mark.parametrize(("cols", "named"), [(["c0"], False), (None, True)])
def test_the_row_groups_named_are_those_of_the_columns_read(
    monkeypatch, tmp_path, cols, named
):
    """The row groups' fix weighs only the columns the failed statement reads.

    A 60-column file's row groups (about 59 MB) are too wide for a 64 MB
    limit on 2 threads; one column's (1 MB) are not, so a statement reading
    only that column does not blame them. The error is forced as above.
    """
    path = tmp_path / "wide.parquet"
    con = duckdb.connect()
    picked = ", ".join(f"random() AS c{i}" for i in range(60))
    con.execute(
        f"COPY (SELECT {picked} FROM range(250000)) TO '{path}' (FORMAT parquet)"
    )
    con.execute("SET memory_limit = '64MB'; SET threads = 2")

    def fail(*_args):
        raise duckdb.OutOfMemoryException("Out of Memory Error: failed")

    monkeypatch.setattr(module, "_fetch", fail)
    previous = connection()
    sq.set_config(connection=con)
    try:
        with pytest.raises(SqlearnError) as info:
            sq.explore.profile(str(path), cols)
    finally:
        sq.set_config(connection=previous)
    assert ("ROW_GROUP_SIZE" in str(info.value)) is named
    if named:
        assert "of the 20 columns it reads" in str(info.value)


def test_an_approximate_profile_out_of_memory_does_not_name_exact(monkeypatch):
    """With exact=False already, the fixes do not name it again."""

    def fail(*_args):
        raise duckdb.OutOfMemoryException("Out of Memory Error: failed")

    monkeypatch.setattr(module, "_fetch", fail)
    with pytest.raises(SqlearnError, match=r"(?s)Why:.*Fix:.*cols=") as info:
        sq.explore.profile(_mixed(), exact=False)
    assert "exact=False" not in str(info.value)
