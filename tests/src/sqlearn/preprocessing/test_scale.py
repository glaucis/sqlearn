"""Tests of sq.scale against scikit-learn's Standard, Robust, MinMax, MaxAbs scalers."""

import pickle
import time
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_allclose, assert_array_equal
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline as SkPipeline
from sklearn.preprocessing import (
    MaxAbsScaler,
    MinMaxScaler,
    Normalizer,
    RobustScaler,
    StandardScaler,
)

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import classify
from sqlearn.errors import SqlearnError, StepError
from sqlearn.preprocessing.scale import Normalize, Scale


@pytest.fixture
def con():
    """Return sqlearn's connection."""
    return connection()


def data(seed=1, rows=50):
    """Return seeded data: two float columns, an int column, a text column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(5, 2, rows),
            "b": rng.uniform(-3, 40, rows),
            "n": rng.integers(0, 100, rows).astype("int64"),
            "city": rng.choice(["x", "y"], rows),
        },
    )


def holed(seed=1, rows=50):
    """Return `data` with NaN holes in the float columns."""
    frame = data(seed, rows)
    rng = np.random.default_rng(seed + 10)
    frame.loc[rng.choice(rows, 7, replace=False), "a"] = np.nan
    frame.loc[rng.choice(rows, 4, replace=False), "b"] = np.nan
    return frame


NUMBERS = ["a", "b", "n"]

SKLEARN_CENTER = {
    "standard": "mean_",
    "robust": "center_",
    "minmax": "data_min_",
    "maxabs": None,
}


@pytest.mark.parametrize(
    ("shortcut", "sklearn_scaler"),
    [
        (sq.scale.standard, StandardScaler()),
        (sq.scale.robust, RobustScaler()),
        (sq.scale.minmax, MinMaxScaler()),
        (sq.scale.maxabs, MaxAbsScaler()),
    ],
)
def test_scalers_match_sklearn(con, shortcut, sklearn_scaler):
    """Each shortcut's output and learned centre match scikit-learn's scaler."""
    frame = holed()
    sk = sklearn_scaler.fit(frame[NUMBERS])
    step = shortcut()
    pipe = sq.Pipeline([step]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(
        got[NUMBERS].to_numpy(), sk.transform(frame[NUMBERS]), rtol=1e-13, atol=1e-15
    )
    assert got["city"].tolist() == frame["city"].tolist()
    center = SKLEARN_CENTER[step.method]
    learned = pipe[step.default_name()]
    if center is not None:
        assert_allclose(
            [learned.center_[c] for c in NUMBERS], getattr(sk, center), rtol=1e-15
        )


def test_robust_with_a_quantile_range_matches_sklearn():
    """``quantile_range`` is RobustScaler's, in percent."""
    frame = holed(seed=3, rows=100)
    sk = RobustScaler(quantile_range=(7.0, 93.0)).fit(frame[NUMBERS])
    pipe = sq.Pipeline([sq.scale.robust(quantile_range=(7, 93))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_array_equal(got[NUMBERS].to_numpy(), sk.transform(frame[NUMBERS]))
    assert [pipe["robust"].scale_[c] for c in NUMBERS] == sk.scale_.tolist()


def test_minmax_with_a_feature_range_matches_sklearn():
    """``feature_range`` is MinMaxScaler's."""
    frame = holed()
    sk = MinMaxScaler(feature_range=(-1, 2)).fit(frame[NUMBERS])
    pipe = sq.Pipeline([sq.scale.minmax(feature_range=(-1, 2))]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(
        got[NUMBERS].to_numpy(), sk.transform(frame[NUMBERS]), rtol=1e-13, atol=1e-15
    )


def test_shortcut_equals_general_form():
    """Each shortcut builds the step the general form builds with its settings."""
    assert sq.scale.robust("x").settings() == sq.scale("x", method="robust").settings()
    assert (
        repr(sq.scale.robust("x", quantile_range=(10, 90)))
        == "sq.scale.robust(cols='x', quantile_range=(10, 90))"
    )
    pairs = [
        (sq.scale.standard("x"), sq.scale("x")),
        (sq.scale.robust("x"), sq.scale("x", method="robust")),
        (
            sq.scale.robust("x", quantile_range=(10, 90)),
            sq.scale("x", method="robust", spread=sq.agg.iqr(q=(0.1, 0.9))),
        ),
        (
            sq.scale.robust("x", quantile_range=(25, 75)),
            sq.scale("x", method="robust", spread=sq.agg.iqr(q=(0.25, 0.75))),
        ),
        (sq.scale.minmax("x"), sq.scale("x", method="minmax")),
        (
            sq.scale.minmax("x", feature_range=(-1, 1)),
            sq.scale("x", method="minmax", feature_range=(-1, 1)),
        ),
        (sq.scale.maxabs("x"), sq.scale("x", method="maxabs")),
    ]
    frame = pd.DataFrame({"x": [1.0, 4.0, 2.0, 9.0, -3.0]})
    for short, general in pairs:
        assert short.settings() == general.settings()
        assert repr(short) == repr(general)
        a = sq.Pipeline([short]).learn(frame).apply(frame, out="pandas")
        b = sq.Pipeline([general]).learn(frame).apply(frame, out="pandas")
        assert a.equals(b)


def test_a_given_center_replaces_the_default():
    """A given centre or spread replaces the method's; the method stays."""
    s = sq.scale.robust(center=sq.agg.mean)
    assert s.method == "robust" and s.center == sq.agg.mean
    assert s.default_name() == "robust"
    assert repr(s) == "sq.scale.robust(center=sq.agg.mean)"
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 10.0]})
    got = sq.Pipeline([s]).learn(frame).apply(frame, out="pandas")["x"]
    q1, q3 = np.quantile(frame["x"], [0.25, 0.75])
    assert_allclose(got, (frame["x"] - frame["x"].mean()) / (q3 - q1), rtol=1e-15)
    assert sq.scale.standard(center="median").center == sq.agg.median


