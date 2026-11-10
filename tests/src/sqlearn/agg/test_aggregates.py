"""Tests of the aggregates: values a step takes, expressions it learns."""

import math
import pickle

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


@pytest.mark.parametrize(
    ("build", "why"),
    [
        (
            lambda x: sq.agg.std(x - sq.agg.std(x)),
            "standard deviation of an expression holding another standard "
            "deviation, which cannot be staged",
        ),
        (
            lambda x: sq.agg.median(x / sq.agg.std(x)),
            "quantile, mode or target statistic of an expression holding a "
            "standard deviation, which cannot be staged",
        ),
    ],
    ids=["std of std", "median of std"],
)
def test_a_std_the_stages_cannot_order_is_refused(build, why):
    """Each refusal names the step and why the stages cannot compute it."""
    data = pd.DataFrame({"a": [1.0, 2.0, 6.0]})
    with pytest.raises(sq.errors.StepError, match=r"\(step 1\).*" + why):
        sq.Pipeline([("bad", _Learns(build))]).learn(data)


@pytest.mark.parametrize(
    "build",
    [
        lambda x: sq.agg.std(x - sq.agg.mean(x)),
        lambda x: sq.agg.median(x - sq.agg.mean(x)),
        lambda x: sq.agg.mode(x - sq.agg.mean(x)),
    ],
    ids=["std", "median", "mode"],
)
def test_a_plain_aggregate_inside_a_staged_one_is_refused(build):
    """Each refusal names the step and position, not DuckDB's GROUP BY error."""
    data = pd.DataFrame({"a": [1.0, 2.0, 6.0]})
    with pytest.raises(sq.errors.StepError, match=r"\(step 1\)") as raised:
        sq.Pipeline([("bad", _Learns(build))]).learn(data)
    message = str(raised.value)
    assert message.startswith("bad (step 1)")
    assert "a plain aggregate" in message
    assert "Fix:" in message
    assert "Binder Error" not in message
