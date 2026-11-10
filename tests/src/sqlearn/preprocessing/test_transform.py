"""Tests of sq.transform against numpy and Python's own string methods."""

import math
import pickle

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_allclose, assert_array_equal

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify
from sqlearn.errors import SqlearnError, StepError
from sqlearn.preprocessing.transform import Transform


def data(seed=1, rows=200):
    """Return seeded data: positive floats, signed floats, ints, text."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.exponential(3, rows) + 0.01,
            "b": rng.normal(0, 2, rows),
            "n": rng.integers(-50, 50, rows).astype("int64"),
            "city": rng.choice(["Kyiv", "LIMA", "nuuk", "Oslo"], rows),
        },
    )


def applied(step, frame):
    """Return the frame after the one step, as pandas."""
    return sq.Pipeline([step]).learn(frame).apply(frame, out="pandas")


def test_log_matches_numpy():
    """log is numpy's log on positive values."""
    frame = data()
    got = applied(sq.transform.log("a"), frame)
    assert_allclose(got["a"], np.log(frame["a"]), rtol=1e-15)
    assert got["b"].tolist() == frame["b"].tolist()


def test_sqrt_matches_numpy_and_zero_is_allowed():
    """sqrt is numpy's sqrt; sqrt(0) is 0."""
    frame = data()
    frame.loc[0, "a"] = 0.0
    got = applied(sq.transform.sqrt("a"), frame)
    assert_allclose(got["a"], np.sqrt(frame["a"]), rtol=1e-15)
    assert got["a"][0] == 0.0


def test_log1p_matches_numpy_including_tiny_and_negative_values():
    """log1p is accurate near 0 and for values between -1 and 0."""
    values = [0.0, 1e-20, -1e-20, 1e-10, 1e-5, 0.5, -0.5, -0.999999, 12345.678, 1e300]
    frame = pd.DataFrame({"x": values})
    got = applied(sq.transform.log1p(), frame)
    assert_allclose(got["x"], np.log1p(values), rtol=1e-14)
    assert (
        applied(sq.transform.log1p(), pd.DataFrame({"x": [np.inf]}))["x"][0] == np.inf
    )


@pytest.mark.parametrize(
    ("bounds", "numpy_bounds"),
    [
        ({"lower": -1.5, "upper": 2.5}, (-1.5, 2.5)),
        ({"lower": -1.5}, (-1.5, None)),
        ({"upper": 2.5}, (None, 2.5)),
    ],
)
def test_clip_matches_numpy_with_one_or_two_bounds(bounds, numpy_bounds):
    """clip is numpy's clip; one bound clips on that side only."""
    frame = data()
    got = applied(sq.transform.clip("b", **bounds), frame)
    assert_array_equal(got["b"], np.clip(frame["b"], *numpy_bounds))


def test_clip_keeps_integer_columns_integer_as_numpy():
    """Integer bounds on an integer column give integers; float bounds, DOUBLE."""
    frame = data()
    ints = sq.Pipeline([sq.transform.clip("n", lower=-10, upper=10)]).learn(frame)
    rel = ints.apply(frame)
    assert str(rel.types[2]) == "BIGINT"
    assert_array_equal(rel.df()["n"], np.clip(frame["n"], -10, 10))
    assert np.clip(frame["n"].to_numpy(), -10, 10).dtype == np.int64
    floats = sq.Pipeline([sq.transform.clip("n", lower=-10.5)]).learn(frame)
    assert str(floats.apply(frame).types[2]) == "DOUBLE"
    assert_array_equal(
        floats.apply(frame, out="pandas")["n"], np.clip(frame["n"], -10.5, None)
    )


def test_lower_and_upper_on_text():
    """lower and upper are Python's str.lower and str.upper; text is the default."""
    frame = data()
    low = applied(sq.transform.lower(), frame)
    up = applied(sq.transform.upper(), frame)
    assert low["city"].tolist() == [s.lower() for s in frame["city"]]
    assert up["city"].tolist() == [s.upper() for s in frame["city"]]
    assert low["a"].tolist() == frame["a"].tolist()