def test_a_center_or_spread_of_none_means_zero_or_one():
    """``center=None`` subtracts nothing; ``spread=None`` divides by nothing."""
    frame = pd.DataFrame({"x": [1.0, 2.0, 6.0]})
    uncentred = sq.Pipeline([sq.scale(center=None)]).learn(frame)
    assert_allclose(
        uncentred.apply(frame, out="pandas")["x"],
        StandardScaler(with_mean=False).fit_transform(frame)[:, 0],
        rtol=1e-15,
    )
    unspread = sq.Pipeline([sq.scale(spread=None)]).learn(frame)
    assert unspread.apply(frame, out="pandas")["x"].tolist() == [-2.0, -1.0, 3.0]
    nothing = sq.Pipeline([sq.scale(center=None, spread=None)]).learn(frame)
    assert nothing.apply(frame).fetchall() == [(1.0,), (2.0,), (6.0,)]


def test_scale_and_impute_integer_and_decimal_columns(con):
    """INTEGER, BIGINT and DECIMAL(10,2) columns give scikit-learn's DOUBLE values."""
    con.execute(
        "CREATE OR REPLACE TABLE numbers (i INTEGER, b BIGINT, d DECIMAL(10,2))"
    )
    rng = np.random.default_rng(5)
    rows = [
        [
            None if k % 7 == 0 else int(rng.integers(-50, 50)),
            None if k % 5 == 1 else int(rng.integers(0, 10**12)),
            None if k % 6 == 2 else round(float(rng.uniform(-1000, 1000)), 2),
        ]
        for k in range(41)
    ]
    con.executemany("INSERT INTO numbers VALUES (?, ?, ?)", rows)
    rel = con.table("numbers")
    floats = np.array(
        [[np.nan if v is None else float(v) for v in row] for row in rows], dtype=float
    )
    for shortcut, scaler in [
        (sq.scale.robust, RobustScaler()),
        (sq.scale.standard, StandardScaler()),
        (sq.scale.minmax, MinMaxScaler()),
        (sq.scale.maxabs, MaxAbsScaler()),
    ]:
        sk = SkPipeline([("i", SimpleImputer(strategy="median")), ("s", scaler)])
        expected = sk.fit_transform(floats)
        out = sq.Pipeline([sq.impute.median(), shortcut()]).learn(rel).apply(rel)
        assert [str(t) for t in out.types] == ["DOUBLE"] * 3
        got = np.array(out.fetchall(), dtype=float)
        if shortcut == sq.scale.robust:
            assert_array_equal(got, expected)
        else:
            assert_allclose(got, expected, rtol=1e-13, atol=1e-15)


