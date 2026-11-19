"""Tests of ``sq.select``, its shortcuts, and its selectors in pipelines.

The selectors in a pipeline, a search, the learning store and a saved file,
against scikit-learn's ``Pipeline`` and ``GridSearchCV`` (spec §2, §7).
"""

import json
import time

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.feature_selection import SelectKBest as SkSelectKBest
from sklearn.feature_selection import VarianceThreshold as SkVarianceThreshold
from sklearn.feature_selection import f_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, PredefinedSplit
from sklearn.pipeline import make_pipeline

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE, step_key
from sqlearn.errors import SqlearnError
from sqlearn.feature_selection import SelectKBest, SelectPercentile, VarianceThreshold

DATA = ("table", "t", 1)


def key(name, step):
    """Return the store key of a one-step pipeline of `step`."""
    return step_key(DATA, None, [(name, step)], 0, frozenset())


def test_the_shortcut_is_the_general_form():
    """Each shortcut builds the step the class and the general form build."""
    cases = [
        (
            "variance",
            sq.select.variance(threshold=0.5),
            sq.select(method="variance", threshold=0.5),
            VarianceThreshold(threshold=0.5),
            "sq.select.variance(threshold=0.5)",
        ),
        (
            "best",
            sq.select.best("a", "b", k=2, score="chi2"),
            sq.select("a", "b", method="best", k=2, score="chi2"),
            SelectKBest(k=2, score="chi2", cols=["a", "b"]),
            "sq.select.best(k=2, score='chi2', cols=['a', 'b'])",
        ),
        (
            "percentile",
            sq.select.percentile(percentile=30, score="f_regression"),
            sq.select(method="percentile", percentile=30, score="f_regression"),
            SelectPercentile(percentile=30, score="f_regression"),
            "sq.select.percentile(percentile=30, score='f_regression')",
        ),
    ]
    for name, short, general, cls, text in cases:
        assert type(short) is type(general) is type(cls)
        assert repr(short) == repr(general) == repr(cls) == text
        assert short.settings() == general.settings() == cls.settings()
        assert key(name, short) == key(name, general) == key(name, cls)


def test_the_general_form_defaults_to_variance():
    """Called with no method, it is the variance selector."""
    assert repr(sq.select()) == "sq.select.variance()"


@pytest.mark.parametrize(
    "call",
    [
        lambda: sq.select(method="nope"),
        lambda: sq.select(method="variance", k=3),
        lambda: sq.select(method="variance", score="chi2"),
        lambda: sq.select(method="best", threshold=0.1),
        lambda: sq.select(method="best", percentile=10),
        lambda: sq.select(method="percentile", k=3),
        lambda: sq.select(method="percentile", threshold=0.1),
    ],
)
def test_the_general_form_refuses_a_setting_of_another_method(call):
    """A setting that does not belong to the method is refused, with Why and Fix."""
    with pytest.raises(SqlearnError, match=r"Why:.*Fix:"):
        call()


def churn(seed=3, rows=240):
    """Return 14 numeric columns, 2 with holes and 1 constant, and a class.

    Five columns carry the class, more or less strongly; the rest are noise.
    """
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, rows)
    columns = {
        f"x{i:02d}": rng.normal(0, 1, rows) + (0.6 - 0.1 * i) * y * (i < 5)
        for i in range(13)
    }
    frame = pd.DataFrame(columns).assign(flat=2.0)
    frame.loc[rng.choice(rows, 20, replace=False), "x00"] = np.nan
    frame.loc[rng.choice(rows, 15, replace=False), "x07"] = np.nan
    return frame, y


def spec_pipe(k=10):
    """Return §2's pipeline."""
    return sq.Pipeline(
        [
            sq.impute.median(),
            sq.select.variance(),
            sq.select.best(k=k, score="f_classif"),
            ("model", LogisticRegression()),
        ]
    )


def sk_spec_pipe(k=10):
    """Return scikit-learn's equivalent of §2's pipeline."""
    return make_pipeline(
        SimpleImputer(strategy="median"),
        SkVarianceThreshold(),
        SkSelectKBest(f_classif, k=k),
        LogisticRegression(),
    )


def folds_of(frame):
    """Return sqlearn's default fold of each row, for ``PredefinedSplit``.

    A k-fold deals rows by their values: give the data as the search gets it,
    the target included.
    """
    con = connection()
    con.register("select_folds", frame)
    try:
        return [
            k
            for (k,) in sq.folds.kfold(5, seed=0)
            .numbered(con.table("select_folds"), "k")
            .project("k")
            .fetchall()
        ]
    finally:
        con.unregister("select_folds")


