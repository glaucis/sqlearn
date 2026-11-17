"""Tests of the aggregates: values a step takes, expressions it learns."""

import math
import pickle
import statistics

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE

import sqlearn as sq
from sqlearn._compose import SOURCE, execute, step_stage
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.agg.aggregates import lookup, present
from sqlearn.errors import SqlearnError
from validation import _cases

NAN = float("nan")
X = duckdb.ColumnExpression("a")


class Learn(sq.Step):
    """Learn one aggregate, given as a value, of each column; apply leaves it."""

    def __init__(self, cols=None, value=sq.agg.median, keep=False, suffix=None):
        """Set the settings."""
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.value = value

    def learn(self, x):
        """Learn the aggregate."""
        return {"v": self.value(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def learn(values, aggregate, kind="DOUBLE"):
    """Return what `aggregate` learns from column ``a`` holding `values`."""
    con = connection()
    con.execute(f"CREATE OR REPLACE TABLE t (a {kind})")
    con.executemany("INSERT INTO t VALUES (?)", [[v] for v in values])
    pipe = sq.Pipeline([("learn", Learn(cols=["a"], value=aggregate))])
    return pipe.learn(con.table("t"))["learn"].v_["a"]


def test_an_aggregate_is_a_value_and_a_builder():
    """Without a column it is a value; with one it is the expression."""
    assert repr(sq.agg.median) == "sq.agg.median"
    assert repr(sq.agg.quantile(q=0.9)) == "sq.agg.quantile(q=0.9)"
    assert isinstance(sq.agg.quantile(X, q=0.9), duckdb.Expression)
    assert isinstance(sq.agg.quantile(q=0.9)(X), duckdb.Expression)
    with pytest.raises(SqlearnError, match="q"):
        sq.agg.quantile(X)


def test_the_repr_sorts_params_and_leaves_defaults_out():
    """Defaults are not printed; the rest is sorted by name."""
    assert repr(sq.agg.quantile(q=0.9, method="linear")) == "sq.agg.quantile(q=0.9)"
    assert (
        repr(sq.agg.quantile(q=0.5, method="averaged_inverted_cdf"))
        == "sq.agg.quantile(method='averaged_inverted_cdf', q=0.5)"
    )
    assert repr(sq.agg.iqr(q=(0.25, 0.75))) == "sq.agg.iqr"
    assert repr(sq.agg.iqr(q=(0.1, 0.9))) == "sq.agg.iqr(q=(0.1, 0.9))"


def test_equal_aggregates_share_a_store_key():
    """Equal aggregates built apart are equal, hash alike, and learn once."""
    assert sq.agg.quantile(q=0.9) == sq.agg.quantile(q=0.9)
    assert hash(sq.agg.quantile(q=0.9)) == hash(sq.agg.quantile(q=0.9))
    assert sq.agg.quantile(q=0.9) != sq.agg.quantile(q=0.8)
    assert sq.agg.quantile(q=1) == sq.agg.quantile(q=1.0)
    data = connection().sql("SELECT * FROM (VALUES (1.0), (2.0)) t(a)")
    for _ in range(2):
        built = Learn(cols=["a"], value=sq.agg.quantile(q=0.9))
        sq.Pipeline([("learn", built)]).learn(data)
    assert STORE.learns["learn"] == 1
    other = Learn(cols=["a"], value=sq.agg.quantile(q=0.8))
    sq.Pipeline([("learn", other)]).learn(data)
    assert STORE.learns["learn"] == 2


def test_an_aggregate_equals_only_aggregates():
    """A string is not an aggregate (lookup turns one into it); a list is a pair."""
    assert sq.agg.median != "median"
    assert sq.agg.iqr(q=[0.1, 0.9]) == sq.agg.iqr(q=(0.1, 0.9))


def test_an_aggregate_built_by_hand():
    """One's own aggregate: a name and a build; it keeps the class docstring."""
    double = sq.agg.Aggregate("double", lambda x: x * sq.fn.const(2))
    assert repr(double) == "sq.agg.double"
    assert str(double(X)) == '("a" * 2)'
    assert double.__doc__ == sq.agg.Aggregate.__doc__


def test_strings_name_aggregates():
    """A string naming an aggregate is that aggregate; others are not."""
    assert lookup("median") is sq.agg.median
    assert lookup("quantile") is sq.agg.quantile
    assert lookup("unknown") is None


def test_numeric_only_marks_the_aggregates_needing_numbers():
    """mode, min, max, count and distinct take any type; the rest numbers."""
    general = {"mode", "min", "max", "count", "distinct"}
    every = [
        "mean",
        "median",
        "quantile",
        "approx_quantile",
        "iqr",
        "mode",
        "min",
        "max",
        "range",
        "maxabs",
        "std",
        "var",
        "count",
        "distinct",
    ]
    for name in every:
        aggregate = getattr(sq.agg, name)
        assert aggregate.name == name
        assert lookup(name) is aggregate
        assert aggregate.numeric_only is (name not in general)


def test_a_bad_param_is_refused():
    """An unknown param, a q out of range or another method is refused."""
    with pytest.raises(SqlearnError, match=r"median.*'q'"):
        sq.agg.median(q=0.5)
    with pytest.raises(SqlearnError, match=r"between 0 and 1"):
        sq.agg.quantile(q=1.5)
    with pytest.raises(SqlearnError, match=r"between 0 and 1"):
        sq.agg.quantile(q=True)
    with pytest.raises(SqlearnError, match=r"'linear'.*'averaged_inverted_cdf'"):
        sq.agg.quantile(q=0.5, method="nearest")
    with pytest.raises(SqlearnError, match=r"iqr.*pair"):
        sq.agg.iqr(q=(0.75, 0.25))
    with pytest.raises(SqlearnError, match=r"iqr.*not a pair"):
        sq.agg.iqr(q=0.5)
    with pytest.raises(SqlearnError, match=r"by keyword"):
        sq.agg.quantile(0.9)  # ty: ignore[no-matching-overload]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            [1.0, 2.0, 3.0, 4.0],
            {"median": 2.5, "q90": 3.7, "iqr": 1.5, "range": 3.0, "maxabs": 4.0},
        ),
        (
            [1.0, None, NAN, 3.0],
            {"median": 2.0, "q90": 2.8, "iqr": 1.0, "range": 2.0, "maxabs": 3.0},
        ),
    ],
)
def test_aggregates_leave_missing_out(values, expected):
    """Each aggregate learns from the present values, as numpy computes them."""
    present_values = np.array([v for v in values if v is not None and v == v])
    numpy = {
        "median": np.median(present_values),
        "q90": np.quantile(present_values, 0.9),
        "iqr": np.quantile(present_values, 0.75) - np.quantile(present_values, 0.25),
        "range": np.ptp(present_values),
        "maxabs": np.max(np.abs(present_values)),
        "mean": np.mean(present_values),
        "std": np.std(present_values),
        "var": np.var(present_values),
        "min": np.min(present_values),
        "max": np.max(present_values),
        "count": len(present_values),
    }
    aggregates = {
        "median": sq.agg.median,
        "q90": sq.agg.quantile(q=0.9),
        "iqr": sq.agg.iqr,
        "range": sq.agg.range,
        "maxabs": sq.agg.maxabs,
        "mean": sq.agg.mean,
        "std": sq.agg.std,
        "var": sq.agg.var,
        "min": sq.agg.min,
        "max": sq.agg.max,
        "count": sq.agg.count,
    }
    for name, aggregate in aggregates.items():
        got = learn(values, aggregate)
        assert got == pytest.approx(numpy[name]), name
        if name in expected:
            assert got == pytest.approx(expected[name]), name


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        ("('b'), ('a'), (NULL), ('b'), ('NULL')", ["NULL", "a", "b"]),
        ("(2.0), ('NaN'::DOUBLE), (-0.0), (0.0), ('NaN'::DOUBLE)", [0.0, 2.0]),
        ("(NULL::VARCHAR)", []),
    ],
)
def test_distinct_values_are_sorted_without_null_and_nan(rows, want):
    """Each value once, sorted; NULL and NaN are not values."""
    rel = duckdb.connect().sql(f"SELECT * FROM (VALUES {rows}) t(x)")
    got = rel.aggregate([sq.agg.distinct(duckdb.ColumnExpression("x"))])
    assert str(got.fetchall()) == str([(want,)])


