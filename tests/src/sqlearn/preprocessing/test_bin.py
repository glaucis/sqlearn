"""Tests of sq.bin against scikit-learn's KBinsDiscretizer and Binarizer."""

import pickle
import warnings

import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_array_equal
from sklearn.preprocessing import Binarizer, KBinsDiscretizer

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify
from sqlearn.errors import SqlearnError, SqlearnWarning, StepError
from sqlearn.preprocessing.bin import Bin, Binarize


def data(seed=1, rows=200):
    """Return seeded data: two float columns, an int column, a text column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(5, 2, rows),
            "b": rng.exponential(3, rows),
            "n": rng.integers(0, 1000, rows).astype("int64"),
            "city": rng.choice(["x", "y"], rows),
        },
    )


NUMBERS = ["a", "b", "n"]


def sklearn_bins(strategy, n, train, applied=None):
    """Return scikit-learn's fitted discretizer and its ordinal bins."""
    kbins = KBinsDiscretizer(
        n_bins=n, strategy=strategy, encode="ordinal", subsample=None
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        kbins.fit(train)
    return kbins, kbins.transform(train if applied is None else applied)


@pytest.mark.parametrize("method", ["uniform", "quantile"])
@pytest.mark.parametrize("n", [2, 3, 5, 7, 10])
@pytest.mark.parametrize("rows", [6, 13, 200])
def test_bins_match_sklearn(method, n, rows):
    """Each column's bins and inner edges are scikit-learn's, exactly."""
    frame = data(rows=rows)
    pipe = sq.Pipeline([sq.bin(method=method, n=n)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SqlearnWarning)
        pipe.learn(frame)
    got = pipe.apply(frame, out="pandas")
    kbins, expected = sklearn_bins(method, n, frame[NUMBERS])
    assert_array_equal(got[NUMBERS].to_numpy(), expected)
    for i, c in enumerate(NUMBERS):
        assert pipe[method].edges_[c] == kbins.bin_edges_[i][1:-1].tolist()
    assert got["city"].tolist() == frame["city"].tolist()


@pytest.mark.parametrize("method", ["uniform", "quantile"])
def test_new_values_outside_the_learned_range_go_to_the_end_bins(method):
    """Values below the minimum go to bin 0, above the maximum to the last."""
    train = data()[["a"]]
    applied = pd.DataFrame({"a": [-100.0, 100.0, 5.0, train["a"].min()]})
    pipe = sq.Pipeline([sq.bin(method=method, n=4)]).learn(train)
    _, expected = sklearn_bins(method, 4, train, applied)
    got = pipe.apply(applied, out="pandas")["a"].to_numpy()
    assert_array_equal(got, expected[:, 0])
    assert got[0] == 0 and got[1] == 3


def test_a_value_on_an_edge_goes_to_the_bin_above():
    """A value equal to an inner edge is in the bin above it, as searchsorted."""
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0]})
    pipe = sq.Pipeline([sq.bin.uniform(n=4)]).learn(frame)
    assert pipe["uniform"].edges_ == {"x": [1.0, 2.0, 3.0]}
    got = pipe.apply(frame, out="pandas")["x"].tolist()
    assert got == [0, 1, 2, 3, 3]
    assert got == sklearn_bins("uniform", 4, frame)[1][:, 0].tolist()


def test_equal_quantile_edges_merge_with_a_warning_as_sklearn():
    """Edges closer than 1e-8 merge, fewer bins result, and both warn."""
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"x": np.r_[np.zeros(60), rng.normal(10, 1, 40)]})
    pipe = sq.Pipeline([sq.bin.quantile(n=5)])
    with pytest.warns(SqlearnWarning, match=r"'x'.*3 bins.*not 5"):
        pipe.learn(frame)
    with pytest.warns(UserWarning, match="Bins whose width are too small"):
        kbins = KBinsDiscretizer(
            n_bins=5, strategy="quantile", encode="ordinal", subsample=None
        ).fit(frame)
    assert pipe["quantile"].edges_["x"] == kbins.bin_edges_[0][1:-1].tolist()
    got = pipe.apply(frame, out="pandas")["x"].to_numpy()
    assert_array_equal(got, kbins.transform(frame)[:, 0])
    assert got.max() == 2


def test_an_edge_equal_to_the_maximum_merges_away_the_one_below_it():
    """As scikit-learn: the last edge kept drops out, not the maximum's."""
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0, 2.0, 2.0, 2.0]})
    pipe = sq.Pipeline([sq.bin.quantile(n=3)])
    with pytest.warns(SqlearnWarning):
        pipe.learn(frame)
    kbins, expected = sklearn_bins("quantile", 3, frame)
    assert pipe["quantile"].edges_["x"] == kbins.bin_edges_[0][1:-1].tolist()
    assert_array_equal(pipe.apply(frame, out="pandas")["x"], expected[:, 0])