def test_the_spec_script_predicts_as_scikit_learn():
    """§2's pipeline trains and predicts as scikit-learn's ``Pipeline``.

    The constant column is dropped by the variance selector, then the 10
    best of the 13 left are kept, the same 10 in the same order.
    """
    frame, y = churn()
    sk = sk_spec_pipe().fit(frame, y)
    pipe = spec_pipe().train(frame.assign(churned=y), target="churned")
    kept = list(sk[:-1].get_feature_names_out())
    assert "flat" not in kept
    assert pipe.columns_out_ == kept
    predicted = pipe.predict(frame, out="pandas")["prediction"].to_numpy()
    np.testing.assert_array_equal(predicted, sk.predict(frame))
    assert list(pipe["best"].scores_) == [c for c in frame.columns if c != "flat"]


def test_a_search_over_k_picks_scikit_learns_setting():
    """sqlearn's folds handed to ``GridSearchCV``: the same best k and means.

    k chooses only the output (ADR 0056): the scores are learned once per
    fold, plus once in the final training, whatever the number of settings.
    """
    frame, y = churn()
    ks = [1, 3, 6, 13]
    sk = GridSearchCV(
        sk_spec_pipe(),
        {"selectkbest__k": ks},
        scoring="accuracy",
        cv=PredefinedSplit(folds_of(frame.assign(churned=y))),
    ).fit(frame, y)
    search = sq.search(
        spec_pipe(), params={"best__k": ks}, metric=sq.metrics.accuracy
    ).train(frame.assign(churned=y), target="churned")
    assert search.best_params_ == {"best__k": sk.best_params_["selectkbest__k"]}
    assert search.best_score_ == pytest.approx(sk.best_score_, abs=1e-12)
    means = dict(search.results_.aggregate("setting, avg(score)", "setting").fetchall())
    for params, sk_mean in zip(
        sk.cv_results_["params"], sk.cv_results_["mean_test_score"], strict=True
    ):
        setting = json.dumps({"best__k": params["selectkbest__k"]})
        assert means[setting] == pytest.approx(sk_mean, abs=1e-12)
    assert STORE.learns["best"] == 5 + 1
    assert STORE.learns["median"] == 5 + 1


@pytest.mark.parametrize(
    ("params", "learns"),
    [
        ({"percentile__percentile": [10, 50, 90]}, 5 + 1),
        ({"percentile__score": ["f_classif", "chi2"]}, 2 * 5 + 1),
    ],
)
def test_a_search_learns_per_fold_for_percentile_and_per_setting_for_score(
    params, learns
):
    """percentile chooses only the output; score changes what is learned."""
    frame, y = churn()
    frame = frame.drop(columns="flat")
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.scale.minmax(),  # chi2 takes no negative value
            sq.select.percentile(),
            ("model", LogisticRegression()),
        ]
    )
    sq.search(pipe, params=params).train(frame.assign(churned=y), target="churned")
    assert STORE.learns["percentile"] == learns


def scaled_columns():
    """Return the columns each learned scaler matched, from the store."""
    return {
        tuple(entry.columns)
        for key, entry in STORE._entries.items()
        if key[2][-1][0] == "scale"
    }


def test_a_later_step_sees_only_the_kept_columns():
    """In ``train`` and in each search fold, the next step sees what is kept.

    The scaler learns on the columns scikit-learn's SelectKBest keeps: on all
    rows in ``train``, on each fold's training rows in a search. It reads the
    kept columns, so it is learned per setting of k and fold (k is in its
    key), plus once in the final training; the selector once per fold.
    """
    frame, y = churn()
    frame = frame.drop(columns=["flat", "x00", "x07"])
    data = frame.assign(churned=y)
    pipe = sq.Pipeline(
        [
            sq.select.best(k=3),
            ("scale", sq.scale.standard()),
            ("model", LogisticRegression()),
        ]
    )
    pipe.train(data, target="churned")
    sk_kept = tuple(SkSelectKBest(f_classif, k=3).fit(frame, y).get_feature_names_out())
    assert tuple(pipe["scale"].center_) == sk_kept
    assert pipe.columns_out_ == list(sk_kept)
    assert scaled_columns() == {sk_kept}

    STORE.clear()
    search = sq.search(pipe, params={"best__k": [2, 3]}).train(data, target="churned")
    folds = np.array(folds_of(data))
    expected = {
        tuple(
            SkSelectKBest(f_classif, k=k)
            .fit(frame[folds != fold], y[folds != fold])
            .get_feature_names_out()
        )
        for k in (2, 3)
        for fold in range(5)
    }
    best = search.best_params_["best__k"]
    expected.add(
        tuple(SkSelectKBest(f_classif, k=best).fit(frame, y).get_feature_names_out())
    )
    assert scaled_columns() == expected
    assert STORE.learns["scale"] == 2 * 5 + 1
    assert STORE.learns["best"] == 5 + 1