def test_distinct_values_of_no_rows_is_empty():
    """No rows, no values: an empty list, not NULL."""
    rel = duckdb.connect().sql("SELECT 'a' AS x WHERE false")
    got = rel.aggregate([sq.agg.distinct(duckdb.ColumnExpression("x"))])
    assert got.fetchall() == [([],)]


def test_distinct_values_need_memory_for_the_values_not_the_rows():
    """Five million rows of three categories are learned within 16 MB.

    Collecting every row into a list first (``list(x)``) needs about 80 MB
    here and fails.
    """
    con = duckdb.connect()
    con.execute("SET memory_limit = '16MB'")
    con.execute("SET threads = 1")
    rel = con.sql("SELECT (i % 3)::VARCHAR AS x FROM range(5000000) t(i)")
    got = rel.aggregate([sq.agg.distinct(duckdb.ColumnExpression("x"))])
    assert got.fetchall() == [(["0", "1", "2"],)]
    with pytest.raises(duckdb.OutOfMemoryException):
        rel.aggregate("list(x)").fetchall()


def test_distinct_leaves_null_and_nan_out():
    """The sorted distinct values, without NULL and NaN."""
    assert learn([2.0, NAN, 1.0, None, 2.0], sq.agg.distinct) == [1.0, 2.0]
    assert learn(["b", None, "a", "b"], sq.agg.distinct, "VARCHAR") == ["a", "b"]
    assert learn([None], sq.agg.distinct, "VARCHAR") == []