@pytest.mark.parametrize("method", ["uniform", "quantile"])
def test_bins_of_a_constant_column(method):
    """A constant column has one bin, every value 0, as scikit-learn; it warns."""
    frame = pd.DataFrame({"x": [3.0] * 5, "y": [1.0, 2.0, 3.0, 4.0, 5.0]})
    pipe = sq.Pipeline([sq.bin(method=method, n=3)])
    with pytest.warns(SqlearnWarning, match=r"'x'.*1 bin.*not 3"):
        pipe.learn(frame)
    kbins, expected = sklearn_bins(method, 3, frame)
    assert kbins.n_bins_[0] == 1
    assert pipe[method].edges_["x"] == []
    got = pipe.apply(frame, out="pandas")
    assert_array_equal(got[["x", "y"]].to_numpy(), expected)
    assert got["x"].tolist() == [0] * 5
    one = pd.DataFrame({"x": [np.nan, 7.0, np.nan]})
    with pytest.warns(SqlearnWarning):
        single = sq.Pipeline([sq.bin(method=method)]).learn(one)
    assert single.apply(one, out="pandas")["x"].tolist()[1] == 0


@pytest.mark.parametrize("method", ["uniform", "quantile"])
def test_null_and_nan_stay_null_and_are_left_out_of_learning(method):
    """Missing values (NULL or NaN) do not move the edges and stay NULL."""
    full = data()[["a"]]
    holed = full.copy()
    holed.loc[[3, 10, 50], "a"] = np.nan
    present = holed.dropna()
    pipe = sq.Pipeline([sq.bin(method=method, n=4)]).learn(holed)
    kbins, expected = sklearn_bins(method, 4, present)
    assert pipe[method].edges_["a"] == kbins.bin_edges_[0][1:-1].tolist()
    got = pipe.apply(holed, out="pandas")["a"]
    assert got.isna().tolist() == holed["a"].isna().tolist()
    assert_array_equal(got.dropna().to_numpy(), expected[:, 0])
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE), (3.0), (2.0)) t(a)"
    )
    applied = sq.Pipeline([sq.bin(method=method, n=2)]).learn(rel).apply(rel)
    assert applied.fetchall() == [(0,), (None,), (None,), (1,), (1,)]


@pytest.mark.parametrize("method", ["uniform", "quantile"])
@pytest.mark.parametrize("kind", ["INTEGER", "BIGINT", "DECIMAL(10,2)"])
def test_integer_and_decimal_columns(method, kind):
    """Integer and decimal columns bin as scikit-learn bins their floats."""
    rng = np.random.default_rng(5)
    values = rng.integers(-500, 500, 97) / (100 if kind.startswith("DEC") else 1)
    con = connection()
    con.register("_raw", pd.DataFrame({"x": values}))
    rel = con.sql(f"SELECT x::{kind} AS x FROM _raw")
    pipe = sq.Pipeline([sq.bin(method=method, n=6)]).learn(rel)
    got = pipe.apply(rel, out="pandas")["x"].to_numpy()
    kbins, expected = sklearn_bins(method, 6, values[:, None])
    assert pipe[method].edges_["x"] == kbins.bin_edges_[0][1:-1].tolist()
    assert_array_equal(got, expected[:, 0])
    con.unregister("_raw")


def test_the_output_is_integer():
    """A bin is an INTEGER, from 0."""
    frame = data()
    rel = sq.Pipeline([sq.bin.uniform("a")]).learn(frame).apply(frame)
    assert str(rel.types[0]) == "INTEGER"
    rel = sq.Pipeline([sq.bin.binarize("n")]).learn(frame).apply(frame)
    assert str(rel.types[2]) == "INTEGER"


@pytest.mark.parametrize("method", ["uniform", "quantile"])
def test_all_missing_column_is_refused(method):
    """A column of only NaN or only NULL is named in a StepError."""
    frame = pd.DataFrame({"dead": [np.nan, np.nan], "a": [1.0, 2.0]})
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'dead'"):
        sq.Pipeline([sq.bin(method=method)]).learn(frame)
    rel = connection().sql("SELECT NULL::DOUBLE AS dead, 1.0 AS ok")
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'dead'"):
        sq.Pipeline([sq.bin(method=method)]).learn(rel)