@pytest.mark.parametrize(
    "step",
    [
        sq.select.variance(threshold=1.0),
        sq.select.best(k=4),
        sq.select.percentile(percentile=40),
    ],
    ids=repr,
)
def test_a_learned_feature_selector_is_found_in_the_store(step):
    """A second ``learn`` on the same data runs nothing, and keeps the same."""
    frame, y = churn()
    data = frame.drop(columns=["flat", "x00", "x07"]).assign(churned=y)
    first = sq.Pipeline([step]).learn(data, target="churned")
    assert STORE.learns[step.default_name()] == 1
    again = sq.Pipeline([step]).learn(data, target="churned")
    assert STORE.learns[step.default_name()] == 1
    assert again.runs_ == []
    assert again.columns_out_ == first.columns_out_
    assert len(first.columns_out_) < len(data.columns) - 1


@pytest.mark.parametrize(
    "step",
    [
        sq.select.variance(threshold=0.3),
        sq.select.best(k=4, score="chi2"),
        sq.select.percentile(percentile=40, score="f_regression"),
    ],
    ids=repr,
)
def test_each_feature_selector_saves_and_loads(step, tmp_path):
    """``sq.save`` then ``sq.load`` in a fresh store: the same output, unlearned.

    The settings are plain values (`score` is a name), and what was learned
    (a variance, or the sums per class or the moments of a score) is written
    as plain data, so loading builds the step from its class path alone.
    """
    frame, y = churn()
    data = frame.drop(columns="flat").abs().assign(churned=y)
    pipe = sq.Pipeline([sq.impute.median(), step]).learn(data, target="churned")
    expected = pipe.apply(data, out="pandas")
    assert list(expected.columns) != list(data.columns)
    path = tmp_path / "select.json"
    sq.save(pipe, path)
    STORE.clear()
    loaded = sq.load(path)
    assert repr(loaded[1]) == repr(step)
    pd.testing.assert_frame_equal(loaded.apply(data, out="pandas"), expected)
    assert loaded.columns_out_ == pipe.columns_out_
    assert dict(STORE.learns) == {}


BIG = """
    SELECT
        ((hash(i, 1) % 1000) / 100 + 0.8 * y)::DOUBLE AS a,
        ((hash(i, 2) % 1000) / 100)::DOUBLE AS b,
        ((hash(i, 3) % 1000) / 100 + 0.3 * y)::DOUBLE AS c,
        ((hash(i, 4) % 1000) / 100)::DOUBLE AS d,
        2.5::DOUBLE AS flat,
        y
    FROM (SELECT i, (hash(i, 9) % 2)::INTEGER AS y FROM range(20000000) t(i))
"""

F_CLASSIF = """
    WITH classes AS (
        SELECT count(*) AS n, avg({c}) AS mean, var_pop({c}) * count(*) AS within
        FROM {data} GROUP BY y
    ), whole AS (SELECT sum(n) AS n, sum(n * mean) / sum(n) AS mean FROM classes)
    SELECT (sum(classes.n * (classes.mean - whole.mean) ** 2) / (count(*) - 1))
        / (sum(within) / (any_value(whole.n) - count(*)))
    FROM classes, whole
"""


@pytest.mark.slow
def test_the_feature_selectors_learn_larger_than_memory(tmp_path, capsys):
    """``variance`` then ``best`` learn 20 million rows within 64 MB.

    The rows take about 960 MB in DuckDB's memory (105 MB as Parquet), on
    one thread as the core's slow tests. The variances and scores are
    checked against DuckDB's own on a connection without the limit.
    """
    path = tmp_path / "big.parquet"
    duckdb.execute(f"COPY ({BIG}) TO '{path}' (FORMAT parquet)")
    assert path.stat().st_size > 64 * 2**20
    con = duckdb.connect()
    con.execute("set memory_limit = '64MB'")
    con.execute("set threads = 1")
    con.execute(f"set temp_directory = '{tmp_path / 'spill'}'")
    sq.set_config(connection=con)
    pipe = sq.Pipeline([sq.select.variance(), sq.select.best(k=2)])
    out = tmp_path / "selected.parquet"
    start = time.perf_counter()
    pipe.learn(str(path), target="y")
    pipe.apply(str(path), out=sq.out.parquet(out))
    elapsed = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n20 million rows through variance and best in 64 MB: {elapsed:.1f} s")  # noqa: T201

    assert pipe.columns_out_ == ["a", "c"]
    whole = duckdb.connect()
    data = f"read_parquet('{path}')"
    variances = whole.sql(
        f"SELECT var_pop(a), var_pop(b), var_pop(c), var_pop(d) FROM {data}"
    ).fetchall()[0]
    assert pipe["variance"].variances_ == pytest.approx(
        dict(zip("abcd", variances, strict=True)) | {"flat": 0.0}, rel=1e-9
    )
    scores = {
        c: whole.sql(F_CLASSIF.format(c=c, data=data)).fetchall()[0][0] for c in "abcd"
    }
    assert pipe["best"].scores_ == pytest.approx(scores, rel=1e-9)
    selected = con.sql(f"SELECT * FROM read_parquet('{out}') LIMIT 0").columns
    assert selected == pipe.columns_out_
    assert con.sql(f"SELECT count(*) FROM read_parquet('{out}')").fetchall() == [
        (20_000_000,)
    ]
