"""Tests of sq.impute against scikit-learn's SimpleImputer and MissingIndicator."""

import datetime
import pickle

import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE, INTEGER, VARCHAR
from numpy.testing import assert_allclose
from sklearn.impute import MissingIndicator, SimpleImputer
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify
from sqlearn.errors import SqlearnError, StepError
from sqlearn.preprocessing.impute import Impute


def holes(seed=0, rows=40):
    """Return seeded data: two float columns with NaN holes, one int column."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "a": rng.normal(10, 3, rows),
            "b": rng.exponential(2, rows),
            "n": rng.integers(0, 50, rows).astype("int64"),
        },
    )
    frame.loc[rng.choice(rows, 7, replace=False), "a"] = np.nan
    frame.loc[rng.choice(rows, 5, replace=False), "b"] = np.nan
    return frame


def people():
    """Return a small frame with gaps in a number and a text column."""
    return pd.DataFrame(
        {
            "age": [30.0, np.nan, 50.0, 40.0, np.nan],
            "income": [1.0, 2.0, 3.0, 4.0, 10.0],
            "city": ["oslo", None, "rome", "oslo", "lima"],
        }
    )


def test_shortcut_equals_general_form():
    """Each shortcut builds the step the general form builds."""
    for a, b in [
        (sq.impute.median("age"), sq.impute("age", value="median")),
        (sq.impute.mean("age"), sq.impute("age", value=sq.agg.mean)),
        (sq.impute.mode("city"), sq.impute("city", value="mode")),
        (sq.impute.constant(0, "s"), sq.impute("s", value=0)),
        (
            sq.impute.indicator("age"),
            sq.impute("age", value=None, indicator=True),
        ),
    ]:
        assert a.settings() == b.settings() and repr(a) == repr(b)


@pytest.mark.parametrize("value", ["median", "mean"])
def test_impute_matches_simple_imputer(value):
    """Filling NaN holes gives the same numbers as scikit-learn's imputer."""
    frame = holes()
    cols = ["a", "b"]
    sk = SimpleImputer(strategy=value).fit(frame[cols])
    pipe = sq.Pipeline([("fill", sq.impute(cols, value=value))])
    got = pipe.learn(frame).apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), sk.transform(frame[cols]), rtol=1e-12)
    assert_allclose([pipe["fill"].value_[c] for c in cols], sk.statistics_, rtol=1e-12)