def test_scale_a_dict():
    """A dict gives each column its own method, in one step that rebuilds."""
    frame = holed()
    step = sq.scale({"a": "robust", "b": "minmax", "n": "standard"})
    assert step.settings()["cols"] == ["a", "b", "n"]
    pipe = sq.Pipeline([step]).learn(frame)
    assert list(pipe.named_steps) == ["scale"]
    got = pipe.apply(frame, out="pandas")
    for col, scaler in [
        ("a", RobustScaler()),
        ("b", MinMaxScaler()),
        ("n", StandardScaler()),
    ]:
        expected = scaler.fit_transform(frame[[col]])[:, 0]
        assert_allclose(got[col], expected, rtol=1e-13, atol=1e-15)
    assert repr(step) == "sq.scale({'a': 'robust', 'b': 'minmax', 'n': 'standard'})"
    assert eval(repr(step)).settings() == step.settings()


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: sq.scale({"a": "normalise"}), r"'normalise'.*standard"),
        (lambda: sq.scale({"a": sq.agg.mean}), r"sq\.agg\.mean.*method"),
        (lambda: sq.scale({"a": "robust"}, method="minmax"), r"dict.*method="),
        (lambda: sq.scale({"a": "robust"}, method="standard"), r"dict.*method="),
        (lambda: sq.scale({"a": "robust"}, center=sq.agg.mean), r"dict.*center="),
        (lambda: Scale(cols=["b"], method={"a": "robust"}), r"cols="),
        (lambda: sq.scale(method="zscore"), r"'zscore'.*'standard'"),
        (lambda: sq.scale(center="middle"), r"center='middle'.*aggregate"),
        (lambda: sq.scale(spread=sq.agg.distinct), r"sq\.agg\.distinct"),
        (lambda: sq.scale(spread=2.0), r"spread=2\.0"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.scale.minmax(feature_range=(1, 0)), r"feature_range=\(1, 0\)"),
        (lambda: sq.scale.minmax(feature_range=0), r"feature_range=0"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.scale.robust(quantile_range=(75, 25)), r"quantile_range"),
        (lambda: sq.scale.robust(quantile_range=(0, 150)), r"quantile_range"),
        (
            lambda: sq.scale.robust(quantile_range=(10, 90), spread=sq.agg.std),
            r"quantile_range.*spread",
        ),
        (lambda: sq.scale.robust("a", cols=["b"]), r"cols="),
    ],
)
def test_bad_settings_are_refused(build, match):
    """Settings that are not a scaling are refused when the step is built."""
    with pytest.raises(SqlearnError, match=match):
        build()


def test_a_dict_naming_a_missing_column_is_refused():
    """A misspelt dict key is refused at learn, naming it and the columns."""
    rel = connection().sql("SELECT 1.0 AS age, 2.0 AS income")
    with pytest.raises(StepError, match=r"agee.*'age', 'income'"):
        sq.Pipeline([sq.scale({"agee": "robust"})]).learn(rel)


def test_a_search_over_a_dict_step_is_refused():
    """Searching a dict step's methods is refused, saying to use one step per column."""
    frame = pd.DataFrame({"age": [1.0, 2.0, 3.0, 4.0] * 5, "y": [0, 1, 0, 1] * 5})
    pipe = sq.Pipeline([sq.scale({"age": "robust"}), LogisticRegression()])
    search = sq.search(
        pipe, params={"scale__method": [{"age": "minmax"}]}, folds=sq.folds.kfold(2)
    )
    with pytest.raises(SqlearnError, match=r"scale__method.*one step per column"):
        search.train(frame, target="y")


def test_a_search_over_the_method_takes_its_defaults():
    """Rebuilt with another method, a step takes that method's centre and spread."""
    settings: dict[str, Any] = {**sq.scale.standard("x").settings(), "method": "robust"}
    rebuilt = Scale(**settings)
    assert rebuilt.settings() == sq.scale.robust("x").settings()
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"a": rng.normal(0, 1, 40), "y": [0, 1] * 20})
    pipe = sq.Pipeline([("scale", sq.scale.standard()), LogisticRegression()])
    search = sq.search(
        pipe,
        params={"scale__method": ["standard", "robust", "minmax", "maxabs"]},
        folds=sq.folds.kfold(2),
    ).train(frame, target="y")
    assert len({row[0] for row in search.results_.fetchall()}) == 4