def test_aggregates_of_text_keep_its_type():
    """mode, min, max, count and distinct read text as text."""
    words = ["b", None, "a", "c"]
    assert learn(words, sq.agg.min, "VARCHAR") == "a"
    assert learn(words, sq.agg.max, "VARCHAR") == "c"
    assert learn(words, sq.agg.count, "VARCHAR") == 3


def test_mode_ties_go_to_the_smallest():
    """The most frequent value; a tie goes to the smallest, as scikit-learn."""
    assert learn(["b", "a", "b", "a", "c"], sq.agg.mode, "VARCHAR") == "a"
    assert learn([3, 1, 1, 3], sq.agg.mode, "INTEGER") == 1
    assert learn([2.0, NAN, NAN, NAN, None, None, 2.0, 5.0], sq.agg.mode) == 2.0
    assert learn(["10", "9", "9", "10"], sq.agg.mode, "VARCHAR") == "10"


@pytest.mark.parametrize("q", [0.0, 0.1, 0.25, 0.3, 0.5, 0.6, 0.75, 0.9, 1.0, 1 / 3])
@pytest.mark.parametrize("method", ["linear", "averaged_inverted_cdf"])
@pytest.mark.parametrize("n", [1, 2, 3, 4, 7, 10])
def test_quantiles_match_numpy(q, method, n):
    """Each method gives numpy's quantile of the same name."""
    values = [float(v) for v in np.random.default_rng(n).normal(0.0, 1.0, n)]
    got = learn(values, sq.agg.quantile(q=q, method=method))
    want = np.quantile(np.array(values), q, method=method)
    assert got == pytest.approx(want, rel=1e-15, abs=1e-15)


def test_a_linear_quantile_interpolates_as_numpy_does():
    """From a weight of 0.5, numpy interpolates down from the high value.

    ``lo + w * (hi - lo)`` and numpy's ``hi - (hi - lo) * (1 - w)`` differ
    by an ULP here, so this one is equal only by numpy's form.
    """
    values = [float(v) for v in np.random.default_rng(6).random(100)]
    assert learn(values, sq.agg.quantile(q=0.07)) == np.quantile(values, 0.07)
    assert learn(values, sq.agg.quantile(q=0.93)) == np.quantile(values, 0.93)


def test_the_median_is_the_linear_middle_quantile():
    """median is quantile(q=0.5) in value, and DuckDB's median exactly."""
    values = [0.1, 0.7, 0.2, 0.3000000001, 1e300, -1e300]
    want = (
        duckdb.connect()
        .sql(
            f"SELECT median(a) FROM (VALUES {', '.join(f'({v})' for v in values)}) t(a)"
        )
        .fetchall()[0][0]
    )
    assert learn(values, sq.agg.median) == want
    assert learn(values, sq.agg.quantile(q=0.5)) == want