@pytest.mark.parametrize("method", ["uniform", "quantile"])
@pytest.mark.parametrize("bad", [np.inf, -np.inf])
def test_infinity_is_refused(method, bad):
    """A column holding infinity is refused (ADR 0030), as scikit-learn."""
    frame = pd.DataFrame({"a": [1.0, bad, 3.0, 2.0, 5.0]})
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'a'.*infinity"):
        sq.Pipeline([sq.bin(method=method)]).learn(frame)


@pytest.mark.parametrize("threshold", [0.0, 5.0, -1.5, 3])
def test_binarize_matches_sklearn(threshold):
    """1 above the threshold, else 0 (a value equal to it is 0), as Binarizer."""
    frame = data()
    frame.loc[0, "a"] = float(threshold)
    pipe = sq.Pipeline([sq.bin.binarize(threshold=threshold)]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    expected = Binarizer(threshold=threshold).fit_transform(frame[NUMBERS])
    assert_array_equal(got[NUMBERS].to_numpy(), expected)
    assert got["a"].iloc[0] == 0
    assert got["city"].tolist() == frame["city"].tolist()


def test_binarize_keeps_null_and_nan_null():
    """A missing value stays NULL: NaN, which DuckDB sorts greatest, too."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0), (NULL), ('NaN'::DOUBLE), (-2.0)) t(a)"
    )
    applied = sq.Pipeline([sq.bin.binarize()]).learn(rel).apply(rel)
    assert applied.fetchall() == [(1,), (None,), (None,), (0,)]


def test_binarize_learns_nothing():
    """Binarize has nothing to learn: no aggregate, a static step."""
    assert Binarize().learn(sq.fn.const(1.0)) == {}
    assert Binarize.static is True


def test_shortcut_equals_general_form():
    """Each shortcut builds the step the general form builds with its settings."""
    pairs = [
        (sq.bin.quantile("a"), sq.bin("a")),
        (sq.bin.quantile("a", n=3), sq.bin("a", method="quantile", n=3)),
        (sq.bin.uniform("a"), sq.bin("a", method="uniform")),
        (
            sq.bin.uniform("a", n=7, keep=True),
            sq.bin("a", method="uniform", n=7, keep=True),
        ),
        (sq.bin.binarize("a"), sq.bin("a", method="binarize")),
        (
            sq.bin.binarize("a", threshold=5.0),
            sq.bin("a", method="binarize", threshold=5.0),
        ),
    ]
    frame = data()
    for short, general in pairs:
        assert type(short) is type(general)
        assert short.settings() == general.settings()
        assert repr(short) == repr(general)
        assert short.default_name() == general.default_name()
        a = sq.Pipeline([short]).learn(frame)
        b = sq.Pipeline([general]).learn(frame)
        assert b.runs_ == []
        assert a.apply(frame, out="pandas").equals(b.apply(frame, out="pandas"))


def test_default_method_and_columns():
    """The general form is quantile bins, five, over the numeric columns."""
    step = sq.bin()
    assert isinstance(step, Bin)
    assert (step.method, step.n, step.cols) == ("quantile", 5, None)
    frame = data()
    got = sq.Pipeline([step]).learn(frame).apply(frame, out="pandas")
    assert got["city"].tolist() == frame["city"].tolist()
    assert set(got["a"]) == {0, 1, 2, 3, 4}


def test_columns_by_name_list_or_selector():
    """Columns come as names, one list, or cols=; a dict is refused."""
    assert sq.bin.uniform("a", "b").cols == ["a", "b"]
    assert sq.bin.quantile(["a", "b"]).cols == ["a", "b"]
    assert sq.bin.binarize(cols=sq.cols.numeric()).cols == sq.cols.numeric()
    with pytest.raises(SqlearnError, match="twice"):
        sq.bin.uniform("a", cols="b")
    with pytest.raises(SqlearnError, match="dict"):
        sq.bin({"a": "uniform"})


def test_default_names():
    """A step is named after its method."""
    assert sq.bin().default_name() == "quantile"
    assert sq.bin.uniform().default_name() == "uniform"
    assert sq.bin.binarize(threshold=2.0).default_name() == "binarize"


def test_repr_is_the_shortest_form_that_rebuilds():
    """The repr names the method and only the settings that differ from it."""
    cases = {
        "sq.bin.quantile()": sq.bin(),
        "sq.bin.quantile(cols=['a', 'b'])": sq.bin("a", "b", n=5),
        "sq.bin.uniform(n=10)": sq.bin(method="uniform", n=10),
        "sq.bin.uniform(cols='a', keep=True, suffix='bin')": sq.bin.uniform(
            "a", keep=True, suffix="bin"
        ),
        "sq.bin.binarize()": sq.bin.binarize(threshold=0.0),
        "sq.bin.binarize(cols='b', suffix='hot')": sq.bin.binarize("b", suffix="hot"),
        "sq.bin.binarize(threshold=2.5)": sq.bin(method="binarize", threshold=2.5),
    }
    for text, step in cases.items():
        assert repr(step) == text
        assert eval(text).settings() == step.settings()
    selected = sq.bin.binarize(cols=sq.cols("a"), keep=True)
    assert repr(selected) == "sq.bin.binarize(cols=cols('a'), keep=True)"


def test_settings_and_declaration():
    """Settings read back under the ``__init__`` names; both steps are static."""
    assert sq.bin.uniform(n=4, keep=True).settings() == {
        "cols": None,
        "method": "uniform",
        "n": 4,
        "keep": True,
        "suffix": None,
    }
    assert sq.bin.binarize(threshold=1.0).settings() == {
        "cols": None,
        "threshold": 1.0,
        "keep": False,
        "suffix": None,
    }
    for cls in (Bin, Binarize):
        assert cls.static is True
        undeclared = type("Undeclared", (cls,), {"static": None})()
        assert classify(undeclared, [("a", DOUBLE)]) == "static"


def test_the_steps_pickle():
    """A step pickles and comes back equal (the search copies steps)."""
    for step in (sq.bin.uniform("c", n=3), sq.bin.binarize(threshold=2.0)):
        back = pickle.loads(pickle.dumps(step))
        assert back.settings() == step.settings()
        assert repr(back) == repr(step)


def test_the_group_lists_its_shortcuts():
    """Tab completion lists the shortcuts; the group prints as sq.bin."""
    assert repr(sq.bin) == "sq.bin"
    assert {"uniform", "quantile", "binarize"} <= set(dir(sq.bin))


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: sq.bin(method="kmeans"), "not a method"),
        (lambda: Bin(method="binarize"), "Binarize"),
        (lambda: sq.bin(n=1), "at least 2"),
        (lambda: sq.bin.uniform(n=2.5), "at least 2"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.bin.uniform(n=True), "at least 2"),
        (lambda: sq.bin(method="binarize", n=3), "n="),
        (lambda: sq.bin(method="uniform", threshold=1.0), "threshold="),
        (lambda: sq.bin.binarize(threshold="high"), "threshold"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.bin.binarize(threshold=np.nan), "threshold"),
    ],
)
def test_bad_settings_are_refused(build, match):
    """Each bad setting is refused with a message naming it."""
    with pytest.raises(SqlearnError, match=match):
        build()


@pytest.mark.parametrize("make", [sq.bin.uniform, sq.bin.quantile, sq.bin.binarize])
def test_a_text_column_is_refused_by_name(make):
    """A text column chosen by name is refused, naming it."""
    with pytest.raises(StepError, match=r"\(step 1\).*'city'"):
        sq.Pipeline([make("city")]).learn(data())


def test_keep_adds_a_column_beside_the_input():
    """With keep, the bin goes beside the input, suffixed with the step's name."""
    frame = data()
    got = (
        sq.Pipeline([sq.bin.uniform("a", keep=True), sq.bin.binarize("b", keep=True)])
        .learn(frame)
        .apply(frame, out="pandas")
    )
    assert {"a", "a_uniform", "b", "b_binarize"} <= set(got.columns)
    assert got["a"].tolist() == frame["a"].tolist()


def test_reserved_word_and_space_names_work():
    """Columns called ``order`` and ``my col`` bin as scikit-learn bins them."""
    frame = pd.DataFrame(
        {"order": [1.0, 2.0, 3.0, 9.0], "my col": [2.0, 4.0, 7.0, 0.0]}
    )
    got = sq.Pipeline([sq.bin.uniform(n=3)]).learn(frame).apply(frame, out="pandas")
    assert_array_equal(got.to_numpy(), sklearn_bins("uniform", 3, frame)[1])


@pytest.mark.parametrize("method", ["uniform", "quantile"])
def test_a_step_after_bin_learns_from_its_bins_in_the_same_run(method):
    """A later step learns from the bins as the same query computes them."""
    frame = pd.DataFrame({"a": [0.0, 0.0, 0.0, 1.0, 5.0, 6.0, 7.0, 9.0, 9.5, 10.0]})
    _, expected = sklearn_bins(method, 4, frame)
    pipe = sq.Pipeline([sq.bin(method=method, n=4), sq.scale.minmax()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SqlearnWarning)
        pipe.learn(frame)
    assert len(pipe.runs_) == 1
    assert pipe["minmax"].center_ == {"a": expected.min()}
    assert pipe["minmax"].scale_ == {"a": expected.max() - expected.min()}