def test_constant_column_scales_to_zero():
    """A spread of 0 counts as 1, so a constant column becomes 0 (or ``a``)."""
    frame = pd.DataFrame({"k": [4.0, 4.0, 4.0], "v": [1.0, 2.0, 3.0]})
    for shortcut, scaler in [
        (sq.scale.standard, StandardScaler()),
        (sq.scale.robust, RobustScaler()),
        (sq.scale.minmax, MinMaxScaler(feature_range=(-1, 1))),
    ]:
        step = (
            shortcut(feature_range=(-1, 1))
            if shortcut == sq.scale.minmax
            else shortcut()
        )
        pipe = sq.Pipeline([step]).learn(frame)
        got = pipe.apply(frame, out="pandas")
        assert pipe[step.default_name()].scale_["k"] == 1.0
        assert_allclose(got.to_numpy(), scaler.fit_transform(frame), rtol=1e-15)
    zeros = pd.DataFrame({"z": [0.0, 0.0]})
    got = sq.Pipeline([sq.scale.maxabs()]).learn(zeros).apply(zeros, out="pandas")
    assert got["z"].tolist() == MaxAbsScaler().fit_transform(zeros)[:, 0].tolist()


def test_default_names():
    """A step is named after its method; a dict step is ``scale``."""
    assert sq.scale().default_name() == "standard"
    assert sq.scale(method="robust").default_name() == "robust"
    assert sq.scale.minmax(center=sq.agg.mean).default_name() == "minmax"
    assert sq.scale.maxabs().default_name() == "maxabs"
    assert sq.scale({"a": "robust"}).default_name() == "scale"


def test_repr_is_the_shortest_form_that_rebuilds():
    """The repr names the method and only the settings that differ from its own."""
    cases = {
        "sq.scale.standard()": sq.scale(),
        "sq.scale.standard(cols=['a', 'b'])": sq.scale("a", "b"),
        "sq.scale.robust()": sq.scale.robust(quantile_range=(25.0, 75.0)),
        "sq.scale.robust(quantile_range=(5, 95.5))": sq.scale.robust(
            quantile_range=(5, 95.5)
        ),
        "sq.scale.robust(spread=sq.agg.std)": sq.scale.robust(spread="std"),
        "sq.scale.robust(spread=None)": sq.scale.robust(spread=None),
        "sq.scale.standard(spread=sq.agg.iqr)": sq.scale(spread="iqr"),
        "sq.scale.robust(spread=sq.agg.iqr(q=(0.1234567890123, 0.5)))": sq.scale(
            method="robust", spread=sq.agg.iqr(q=(0.1234567890123, 0.5))
        ),
        "sq.scale.robust(quantile_range=(12.3456789, 50))": sq.scale(
            method="robust", spread=sq.agg.iqr(q=(0.123456789, 0.5))
        ),
        "sq.scale.minmax()": sq.scale.minmax(feature_range=(0.0, 1.0)),
        "sq.scale.minmax(feature_range=None)": sq.scale.minmax(feature_range=None),
        "sq.scale.minmax(feature_range=(-1, 1))": sq.scale.minmax(
            feature_range=[-1, 1]
        ),
        "sq.scale.standard(center=None, keep=True, suffix='z')": sq.scale.standard(
            center=None, keep=True, suffix="z"
        ),
        "sq.scale.maxabs(cols='a')": sq.scale.maxabs("a", spread=sq.agg.maxabs),
        "sq.scale.standard(feature_range=(0, 1))": sq.scale(feature_range=(0, 1)),
    }
    for text, step in cases.items():
        assert repr(step) == text
        assert eval(text).settings() == step.settings()


def test_settings_and_declaration():
    """Settings read back under the ``__init__`` names; the step is static."""
    assert sq.scale.robust(keep=True).settings() == {
        "cols": None,
        "method": "robust",
        "center": "default",
        "spread": "default",
        "feature_range": "default",
        "keep": True,
        "suffix": None,
    }
    undeclared = type("Undeclared", (Scale,), {"static": None})()
    assert classify(undeclared, [("a", DOUBLE)]) == "static"
    assert Scale.static is True