def test_aggregates_of_integers_and_decimals_are_double():
    """The quantiles read integer and decimal columns as DOUBLE."""
    assert learn([7, 3, 9, 4], sq.agg.median, "INTEGER") == 5.5
    assert isinstance(learn([1, 2], sq.agg.quantile(q=0.3), "BIGINT"), float)
    assert learn([1.25, 2.5], sq.agg.median, "DECIMAL(10,2)") == 1.875


def test_approx_quantile_is_close():
    """approx_quantile is DuckDB's own: near the exact one, not equal by promise."""
    values = [float(v) for v in range(1, 1001)]
    got = learn(values, sq.agg.approx_quantile(q=0.5))
    assert abs(got - 500.5) < 10
    with pytest.raises(SqlearnError, match="q"):
        sq.agg.approx_quantile(X)


@pytest.mark.parametrize(
    "aggregate",
    [
        sq.agg.mean,
        sq.agg.median,
        sq.agg.quantile(q=0.9),
        sq.agg.iqr,
        sq.agg.mode,
        sq.agg.min,
        sq.agg.max,
        sq.agg.range,
        sq.agg.maxabs,
        sq.agg.std,
        sq.agg.var,
    ],
    ids=repr,
)
def test_no_present_value_gives_null(aggregate):
    """Every value missing: the aggregate is NULL (the step decides what then)."""
    assert learn([None, NAN], aggregate) is None


def test_count_of_no_present_value_is_zero():
    """count counts the present values: none is 0."""
    assert learn([None, NAN], sq.agg.count) == 0


def test_present_nulls_nan_and_null_and_casts_to_double():
    """NaN and NULL both become NULL; the rest is DOUBLE."""
    rel = connection().sql("SELECT * FROM (VALUES (1), (NULL), (3)) t(a)")
    assert rel.select(present(X)).fetchall() == [(1.0,), (None,), (3.0,)]
    nan = connection().sql("SELECT 'NaN'::DOUBLE AS a")
    assert nan.select(present(X)).fetchall() == [(None,)]


class Spread(sq.Step):
    """Learn the IQR and the median of each column."""

    def learn(self, x):
        """Learn both."""
        return {"iqr": sq.agg.iqr(x), "med": sq.agg.median(x)}

    def apply(self, x, learned):
        """Centre and divide."""
        return (x - learned.med) / learned.iqr


def test_quantile_markers_inside_an_expression_share_one_sort():
    """Two columns' IQRs and medians: six quantiles, one sort."""
    con = duckdb.connect()
    con.sql(
        "CREATE TABLE t AS SELECT * FROM "
        "(VALUES (1.0, 10.0), (2.0, 40.0), (3.0, 20.0), (4.0, NULL)) v(a, b)"
    )
    schema = [("a", DOUBLE), ("b", DOUBLE)]
    stage = step_stage(1, "spread", Spread(), schema, SOURCE)
    values, rel, run = execute(con, "t", [stage], produce=True)
    learn_sql = run.statements[0]
    assert learn_sql.count("row_number()") == 1
    assert "__sqlearn_quantile" not in learn_sql
    assert values["s01_spread"]["iqr"] == {"a": 1.5, "b": 15.0}
    assert values["s01_spread"]["med"] == {"a": 2.5, "b": 20.0}
    assert rel is not None
    assert rel.fetchall()[0] == (-1.0, -2 / 3)


def test_mode_is_counted_not_sorted():
    """A learn stage with a mode groups by value; it has no window."""
    con = duckdb.connect()
    con.sql("CREATE TABLE t AS SELECT * FROM (VALUES ('b'), ('a'), ('b')) v(c)")

    class Most(sq.Step):
        def learn(self, x):
            return {"mode": sq.agg.mode(x), "n": sq.agg.count(x)}

        def apply(self, x, learned):
            return x

    stage = step_stage(1, "most", Most(), [("c", DOUBLE)], SOURCE)
    values, _, run = execute(con, "t", [stage], produce=False)
    assert "row_number()" not in run.statements[0]
    assert "GROUP BY" in run.statements[0]
    assert values["s01_most"] == {"mode": {"c": "b"}, "n": {"c": 3}}


def test_infinity_is_a_value_to_the_quantiles():
    """Infinity is present (only NaN and NULL are missing); Impute refuses it."""
    assert learn([1.0, math.inf, 2.0], sq.agg.median) == 2.0