@pytest.mark.parametrize("kind", ["INTEGER", "BIGINT", "DECIMAL(10,2)"])
@pytest.mark.parametrize("method", ["log", "log1p", "sqrt"])
def test_integer_and_decimal_columns_give_double(method, kind):
    """Integers and decimals are computed as DOUBLE, as numpy computes floats."""
    con = connection()
    values = np.array([1, 2, 5, 40, 300])
    con.register("_raw", pd.DataFrame({"x": values}))
    rel = con.sql(f"SELECT x::{kind} AS x FROM _raw")
    out = sq.Pipeline([sq.transform(method=method)]).learn(rel).apply(rel)
    assert str(out.types[0]) == "DOUBLE"
    numpy_f = {"log": np.log, "log1p": np.log1p, "sqrt": np.sqrt}[method]
    assert_allclose(out.df()["x"], numpy_f(values.astype(float)), rtol=1e-15)
    con.unregister("_raw")


@pytest.mark.parametrize("method", ["log", "log1p", "sqrt", "clip"])
def test_null_stays_null_and_nan_stays_nan(method):
    """NULL stays NULL and NaN passes as numpy gives it (NaN), in every method."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (2.0), (NULL), ('NaN'::DOUBLE), (3.0)) t(a)"
    )
    step = (
        sq.transform(method=method, lower=0.0, upper=2.5)
        if method == "clip"
        else sq.transform(method=method)
    )
    rows = [r[0] for r in sq.Pipeline([step]).learn(rel).apply(rel).fetchall()]
    assert rows[1] is None
    assert math.isnan(rows[2])
    assert rows[0] is not None and not math.isnan(rows[0])
    assert rows[3] == (2.5 if method == "clip" else rows[3])


def test_text_null_stays_null():
    """lower and upper keep NULL."""
    rel = connection().sql("SELECT * FROM (VALUES ('Ab'), (NULL)) t(c)")
    got = sq.Pipeline([sq.transform.upper()]).learn(rel).apply(rel).fetchall()
    assert got == [("AB",), (None,)]


@pytest.mark.parametrize(
    ("step", "value", "fix"),
    [
        (sq.transform.log, 0.0, "log1p"),
        (sq.transform.log, -3.0, "clip"),
        (sq.transform.log, -math.inf, "clip"),
        (sq.transform.log1p, -1.0, "clip"),
        (sq.transform.log1p, -2.0, "clip"),
        (sq.transform.sqrt, -0.5, "clip"),
        (sq.transform.sqrt, -math.inf, "clip"),
    ],
)
def test_bad_input_is_refused_naming_step_column_and_fix(step, value, fix):
    """A value outside the domain stops the query with a message naming all three."""
    frame = pd.DataFrame({"x": [1.0, value], "y": [1.0, 1.0]})
    pipe = sq.Pipeline([step("x")]).learn(frame)
    with pytest.raises(duckdb.InvalidInputException) as caught:
        pipe.apply(frame).fetchall()
    text = str(caught.value)
    assert f"sq.transform.{step.__name__}" in text
    assert "'x'" in text
    assert fix in text


def test_log_of_zero_is_refused_with_the_fix():
    """log(0) names the column and points to log1p."""
    frame = pd.DataFrame({"visits": [3.0, 0.0]})
    pipe = sq.Pipeline([sq.transform.log("visits")]).learn(frame)
    with pytest.raises(duckdb.InvalidInputException, match=r"'visits'.*log1p"):
        pipe.apply(frame).fetchall()


def test_good_values_next_to_good_values_do_not_raise_and_infinity_passes():
    """Infinity above the domain passes as numpy gives it."""
    frame = pd.DataFrame({"x": [1.0, np.inf]})
    assert applied(sq.transform.log("x"), frame)["x"].tolist() == [0.0, np.inf]
    assert applied(sq.transform.sqrt("x"), frame)["x"].tolist() == [1.0, np.inf]


def test_the_refusal_is_not_raised_for_rows_not_fetched():
    """The error comes when the bad value is met, not when the step is built."""
    frame = pd.DataFrame({"x": [1.0, -1.0]})
    pipe = sq.Pipeline([sq.transform.sqrt("x")]).learn(frame)
    rel = pipe.apply(frame)
    with pytest.raises(duckdb.InvalidInputException):
        rel.fetchall()


def test_clip_with_no_bound_or_inverted_bounds_is_refused():
    """clip needs a bound, and the lower one must not exceed the upper."""
    with pytest.raises(SqlearnError, match="at least one"):
        sq.transform.clip()
    with pytest.raises(SqlearnError, match=r"lower=5.*upper=1"):
        sq.transform.clip(lower=5, upper=1)
    assert sq.transform.clip(lower=2, upper=2).lower == 2


@pytest.mark.parametrize("bad", ["a", True, math.nan, math.inf, [1]])
def test_clip_bounds_must_be_finite_numbers(bad):
    """A bound that is no finite number is refused, naming it."""
    with pytest.raises(SqlearnError, match="lower="):
        sq.transform.clip(lower=bad)


def test_bounds_belong_to_clip_only():
    """lower= and upper= with another method are refused."""
    with pytest.raises(SqlearnError, match="lower=1"):
        sq.transform(method="log", lower=1)
    with pytest.raises(SqlearnError, match="upper=1"):
        sq.transform(method="sqrt", upper=1)


def test_no_method_is_a_type_error_and_a_bad_one_is_refused():
    """There is no default method; an unknown one names the choices."""
    with pytest.raises(TypeError):
        sq.transform()  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        Transform()  # ty: ignore[missing-argument]
    with pytest.raises(SqlearnError, match="not a method"):
        sq.transform(method="custom")
    with pytest.raises(SqlearnError, match=r"sq\.Step"):
        sq.transform(method="custom")


def test_shortcut_equals_general_form():
    """Each shortcut builds the step the general form builds with its method."""
    pairs = [
        (sq.transform.log("a"), sq.transform("a", method="log")),
        (sq.transform.log1p("a"), sq.transform("a", method="log1p")),
        (sq.transform.sqrt("a"), sq.transform("a", method="sqrt")),
        (
            sq.transform.clip("b", lower=-1, upper=1),
            sq.transform("b", method="clip", lower=-1, upper=1),
        ),
        (sq.transform.lower("city"), sq.transform("city", method="lower")),
        (sq.transform.upper("city"), sq.transform("city", method="upper")),
    ]
    frame = data()
    for short, general in pairs:
        assert type(short) is type(general)
        assert short.settings() == general.settings()
        assert repr(short) == repr(general)
        assert short.default_name() == general.default_name()
        a = applied(short, frame)
        b = applied(general, frame)
        assert a.equals(b)


def test_default_columns():
    """Numeric methods take the numeric columns, lower and upper the text ones."""
    frame = data()
    positive = frame.assign(b=frame["b"].abs(), n=frame["n"].abs())
    got = applied(sq.transform.sqrt(), positive)
    assert_allclose(got["a"], np.sqrt(frame["a"]))
    assert got["city"].tolist() == frame["city"].tolist()
    assert_allclose(got["n"], np.sqrt(positive["n"]))
    assert_allclose(got["b"], np.sqrt(positive["b"]))
    low = applied(sq.transform.lower(), frame)
    assert low[["a", "b", "n"]].equals(frame[["a", "b", "n"]])


def test_columns_by_name_list_or_selector():
    """Columns come as names, one list, or cols=; a dict is refused."""
    assert sq.transform.log("a", "b").cols == ["a", "b"]
    assert sq.transform.log(["a", "b"]).cols == ["a", "b"]
    assert sq.transform.clip(cols=sq.cols.numeric(), lower=0).cols == sq.cols.numeric()
    with pytest.raises(SqlearnError, match="twice"):
        sq.transform.log("a", cols="b")
    with pytest.raises(SqlearnError, match="dict"):
        sq.transform({"a": "log"}, method="log")


def test_default_names():
    """A step is named after its method, whatever its bounds."""
    assert sq.transform.log().default_name() == "log"
    assert sq.transform.clip(lower=0).default_name() == "clip"
    assert sq.transform(method="upper").default_name() == "upper"


def test_repr_is_the_shortest_form_that_rebuilds():
    """The repr names the method and only the settings given."""
    cases = {
        "sq.transform.log()": sq.transform.log(),
        "sq.transform.log1p(cols=['a', 'b'])": sq.transform("a", "b", method="log1p"),
        "sq.transform.clip(lower=0)": sq.transform.clip(lower=0),
        "sq.transform.clip(lower=-1.5, upper=2)": sq.transform.clip(
            lower=-1.5, upper=2
        ),
        "sq.transform.clip(cols='b', upper=1, keep=True)": sq.transform.clip(
            "b", upper=1, keep=True
        ),
        "sq.transform.upper(cols='city', suffix='up')": sq.transform.upper(
            "city", suffix="up"
        ),
    }
    for text, step in cases.items():
        assert repr(step) == text
        assert eval(text).settings() == step.settings()


def test_settings_and_declaration():
    """Settings read back under the ``__init__`` names; the step is static."""
    assert sq.transform.clip(lower=0, keep=True).settings() == {
        "cols": None,
        "method": "clip",
        "lower": 0,
        "upper": None,
        "keep": True,
        "suffix": None,
    }
    assert Transform.static is True
    undeclared = type("Undeclared", (Transform,), {"static": None})(method="log")
    assert classify(undeclared, [("a", DOUBLE)]) == "static"
    assert sq.transform.log().learn(sq.fn.const(1.0)) == {}


def test_the_step_pickles():
    """A step pickles and comes back equal (the search copies steps)."""
    step = sq.transform.clip("b", lower=-1, upper=1)
    back = pickle.loads(pickle.dumps(step))
    assert back.settings() == step.settings()
    assert repr(back) == repr(step)


def test_the_group_lists_its_shortcuts():
    """Tab completion lists the shortcuts; the group prints as sq.transform."""
    assert repr(sq.transform) == "sq.transform"
    assert {"log", "log1p", "sqrt", "clip", "lower", "upper"} <= set(dir(sq.transform))
    assert not hasattr(sq.transform, "custom")


def test_the_wrong_kind_of_column_is_refused_by_name():
    """Text under a numeric method, and numbers under lower, are refused."""
    with pytest.raises(StepError, match=r"\(step 1\).*'city'"):
        sq.Pipeline([sq.transform.log("city")]).learn(data())
    with pytest.raises(StepError, match=r"\(step 1\).*'a'"):
        sq.Pipeline([sq.transform.lower("a")]).learn(data())
    with pytest.raises(StepError, match=r"\(step 1\).*'city'"):
        sq.Pipeline([sq.transform.clip("city", lower=0)]).learn(data())


def test_keep_adds_a_column_beside_the_input():
    """With keep, the result goes beside the input, suffixed with the method."""
    frame = data()
    got = applied(sq.transform.log("a", keep=True), frame)
    assert {"a", "a_log"} <= set(got.columns)
    assert got["a"].tolist() == frame["a"].tolist()
    assert_allclose(got["a_log"], np.log(frame["a"]))


def test_reserved_word_and_space_names_work():
    """Columns called ``order`` and ``my col`` transform."""
    frame = pd.DataFrame({"order": [1.0, 4.0], "my col": [9.0, 16.0]})
    got = applied(sq.transform.sqrt(), frame)
    assert got.to_numpy().tolist() == [[1.0, 3.0], [2.0, 4.0]]


def test_chains_into_the_stage_around_it():
    """A static transform runs in the same query as the step after it."""
    frame = data()
    pipe = sq.Pipeline([sq.transform.log("a"), sq.scale.standard("a")]).learn(frame)
    assert len(pipe.runs_) == 1
    expected = np.log(frame["a"])
    assert_allclose(
        pipe.apply(frame, out="pandas")["a"],
        (expected - expected.mean()) / expected.std(ddof=0),
        atol=1e-12,
    )


def test_case_functions_choose_enum_columns_by_default():
    """With no cols=, upper() changes an ENUM column as it does a VARCHAR one."""
    con = connection()
    enum_rel = con.sql("SELECT 'a'::ENUM('a', 'b') AS e, 1 AS n")
    got = (
        sq.Pipeline([sq.transform.upper()])
        .learn(enum_rel)
        .apply(enum_rel, out="pandas")
    )
    assert got["e"].tolist() == ["A"]
    assert got["n"].tolist() == [1]