def test_the_step_pickles():
    """A step pickles and comes back equal (the search copies steps)."""
    step = sq.scale.robust("c", center=sq.agg.mean, quantile_range=(10, 90))
    back = pickle.loads(pickle.dumps(step))
    assert back.settings() == step.settings()
    assert repr(back) == repr(step)


def test_the_group_lists_its_shortcuts():
    """Tab completion lists the shortcuts; the group prints as sq.scale."""
    assert repr(sq.scale) == "sq.scale"
    assert {"standard", "robust", "minmax", "maxabs"} <= set(dir(sq.scale))


def test_integer_columns_come_out_double():
    """Scaling an integer column gives DOUBLE."""
    frame = data()
    rel = sq.Pipeline([sq.scale.standard("n")]).learn(frame).apply(frame)
    assert str(rel.types[2]) == "DOUBLE"


def test_a_text_column_is_refused_by_name():
    """A text column chosen to scale is refused at learn, naming it."""
    frame = data()
    with pytest.raises(StepError, match=r"standard \(step 1\).*'city'.*VARCHAR"):
        sq.Pipeline([sq.scale.standard("city")]).learn(frame)


def test_keep_adds_a_column_beside_the_input():
    """With keep=True the input stays and ``a_<step name>`` is added."""
    frame = data()
    got = (
        sq.Pipeline([sq.scale.robust("a", keep=True)])
        .learn(frame)
        .apply(frame, out="pandas")
    )
    assert "a_robust" in got.columns
    assert "a" in got.columns


def test_impute_then_scale_matches_sklearn_pipeline():
    """Impute then scale equals scikit-learn's imputer then scaler."""
    frame = holed(rows=60)
    cols = ["a", "b"]
    sk = SkPipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())])
    expected = sk.fit_transform(frame[cols])
    pipe = sq.Pipeline([sq.impute.median(cols), sq.scale.standard(cols)]).learn(frame)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(got[cols].to_numpy(), expected, rtol=1e-12)


@pytest.mark.parametrize("method", ["standard", "robust", "minmax", "maxabs"])
def test_all_missing_column(method):
    """A column of only NaN or only NULL is named in a StepError."""
    frame = pd.DataFrame({"dead": [np.nan, np.nan], "a": [1.0, 2.0]})
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'dead'"):
        sq.Pipeline([sq.scale(method=method)]).learn(frame)
    rel = connection().sql("SELECT NULL::DOUBLE AS dead, 1.0 AS ok")
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'dead'"):
        sq.Pipeline([sq.scale(method=method)]).learn(rel)


def test_reserved_word_and_space_names_work_and_are_named_in_errors():
    """Columns called ``order`` and ``my col`` scale, and are named when refused."""
    frame = pd.DataFrame({"order": [1.0, 2.0, 3.0], "my col": [2.0, 4.0, 7.0]})
    sk = RobustScaler().fit(frame)
    got = sq.Pipeline([sq.scale.robust()]).learn(frame).apply(frame, out="pandas")
    assert got.to_numpy().tolist() == sk.transform(frame).tolist()
    dead = pd.DataFrame({"order": [np.nan, np.nan], "my col": [np.nan, np.nan]})
    with pytest.raises(StepError, match=r"robust \(step 1\).*'order'"):
        sq.Pipeline([sq.scale.robust("order")]).learn(dead)
    with pytest.raises(StepError, match=r"robust \(step 1\).*'my col'"):
        sq.Pipeline([sq.scale.robust("my col")]).learn(dead)


def test_real_nulls_are_skipped_in_learning():
    """NULLs (not NaN) stay NULL and do not count in the centre or spread."""
    rel = connection().sql("SELECT * FROM (VALUES (1.0), (NULL), (3.0)) t(a)")
    pipe = sq.Pipeline([sq.scale.standard()]).learn(rel)
    assert pipe["standard"].center_ == {"a": 2.0}
    assert pipe.apply(rel).fetchall() == [(-1.0,), (None,), (1.0,)]