def test_an_aggregate_pickles_by_name_and_params():
    """A step holding an aggregate can be pickled: it comes back equal."""
    for a in (sq.agg.median, sq.agg.quantile(q=0.9), sq.agg.iqr(q=(0.1, 0.9))):
        back = pickle.loads(pickle.dumps(a))
        assert back == a and repr(back) == repr(a)


def test_std_is_within_two_ulps_of_the_exact_value_on_100k_rows():
    """The validation's 100,000 values near 1,000: two passes, within 2 ULPs.

    DuckDB's one-pass ``stddev_pop`` was 12 ULPs from the exact population
    standard deviation (mpmath at 50 digits) here; numpy is 1 (issue #28).
    """
    (large,) = (d for d in _cases.numbers() if d.name == "large")
    values = _cases.present(large.values)
    exact = _cases.nearest(_cases.exact_stddev_pop(values))
    data = pd.DataFrame({"a": values})
    got = sq.Pipeline([("learn", Learn(value=sq.agg.std))]).learn(data)
    assert _cases.ulps(got["learn"].v_["a"], exact) <= 2


@pytest.mark.parametrize(
    ("value", "n"), [(1 / 3, 100_000), (0.1, 3), (1e300, 7), (1000.123, 1)]
)
def test_std_of_a_constant_column_is_exactly_zero(value, n):
    """Every value the same, or one value: exactly 0, whatever the mean rounds to.

    The compensated mean of 100,000 copies of 1/3 is not 1/3 itself, so the
    deviations from it are not 0; Scale's zero-spread rule needs 0 here.
    """
    data = pd.DataFrame({"a": [value] * n + [None, NAN]})
    got = sq.Pipeline([("learn", Learn(value=sq.agg.std))]).learn(data)
    assert got["learn"].v_["a"] == 0.0


def test_var_is_the_two_pass_population_variance():
    """The validation's 100,000 values near 1,000: within 2 ULPs of the exact one.

    DuckDB's one-pass ``var_pop`` was 20 ULPs from it here (issue #42); the
    learn statement holds the variance marker's stages, not ``var_pop``.
    """
    (large,) = (d for d in _cases.numbers() if d.name == "large")
    values = _cases.present(large.values)
    exact = _cases.nearest(_cases.exact_variance(values))
    data = pd.DataFrame({"a": values})
    pipe = sq.Pipeline([("learn", Learn(value=sq.agg.var))]).learn(data)
    assert _cases.ulps(pipe["learn"].v_["a"], exact) <= 2
    con = duckdb.connect()
    con.sql("CREATE TABLE t AS SELECT * FROM (VALUES (1.0), (2.0), (6.0)) v(a)")
    stage = step_stage(1, "v", Learn(value=sq.agg.var), [("a", DOUBLE)], SOURCE)
    _, _, run = execute(con, "t", [stage], produce=False)
    assert "var_pop" not in run.statements[0]
    assert "_std_means" in run.statements[0]


@pytest.mark.parametrize("n", [100_000, 1])
def test_var_of_a_constant_column_is_exactly_zero(n):
    """Every value 1/3, or one value: exactly 0, whatever the mean rounds to."""
    data = pd.DataFrame({"a": [1 / 3] * n + [None, NAN]})
    got = sq.Pipeline([("learn", Learn(value=sq.agg.var))]).learn(data)
    assert got["learn"].v_["a"] == 0.0


def test_var_and_std_of_one_column_share_their_passes():
    """One pair of passes holds both: the std is exactly the root of the var."""

    class Both(sq.Step):
        def learn(self, x):
            return {"var": sq.agg.var(x), "std": sq.agg.std(x)}

        def apply(self, x, learned):
            return x

    con = duckdb.connect()
    con.sql("CREATE TABLE t AS SELECT * FROM (VALUES (1.0), (2.0), (6.5)) v(a)")
    stage = step_stage(1, "both", Both(), [("a", DOUBLE)], SOURCE)
    values, _, run = execute(con, "t", [stage], produce=False)
    got = values["s01_both"]
    assert got["std"]["a"] == math.sqrt(got["var"]["a"])  # ty: ignore[invalid-argument-type]
    assert "var_pop" not in run.statements[0]
    assert run.statements[0].count("_std_means") == 2  # its definition, one use