def test_mode_matches_most_frequent_on_numbers_and_text():
    """``mode`` fills numbers and text as ``strategy="most_frequent"``."""
    frame = pd.DataFrame(
        {
            "n": [3.0, 1.0, np.nan, 3.0, 1.0, 2.0],
            "city": ["rome", "oslo", None, "rome", "oslo", "lima"],
        }
    )
    pipe = sq.Pipeline([sq.impute.mode()]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    sk_n = SimpleImputer(strategy="most_frequent").fit_transform(frame[["n"]])
    city = frame[["city"]].fillna(np.nan)
    sk_city = SimpleImputer(strategy="most_frequent").fit_transform(city)
    assert got["n"].tolist() == sk_n[:, 0].tolist()  # a tie goes to the smallest
    assert got["city"].tolist() == sk_city[:, 0].tolist()
    assert pipe["mode"].value_ == {"n": 1.0, "city": "oslo"}


def test_constant_matches_simple_imputer():
    """``constant(v)`` fills as ``strategy="constant", fill_value=v``."""
    frame = people()
    pipe = sq.Pipeline([sq.impute.constant(0), sq.impute.constant("unknown")])
    got = pipe.learn(frame).apply(frame, out="pandas")
    sk = SimpleImputer(strategy="constant", fill_value=0)
    assert got["age"].tolist() == sk.fit_transform(frame[["age"]])[:, 0].tolist()
    sk = SimpleImputer(strategy="constant", fill_value="unknown")
    city = sk.fit_transform(frame[["city"]].fillna(np.nan))[:, 0].tolist()
    assert got["city"].tolist() == city
    assert list(pipe.named_steps) == ["constant-1", "constant-2"]


def test_impute_a_dict():
    """A dict gives each column its own value, in one step that rebuilds."""
    frame = people()
    step = sq.impute({"age": "median", "income": "mean", "city": "unknown"})
    assert step.settings()["cols"] == ["age", "income", "city"]
    assert step.value == {
        "age": sq.agg.median,
        "income": sq.agg.mean,
        "city": "unknown",
    }
    pipe = sq.Pipeline([step]).learn(frame)
    assert list(pipe.named_steps) == ["impute"]
    got = pipe.apply(frame, out="pandas")
    for col, imputer in [
        ("age", SimpleImputer(strategy="median")),
        ("income", SimpleImputer(strategy="mean")),
        ("city", SimpleImputer(strategy="constant", fill_value="unknown")),
    ]:
        expected = imputer.fit_transform(frame[[col]].fillna(np.nan))[:, 0]
        assert got[col].tolist() == expected.tolist()
    assert repr(step) == (
        "sq.impute({'age': sq.agg.median, 'income': sq.agg.mean, 'city': 'unknown'})"
    )
    assert eval(repr(step)).settings() == step.settings()


def test_a_dict_naming_a_missing_column_is_refused():
    """A misspelt dict key is refused at learn, naming it and the columns."""
    rel = connection().sql("SELECT 1.0 AS age, 2.0 AS income")
    with pytest.raises(StepError, match=r"agee.*'age', 'income'"):
        sq.Pipeline([sq.impute({"agee": "median"})]).learn(rel)


def test_a_dict_and_a_value_together_are_refused():
    """The dict gives the values; ``value=`` beside it is refused."""
    with pytest.raises(SqlearnError, match="dict"):
        sq.impute({"age": "median"}, value="mean")
    with pytest.raises(SqlearnError, match=r"dict.*value='median'"):
        sq.impute({"age": "mean"}, value="median")  # the default, given
    with pytest.raises(SqlearnError, match="cols"):
        Impute(cols=["income"], value={"age": "median"})


def test_a_dict_with_the_indicator_is_refused():
    """A dict step is static: the indicator goes in a step of its own."""
    with pytest.raises(SqlearnError, match=r"indicator=True.*sq\.impute\.indicator"):
        sq.impute({"age": "median"}, indicator=True)


@pytest.mark.parametrize(
    ("step", "match"),
    [
        (sq.impute.constant(datetime.date(2020, 1, 1), "age"), r"'age'.*DOUBLE.*date"),
        (sq.impute.constant(True, "age"), r"'age'.*DOUBLE.*boolean True"),
        (sq.impute("city", value="count"), r"'city'.*VARCHAR.*sq\.agg\.count"),
        (sq.impute("age", value="distinct"), r"'age'.*DOUBLE.*sq\.agg\.distinct"),
        (sq.impute(value="count"), r"'age'.*sq\.agg\.count"),
    ],
)
def test_a_value_that_cannot_fill_the_column_is_refused(step, match):
    """A constant of another type, or count or distinct, is refused at learn."""
    with pytest.raises(StepError, match=match):
        sq.Pipeline([step]).learn(people())


def test_constants_of_other_types_fill_their_own_columns():
    """A bool, date or timestamp fills, by default, only columns of its type."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0, NULL::BOOLEAN, NULL::DATE, NULL::TIMESTAMP),"
        " (NULL, true, DATE '2021-01-01', TIMESTAMP '2021-01-01 10:00')) "
        "t(n, b, d, ts)"
    )
    day, moment = datetime.date(2020, 1, 1), datetime.datetime(2020, 1, 1, 9, 30)
    pipe = sq.Pipeline(
        [sq.impute.constant(False), sq.impute.constant(day), sq.impute.constant(moment)]
    ).learn(rel)
    assert pipe.apply(rel).fetchall() == [
        (1.0, False, day, moment),
        (None, True, datetime.date(2021, 1, 1), datetime.datetime(2021, 1, 1, 10)),
    ]
    assert (
        sq.Pipeline([sq.impute.constant(2, "n")]).learn(rel).apply(rel).fetchall()[1][0]
        == 2.0
    )  # an int fills a DOUBLE column


def test_min_and_max_keep_the_type_of_any_column():
    """``min`` and ``max`` fill text as well as numbers."""
    frame = people()
    got = sq.Pipeline([sq.impute("city", value="max")]).learn(frame)
    assert got.apply(frame, out="pandas")["city"].tolist()[1] == "rome"


def test_a_search_over_a_dict_step_is_refused():
    """Searching a dict step's values is refused, saying to use one step per column."""
    frame = pd.DataFrame(
        {"age": [1.0, np.nan, 3.0, 4.0] * 5, "y": [0, 1, 0, 1] * 5},
    )
    pipe = sq.Pipeline([sq.impute({"age": "median"}), LogisticRegression()])
    search = sq.Search(pipe, params={"impute__value": ["mean"]}, folds=sq.KFold(2))
    with pytest.raises(SqlearnError, match=r"impute__value.*one step per column"):
        search.train(frame, target="y")


def test_indicator_only_where_missing():
    """The indicator column is created only for columns missing a value at learn."""
    frame = people()[["age", "income"]]
    pipe = sq.Pipeline([sq.impute.indicator()]).learn(frame)
    assert pipe.columns_out_ == ["age", "age_missing", "income"]  # beside its column
    got = pipe.apply(frame, out="pandas")
    sk = MissingIndicator().fit(frame)
    assert got["age_missing"].tolist() == sk.transform(frame)[:, 0].astype(int).tolist()
    assert got["age"].isna().sum() == 2  # the input columns are kept as they are
    later = pd.DataFrame({"age": [1.0], "income": [np.nan]})
    assert pipe.apply(later, out="pandas").columns.tolist() == [
        "age",
        "age_missing",
        "income",
    ]


def test_median_with_an_indicator_matches_add_indicator():
    """``indicator=True`` fills and adds ``<column>_missing``, as add_indicator."""
    frame = people()[["age", "income"]]
    pipe = sq.Pipeline([sq.impute.median(indicator=True)]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    sk = SimpleImputer(strategy="median", add_indicator=True).fit_transform(frame)
    assert got.columns.tolist() == ["age", "age_missing", "income"]
    # scikit-learn puts every indicator after the filled columns
    order = ["age", "income", "age_missing"]
    assert_allclose(got[order].to_numpy(dtype=float), sk)
    assert str(pipe.apply(frame).types[1]) == "INTEGER"


def test_literal_text_constant():
    """``sq.fn.const("median")`` is the text, not the aggregate."""
    step = sq.impute("city", value=sq.fn.const("median"))
    assert step.value != sq.agg.median
    assert step.value == "median"
    assert repr(step) == "sq.impute.constant(sq.fn.const('median'), cols='city')"
    assert eval(repr(step)).value != sq.agg.median
    frame = pd.DataFrame({"city": ["oslo", None]})
    got = sq.Pipeline([step]).learn(frame).apply(frame, out="pandas")
    assert got["city"].tolist() == ["oslo", "median"]
    plain = sq.impute("city", value=sq.fn.const("unknown"))
    assert plain.settings() == sq.impute.constant("unknown", "city").settings()


def test_mode_on_text_and_constant_type_mismatch():
    """Mode fills text; a constant of the wrong type is refused, naming both."""
    frame = people()
    got = sq.Pipeline([sq.impute.mode("city")]).learn(frame).apply(frame, out="pandas")
    assert got["city"].tolist() == ["oslo", "oslo", "rome", "oslo", "lima"]
    with pytest.raises(StepError, match=r"'age'.*DOUBLE.*'unknown'"):
        sq.Pipeline([sq.impute.constant("unknown", "age")]).learn(frame)
    with pytest.raises(StepError, match=r"'city'.*VARCHAR.*0"):
        sq.Pipeline([sq.impute.constant(0, "city")]).learn(frame)


def test_mode_of_an_all_missing_column_is_refused():
    """``mode``, as ``mean`` and ``median``, refuses a column with no value."""
    rel = connection().sql("SELECT NULL::VARCHAR AS dead, 'a' AS ok")
    with pytest.raises(StepError, match=r"mode \(step 1\).*'dead'.*every value"):
        sq.Pipeline([sq.impute.mode()]).learn(rel)


def test_constant_fills_an_all_missing_column():
    """A constant needs nothing learned, so an all-missing column is filled."""
    rel = connection().sql("SELECT NULL::DOUBLE AS dead")
    pipe = sq.Pipeline([sq.impute.constant(-1)]).learn(rel)
    assert pipe.apply(rel).fetchall() == [(-1.0,)]


def test_default_columns_follow_the_value():
    """Numbers for an aggregate of numbers; text for text; all for mode."""
    schema = [("n", DOUBLE), ("i", INTEGER), ("city", VARCHAR)]
    assert sq.impute().inputs(schema) == ["n", "i"]
    assert sq.impute.constant(0).inputs(schema) == ["n", "i"]
    assert sq.impute.constant("x").inputs(schema) == ["city"]
    assert sq.impute.mode().inputs(schema) == ["n", "i", "city"]
    assert sq.impute.indicator().inputs(schema) == ["n", "i", "city"]
    assert sq.impute().cols is None


def test_default_names():
    """A step is named after the shortcut its settings match, else impute."""
    assert sq.impute().default_name() == "median"
    assert sq.impute(value="mean").default_name() == "mean"
    assert sq.impute.mode().default_name() == "mode"
    assert sq.impute(value=0).default_name() == "constant"
    assert sq.impute.indicator().default_name() == "indicator"
    assert sq.impute(value=sq.agg.quantile(q=0.9)).default_name() == "impute"
    assert sq.impute({"a": "median"}).default_name() == "impute"


def test_repr_is_the_shortest_form_that_rebuilds():
    """The repr names the shortcut and only the settings that differ."""
    cases = {
        "sq.impute.median()": sq.impute(),
        "sq.impute.mean(cols=['a', 'b'])": sq.impute("a", "b", value="mean"),
        "sq.impute.constant(0, cols='s', keep=True)": sq.impute.constant(
            0, "s", keep=True
        ),
        "sq.impute.indicator(cols='a')": sq.impute.indicator("a"),
        "sq.impute.median(indicator=True)": sq.impute(indicator=True),
        "sq.impute(value=sq.agg.quantile(q=0.9))": sq.impute(
            value=sq.agg.quantile(q=0.9)
        ),
        "sq.impute(value=None)": sq.impute(value=None),
    }
    for text, step in cases.items():
        assert repr(step) == text
        assert eval(text).settings() == step.settings()


def test_a_string_naming_no_aggregate_is_a_constant():
    """``"median"`` is the aggregate; any other string is text."""
    assert sq.impute(value="median").value == sq.agg.median
    assert sq.impute(value="Median").value == "Median"


def test_static_or_dynamic_follows_the_indicator():
    """Without the indicator the step is static; with it, dynamic."""
    plain, flagged = sq.impute(), sq.impute.indicator()
    assert (plain.static, plain.dynamic, plain.creates) == (True, False, None)
    assert (flagged.static, flagged.dynamic, flagged.creates) == (False, True, INTEGER)
    assert classify(plain, [("a", DOUBLE)]) == "static"
    assert classify(flagged, [("a", DOUBLE)]) == "dynamic"


def test_the_step_pickles():
    """A step pickles and comes back equal (the search copies steps)."""
    step = sq.impute("c", value=sq.fn.const("mode"), indicator=True)
    back = pickle.loads(pickle.dumps(step))
    assert back.settings() == step.settings()
    assert repr(back) == repr(step)


def test_the_group_lists_its_shortcuts():
    """Tab completion lists the shortcuts; the group prints as sq.impute."""
    assert repr(sq.impute) == "sq.impute"
    assert {"mean", "median", "mode", "constant", "indicator"} <= set(dir(sq.impute))


def test_names_and_cols_together_are_refused():
    """Positional names and ``cols=`` together are refused."""
    with pytest.raises(SqlearnError, match="cols="):
        sq.impute.median("a", cols=["b"])


def test_median_of_an_even_count_is_the_exact_median():
    """Four values: the median is the mean of the middle two."""
    frame = pd.DataFrame({"a": [1.0, 2.0, 4.0, 10.0, np.nan]})
    got = sq.Pipeline([sq.impute()]).learn(frame).apply(frame, out="pandas")
    assert got["a"].tolist()[-1] == 3.0


def test_impute_treats_nan_as_missing():
    """NULL and NaN both count as missing, and neither counts in the learning."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE), (3.0)) t(a)",
    )
    pipe = sq.Pipeline([("fill", sq.impute.mean())]).learn(rel)
    assert pipe["fill"].value_ == {"a": 2.0}
    assert pipe.apply(rel).fetchall() == [(1.0,), (2.0,), (2.0,), (3.0,)]


def test_integer_columns_come_out_double():
    """An integer column is imputed to DOUBLE, as scikit-learn returns floats."""
    frame = holes()
    frame["n"] = frame["n"].astype("Int64")
    frame.loc[[3, 9], "n"] = pd.NA
    expected = (
        SimpleImputer(strategy="median")
        .fit(frame[["n"]].astype("float64"))
        .transform(frame[["n"]].astype("float64"))
    )
    pipe = sq.Pipeline([("fill", sq.impute.median("n"))]).learn(frame)
    rel = pipe.apply(frame)
    assert str(rel.types[2]) == "DOUBLE"
    got = np.array([[r[2]] for r in rel.fetchall()])
    assert_allclose(got, expected, rtol=1e-12)


def test_default_selects_numeric_columns_only():
    """Text columns are left alone by the default median."""
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0], "city": ["x", "y", "z"]})
    got = sq.Pipeline([sq.impute()]).learn(frame).apply(frame, out="pandas")
    assert got["a"].tolist() == [1.0, 2.0, 3.0]
    assert got["city"].tolist() == ["x", "y", "z"]


def test_keep_adds_a_column_beside_the_input():
    """With keep=True the input stays and ``a_fill`` (step name) is added."""
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
    pipe = sq.Pipeline([("fill", sq.impute(keep=True))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == ["a", "a_fill"]
    assert got["a_fill"].tolist() == [1.0, 2.0, 3.0]


def test_keep_with_an_indicator():
    """With keep=True and the indicator, the input stays beside both new columns."""
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
    pipe = sq.Pipeline([("fill", sq.impute(keep=True, indicator=True))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == ["a", "a_fill", "a_missing"]  # input, then its two
    assert got["a_fill"].tolist() == [1.0, 2.0, 3.0]
    flags = sq.Pipeline([sq.impute.indicator(keep=True)]).learn(frame)
    assert flags.apply(frame, out="pandas").columns.tolist() == ["a", "a_missing"]


def test_all_missing_column():
    """Scikit-learn drops such a column; sqlearn names it in a StepError."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "dead": [np.nan, np.nan]})
    with pytest.raises(StepError, match=r"fill \(step 1\).*'dead'") as err:
        sq.Pipeline([("fill", sq.impute())]).learn(frame)
    assert err.value.step == "fill"
    assert err.value.position == 1


def test_text_column_is_refused_by_name():
    """A text column given to an aggregate of numbers is refused, naming it."""
    frame = pd.DataFrame({"city": ["x", "y"]})
    pipe = sq.Pipeline([("pass", sq.Step()), ("fill", sq.impute("city"))])
    with pytest.raises(StepError, match=r"fill \(step 2\).*'city'.*text") as err:
        pipe.learn(frame)
    assert err.value.position == 2


def test_settings_and_declaration():
    """Settings read back under the ``__init__`` names."""
    step = sq.impute.mean(keep=True, suffix="f")
    assert step.settings() == {
        "cols": None,
        "value": sq.agg.mean,
        "indicator": False,
        "keep": True,
        "suffix": "f",
    }


def test_reserved_word_and_space_names_work_and_are_named_in_errors():
    """Columns called ``order`` and ``my col`` fill, and are named when refused."""
    frame = pd.DataFrame({"order": [1.0, np.nan, 3.0], "my col": [2.0, 4.0, np.nan]})
    got = sq.Pipeline([sq.impute()]).learn(frame).apply(frame, out="pandas")
    assert got["order"].tolist() == [1.0, 2.0, 3.0]
    assert got["my col"].tolist() == [2.0, 4.0, 3.0]
    flags = sq.Pipeline([sq.impute.indicator()]).learn(frame)
    assert flags.columns_out_ == ["order", "order_missing", "my col", "my col_missing"]
    dead = pd.DataFrame({"order": [np.nan, np.nan], "my col": [np.nan, np.nan]})
    with pytest.raises(StepError, match=r"fill \(step 1\).*'order'"):
        sq.Pipeline([("fill", sq.impute("order"))]).learn(dead)
    with pytest.raises(StepError, match=r"fill \(step 1\).*'my col'"):
        sq.Pipeline([("fill", sq.impute("my col"))]).learn(dead)


def test_all_null_column_without_nan():
    """A column of real NULLs (not NaN) is refused, naming it."""
    rel = connection().sql("SELECT NULL::DOUBLE AS dead, 1.0 AS ok")
    with pytest.raises(StepError, match=r"fill \(step 1\).*'dead'"):
        sq.Pipeline([("fill", sq.impute())]).learn(rel)


def test_integer_nulls_are_filled():
    """A real NULL in an integer column is filled with the median, as DOUBLE."""
    rel = connection().sql("SELECT * FROM (VALUES (1), (NULL), (5), (9)) t(n)")
    pipe = sq.Pipeline([sq.impute()]).learn(rel)
    assert pipe.apply(rel).fetchall() == [(1.0,), (5.0,), (5.0,), (9.0,)]


@pytest.mark.parametrize("value", ["median", "mean"])
def test_infinity_is_refused(value):
    """A column holding infinity is refused (the median would hide it)."""
    frame = pd.DataFrame({"a": [1.0, np.inf, 3.0, np.nan, 2.0]})
    pipe = sq.Pipeline([("fill", sq.impute(value=value))])
    with pytest.raises(StepError, match=r"fill \(step 1\).*'a'.*infinity"):
        pipe.learn(frame)


def test_later_steps_see_the_columns_the_indicator_keeps():
    """The indicator keeps its inputs, so a later step by type still reads them."""
    frame = people()
    pipe = sq.Pipeline([sq.impute.indicator("age", "city"), sq.encode.onehot()])
    pipe.learn(frame)
    assert pipe.columns_out_ == [
        "age",
        "age_missing",
        "income",
        "city_lima",
        "city_oslo",
        "city_rome",
        "city_NULL",
        "city_missing",
    ]
    every = sq.Pipeline([sq.impute.indicator(), sq.encode.onehot()]).learn(frame)
    assert "city_oslo" in every.columns_out_
    lower = sq.Pipeline([sq.impute.indicator("age", "city"), sq.transform.upper()])
    got = lower.learn(frame).apply(frame, out="pandas")
    assert got["city"].dropna().tolist() == ["OSLO", "ROME", "OSLO", "LIMA"]


def test_later_steps_see_the_columns_filled_with_an_indicator():
    """Filled with the indicator, the input is still there for a later step."""
    frame = people()
    pipe = sq.Pipeline([sq.impute.mode("city", indicator=True), sq.encode.onehot()])
    assert pipe.learn(frame).columns_out_ == [
        "age",
        "income",
        "city_lima",
        "city_oslo",
        "city_rome",
        "city_missing",
    ]