def test_one_non_missing_value_scales_to_zero():
    """With a single non-missing value the spread is 0 (counts as 1): result 0."""
    frame = pd.DataFrame({"a": [np.nan, 7.0, np.nan]})
    for method in ("standard", "robust", "minmax"):
        got = (
            sq.Pipeline([sq.scale(method=method)])
            .learn(frame)
            .apply(frame, out="pandas")
        )
        assert got["a"].iloc[1] == 0.0


def test_all_missing_after_impute_in_the_same_statement():
    """Impute then scale on an all-missing column fails at the impute, by name."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "dead": [np.nan, np.nan]})
    pipe = sq.Pipeline([("fill", sq.impute()), sq.scale.standard()])
    with pytest.raises(StepError, match=r"fill \(step 1\).*'dead'") as err:
        pipe.learn(frame)
    assert err.value.position == 1


@pytest.mark.parametrize("method", ["standard", "robust", "minmax", "maxabs"])
def test_infinity_is_refused(method):
    """A column holding infinity is refused (the median would hide it)."""
    frame = pd.DataFrame({"a": [1.0, np.inf, 3.0, 2.0, 5.0]})
    pipe = sq.Pipeline([sq.scale(method=method)])
    with pytest.raises(StepError, match=rf"{method} \(step 1\).*'a'.*infinity"):
        pipe.learn(frame)


@pytest.mark.parametrize(
    ("method", "scaler", "values"),
    [
        ("standard", StandardScaler(), [1.0, 1.0 + 2**-52, 1.0]),
        ("standard", StandardScaler(), [1e8, 1e8 + 2**-26, 1e8, 1e8]),
        ("robust", RobustScaler(), [1.0, 1.0, 1.0 + 2**-52, 1.0 + 2**-51]),
        ("minmax", MinMaxScaler(), [1.0, 1.0 + 2**-52, 1.0]),
        ("maxabs", MaxAbsScaler(), [1e-300, -1e-300, 0.0]),
    ],
)
def test_a_near_constant_column_is_constant_as_in_sklearn(method, scaler, values):
    """A spread at the level of rounding counts as 1, as scikit-learn's does.

    The standard spread is judged on the variance, by scikit-learn's bound on
    its rounding; the others are 1 below ten machine epsilons.
    """
    frame = pd.DataFrame({"x": values})
    pipe = sq.Pipeline([sq.scale(method=method)]).learn(frame)
    sk = scaler.fit(frame)
    assert pipe[method].scale_["x"] == 1.0 == sk.scale_[0]
    got = pipe.apply(frame, out="pandas")["x"]
    assert_allclose(got, sk.transform(frame)[:, 0], rtol=1e-15, atol=1e-15)


def test_a_spread_just_above_the_threshold_divides():
    """Ten machine epsilons and more divide, as scikit-learn's do."""
    frame = pd.DataFrame({"x": [1.0, 1.0 + 2**-48, 1.0]})  # range 16 eps
    pipe = sq.Pipeline([sq.scale.minmax()]).learn(frame)
    sk = MinMaxScaler().fit(frame)
    assert pipe["minmax"].scale_["x"] == 2**-48 and sk.scale_[0] == 2**48
    assert pipe.apply(frame).fetchall() == [(0.0,), (1.0,), (0.0,)]


def test_a_search_over_the_robust_center():
    """The spec's search over ``robust__center``: each candidate learns its own."""
    rng = np.random.default_rng(2)
    frame = pd.DataFrame(
        {"a": rng.exponential(3.0, 60), "b": rng.normal(0, 1, 60), "y": [0, 1] * 30}
    )
    pipe = sq.Pipeline([sq.scale.robust(), LogisticRegression()])
    centers = [sq.agg.median, sq.agg.mean]
    search = sq.search(
        pipe, params={"robust__center": centers}, folds=sq.folds.kfold(2)
    ).train(frame, target="y")
    settings = {row[0] for row in search.results_.fetchall()}
    assert settings == {
        '{"robust__center": "sq.agg.median"}',
        '{"robust__center": "sq.agg.mean"}',
    }
    assert search.best_params_["robust__center"] in centers
    assert isinstance(search.best_params_["robust__center"], sq.agg.Aggregate)
    features = frame[["a", "b"]]
    learned = {
        repr(c): sq.Pipeline([sq.scale.robust(center=c)])
        .learn(features)["robust"]
        .center_
        for c in centers
    }
    assert learned["sq.agg.median"]["a"] == np.median(frame["a"])
    assert learned["sq.agg.mean"]["a"] == pytest.approx(frame["a"].mean(), rel=1e-15)
    assert learned["sq.agg.median"] != learned["sq.agg.mean"]
    best = repr(search.best_params_["robust__center"])
    assert search.best_pipeline_["robust"].center_ == learned[best]