def test_std_is_two_passes_and_may_sit_anywhere_in_a_learned_value():
    """Inside another aggregate, beside a median, in an expression: numpy's values.

    The learn statement holds no ``stddev_pop``: the two passes are stages
    of their own, shared by every standard deviation of the stage.
    """

    class Spreads(sq.Step):
        def learn(self, x):
            return {
                "ratio": sq.agg.mean(x / sq.agg.std(x)),
                "both": sq.agg.std(x) * sq.fn.const(2) + sq.agg.median(x),
                "sd": sq.agg.std(x),
            }

        def apply(self, x, learned):
            return x

    con = duckdb.connect()
    con.sql(
        "CREATE TABLE t AS SELECT * FROM "
        "(VALUES (1.0, 4.0), (2.0, NULL), (6.0, 5.0)) v(a, b)"
    )
    schema = [("a", DOUBLE), ("b", DOUBLE)]
    stage = step_stage(1, "spreads", Spreads(), schema, SOURCE)
    values, _, run = execute(con, "t", [stage], produce=False)
    assert "stddev_pop" not in run.statements[0]
    assert "__sqlearn_std" not in run.statements[0]
    got = values["s01_spreads"]
    for column, present_values in {"a": [1.0, 2.0, 6.0], "b": [4.0, 5.0]}.items():
        v = np.array(present_values)
        assert got["sd"][column] == pytest.approx(np.std(v), rel=1e-15)
        assert got["ratio"][column] == pytest.approx(np.mean(v / np.std(v)), rel=1e-15)
        assert got["both"][column] == pytest.approx(
            2 * np.std(v) + np.median(v), rel=1e-15
        )


def test_std_of_an_expression_holding_a_median_is_learned():
    """``std(x - median(x))`` reads the median's stage: the base's value comes back.

    The deviations from a constant spread as the values do, so it is also
    ``std(x)``; inside another aggregate too.
    """
    values = [1.0, 2.0, 6.0, 10.0]
    data = pd.DataFrame({"a": values})
    step = _Learns(lambda x: sq.agg.std(x - sq.agg.median(x)))
    got = sq.Pipeline([("std", step)]).learn(data)["std"].v_["a"]
    assert _cases.ulps(got, 3.5619517121937516) <= 2

    class Ratio(sq.Step):
        def learn(self, x):
            deviation = x - sq.agg.median(x)
            return {"r": sq.agg.mean(deviation / sq.agg.std(deviation))}

        def apply(self, x, learned):
            return x

    ratio = sq.Pipeline([("ratio", Ratio())]).learn(data)["ratio"].r_["a"]
    v = np.array(values)
    want = np.mean((v - np.median(v)) / np.std(v))
    assert ratio == pytest.approx(want, rel=1e-15)