@pytest.mark.parametrize("norm", ["l1", "l2", "max"])
def test_normalize_matches_sklearn(con, norm):
    """Each row of the selected columns is divided by its norm, as Normalizer."""
    frame = data()
    sk = Normalizer(norm=norm).fit_transform(frame[NUMBERS])
    got = sq.Pipeline([sq.scale.normalize(norm=norm)]).learn(frame)
    out = got.apply(frame, out="pandas")
    assert list(out.columns) == list(frame.columns)
    assert_allclose(out[NUMBERS].to_numpy(), sk, rtol=1e-14, atol=1e-16)
    assert out["city"].tolist() == frame["city"].tolist()


def test_a_zero_row_stays_zero(con):
    """A row whose norm is 0 (or within rounding of it) stays as it is."""
    frame = pd.DataFrame({"a": [0.0, 3.0, 1e-17], "b": [0.0, -4.0, 0.0]})
    for norm in ["l1", "l2", "max"]:
        sk = Normalizer(norm=norm).fit_transform(frame)
        pipe = sq.Pipeline([sq.scale.normalize(norm=norm)]).learn(frame)
        got = pipe.apply(frame, out="pandas").to_numpy()
        assert_array_equal(got, sk)
        assert got[0].tolist() == [0.0, 0.0]


def test_normalize_refuses_a_missing_value_when_fetched():
    """A NULL or NaN in a selected column is refused, saying to impute first."""
    frame = holed()
    pipe = sq.Pipeline([sq.scale.normalize(["a", "n"])]).learn(frame)
    with pytest.raises(
        duckdb.InvalidInputException,
        match=r"sq\.scale\.normalize.*missing.*'a'.*Fix: impute",
    ):
        pipe.apply(frame).fetchall()
    rel = connection().sql("SELECT 1.0 AS a, NULL::DOUBLE AS b")
    with pytest.raises(duckdb.InvalidInputException, match=r"'b'"):
        sq.Pipeline([sq.scale.normalize()]).learn(rel).apply(rel).fetchall()
    imputed = sq.Pipeline([sq.impute(), sq.scale.normalize()]).learn(frame)
    sk = SkPipeline([("i", SimpleImputer(strategy="median")), ("n", Normalizer())])
    assert_allclose(
        imputed.apply(frame, out="pandas")[NUMBERS].to_numpy(),
        sk.fit_transform(frame[NUMBERS]),
        rtol=1e-14,
    )


def test_normalize_refuses_infinity_when_fetched():
    """An infinite value is refused, as scikit-learn's Normalizer refuses it."""
    rel = connection().sql("SELECT 1.0 AS a, 'inf'::DOUBLE AS b")
    with pytest.raises(duckdb.InvalidInputException, match=r"'b'.*infinite"):
        sq.Pipeline([sq.scale.normalize()]).learn(rel).apply(rel).fetchall()