class _Learns(sq.Step):
    """Learn the one expression `build` makes of each column."""

    def __init__(self, build=sq.agg.std, cols=None, keep=False, suffix=None):
        """Set the settings."""
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.build = build

    def learn(self, x):
        """Learn the expression."""
        return {"v": self.build(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def _learned(build, values):
    """Return what a step learning `build` of column ``a`` learns from `values`."""
    data = pd.DataFrame({"a": values})
    return sq.Pipeline([("learn", _Learns(build))]).learn(data)["learn"].v_["a"]


def _mad(x):
    """Return the median absolute deviation of `x`, as sqlearn learns it."""
    return sq.agg.median(sq.fn.abs(x - sq.agg.median(x)))


def test_the_median_absolute_deviation_is_learned():
    """The median of the distances from the median: inner first, then outer."""
    assert _learned(_mad, [1.0, 2.0, 3.0, 4.0, 100.0]) == 1.0
    v = np.random.default_rng(0).normal(5, 2, 1_000)
    assert _learned(_mad, v) == np.median(np.abs(v - np.median(v)))


def test_a_mode_of_an_expression_holding_a_median_is_learned():
    """The most frequent distance from the median, rounded down."""

    def build(x):
        return sq.agg.mode(duckdb.FunctionExpression("floor", x - sq.agg.median(x)))

    v = [1.0, 2.0, 2.0, 7.0, 7.0, 7.0]
    assert _learned(build, v) == statistics.mode(np.floor(np.array(v) - np.median(v)))


SAMPLE = np.random.default_rng(1).normal(5, 2, 1_000)
"""1,000 normal values: numpy's two-pass results are the reference."""

NESTED_ULPS = 4
"""A nested value against numpy's: each side rounds the inner value (a
standard deviation within 2 ULPs, ADR 0044), and the outer one carries that
rounding on, squared in a variance, so two bounds add up."""


@pytest.mark.parametrize(
    ("build", "numpy"),
    [
        (lambda x: sq.agg.std(x - sq.agg.std(x)), lambda v: np.std(v - np.std(v))),
        (
            lambda x: sq.agg.median(x / sq.agg.std(x)),
            lambda v: np.median(v / np.std(v)),
        ),
        (lambda x: sq.agg.var(sq.agg.std(x) * x), lambda v: np.var(np.std(v) * v)),
    ],
    ids=["std of std", "median of std", "var of std"],
)
def test_a_std_inside_another_aggregate_is_learned(build, numpy):
    """Within `NESTED_ULPS` of numpy: the inner rounding carries on."""
    for values in ([1.0, 2.0, 6.0], SAMPLE):
        got = _learned(build, values)
        assert _cases.ulps(got, float(numpy(np.asarray(values)))) <= NESTED_ULPS


@pytest.mark.parametrize(
    ("build", "numpy"),
    [
        (lambda x: sq.agg.std(x - sq.agg.mean(x)), lambda v: np.std(v - np.mean(v))),
        (lambda x: sq.agg.var(x - sq.agg.mean(x)), lambda v: np.var(v - np.mean(v))),
        (
            lambda x: sq.agg.median(x - sq.agg.mean(x)),
            lambda v: np.median(v - np.mean(v)),
        ),
    ],
    ids=["std", "var", "median"],
)
def test_a_plain_aggregate_inside_a_staged_one_is_learned(build, numpy):
    """The inner mean is learned first; numpy's values within `NESTED_ULPS`."""
    for values in ([1.0, 2.0, 6.0], SAMPLE):
        got = _learned(build, values)
        assert _cases.ulps(got, float(numpy(np.asarray(values)))) <= NESTED_ULPS


def test_a_mode_of_an_expression_holding_a_plain_aggregate_is_learned():
    """The most frequent distance from the mean, rounded down."""

    def build(x):
        return sq.agg.mode(duckdb.FunctionExpression("floor", x - sq.agg.mean(x)))

    v = np.array([1.0, 2.0, 2.0, 7.0, 7.0, 7.0])
    assert _learned(build, v) == statistics.mode(np.floor(v - np.mean(v)))


def test_an_approximate_median_is_close_to_the_exact_one():
    """On 100,000 normal values the approximation is within 1% of a std."""
    values = np.random.default_rng(0).normal(5, 2, 100_000)
    exact = learn(values, sq.agg.median)
    approx = learn(values, sq.agg.median(approx=True))
    assert abs(approx - exact) < 0.01 * values.std()
    assert abs(exact - np.median(values)) < 1e-9


def test_an_approximate_median_sits_inside_a_larger_expression():
    """``mean(x) - median(x, approx=True)`` learns."""
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    got = learn(values, lambda x: sq.agg.mean(x) - sq.agg.median(x, approx=True))
    assert got == pytest.approx(4.0 - 3.0, abs=0.5)


def test_an_approximate_median_of_integers_is_a_double_as_the_exact_one():
    """On INTEGER values both medians are DOUBLE, as the docstring says."""
    exact = learn([1, 2, 3, 4], sq.agg.median, kind="INTEGER")
    approx = learn([1, 2, 3, 4], sq.agg.median(approx=True), kind="INTEGER")
    assert type(exact) is float
    assert type(approx) is float
    assert 2.0 <= approx <= 3.0


def test_an_approximate_median_of_nulls_only_is_null():
    """No present value, no median."""
    assert learn([None, None], sq.agg.median(approx=True)) is None


def test_the_approx_param_of_the_median_is_a_bool_and_prints():
    """A non-bool is refused; the default prints bare, approx=True prints."""
    assert repr(sq.agg.median) == "sq.agg.median"
    assert repr(sq.agg.median(approx=False)) == "sq.agg.median"
    assert repr(sq.agg.median(approx=True)) == "sq.agg.median(approx=True)"
    with pytest.raises(SqlearnError, match="approx"):
        sq.agg.median(approx="yes")