def test_normalize_shortcut_equals_general_form():
    """``sq.scale.normalize`` and ``method="normalize"`` build equal steps."""
    pairs = [
        (sq.scale.normalize(), sq.scale(method="normalize")),
        (
            sq.scale.normalize("a", norm="l1"),
            sq.scale("a", method="normalize", norm="l1"),
        ),
        (
            sq.scale.normalize(norm="max", keep=True, suffix="u"),
            sq.scale(method="normalize", norm="max", keep=True, suffix="u"),
        ),
    ]
    for short, general in pairs:
        assert isinstance(general, Normalize)
        assert short.settings() == general.settings()
        assert repr(short) == repr(general)
        assert eval(repr(short)).settings() == short.settings()
    assert repr(pairs[0][0]) == "sq.scale.normalize()"
    assert repr(pairs[1][0]) == "sq.scale.normalize(cols='a', norm='l1')"
    assert repr(sq.scale.normalize(norm="l2")) == "sq.scale.normalize()"


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: sq.scale(method="normalize", center="mean"), r"center=.*normalize"),
        (lambda: sq.scale(method="normalize", spread=None), r"spread=None"),
        (
            lambda: sq.scale(method="normalize", feature_range=(0, 1)),
            r"feature_range=\(0, 1\)",
        ),
        (lambda: sq.scale({"a": "normalize"}), r"'normalize'.*whole row"),
        (lambda: sq.scale.normalize(norm="l3"), r"norm='l3'.*'l1', 'l2', 'max'"),
        (lambda: sq.scale(norm="l1"), r"norm='l1'.*method='standard'"),
    ],
)
def test_bad_normalize_settings_are_refused(build, match):
    """Settings normalize does not take are refused when the step is built."""
    with pytest.raises(SqlearnError, match=match):
        build()


def test_normalize_declares_a_whole_row_static_step():
    """Normalize is rowwise and static, learns nothing, and is named normalize."""
    step = sq.scale.normalize("a", norm="l1")
    assert Normalize.rowwise is True and Normalize.static is True
    assert step.settings() == {
        "cols": "a", "norm": "l1", "keep": False, "suffix": None,
    }  # fmt: skip
    assert step.default_name() == "normalize"
    assert step.learn(duckdb.ColumnExpression("a")) == {}
    assert step.apply_row({}, {}, {}) == {}
    with pytest.raises(SqlearnError, match=r"Scale got method='normalize'"):
        Scale(method="normalize")
    assert "normalize" in dir(sq.scale)
    back = pickle.loads(pickle.dumps(step))
    assert repr(back) == repr(step)


def test_normalize_keeps_inputs_and_takes_integers_but_not_text():
    """keep adds ``<column>_normalize``; integers come out DOUBLE; text is refused."""
    frame = data()
    got = (
        sq.Pipeline([sq.scale.normalize(["a", "n"], keep=True)])
        .learn(frame)
        .apply(frame, out="pandas")
    )
    assert list(got.columns) == ["a", "a_normalize", "b", "n", "n_normalize", "city"]
    assert_allclose(
        got[["a_normalize", "n_normalize"]].to_numpy(),
        Normalizer().fit_transform(frame[["a", "n"]]),
        rtol=1e-14,
    )
    rel = sq.Pipeline([sq.scale.normalize("n")]).learn(frame).apply(frame)
    assert str(rel.types[2]) == "DOUBLE"
    with pytest.raises(StepError, match=r"normalize \(step 1\).*'city'.*VARCHAR"):
        sq.Pipeline([sq.scale.normalize(["a", "city"])]).learn(frame)


class Times(sq.Step):
    """Multiply a column by a factor (a setting, so it is in the store key)."""

    static = True

    def __init__(self, cols=None, factor=2.0):
        """Set the settings."""
        super().__init__(cols)
        self.factor = factor

    def apply(self, x, learned):
        """Multiply."""
        return x * self.factor


def test_a_step_after_normalize_depends_on_every_input_s_producer():
    """Reading one normalized column depends on what made the others (ADR 0024)."""
    frame = data()
    centres = [
        sq.Pipeline([Times("b", factor), sq.scale.normalize(["a", "b"]), sq.scale("a")])
        .learn(frame)["standard"]
        .center_["a"]
        for factor in (2.0, 3.0)
    ]
    assert centres[0] != centres[1]


@pytest.mark.parametrize("norm", ["l1", "l2", "max"])
def test_normalize_over_200_columns_is_quick_and_matches_sklearn(norm):
    """The norm is computed once per row, so wide tables stay fast (linear SQL)."""
    rng = np.random.default_rng(4)
    frame = pd.DataFrame(rng.normal(size=(1000, 200))).add_prefix("c")
    start = time.perf_counter()
    rel = sq.Pipeline([sq.scale.normalize(norm=norm)]).learn(frame).apply(frame)
    got = rel.df().to_numpy()
    assert time.perf_counter() - start < 10
    assert len(rel.sql_query()) < 1_000_000
    assert_allclose(got, Normalizer(norm=norm).fit_transform(frame), rtol=1e-13)
