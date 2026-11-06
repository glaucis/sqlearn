"""The preprocessing spec's script (§2), end to end, proved against scikit-learn.

The script, its data and scikit-learn's equivalent live in the validation
runner (``validation/pipelines/validate_preprocessing.py``), so the test and
the recorded validation run the very same comparison.
"""

import time

import duckdb
import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._store import STORE
from validation.pipelines import validate_preprocessing as script
from validation.pipelines import validate_slice


def test_the_script_runs(tmp_path, monkeypatch):
    """§2's script runs on Parquet files, learning each step as often as it must.

    Fold first: 2 centres x 5 folds prepare the data 10 times; C changes
    nothing upstream. A step learns once per fold and setting it depends on,
    plus once in the final training: the robust scaler and what reads its
    output (the bins of age, the polynomial of age and income) 11 times,
    the steps upstream of it, or beside it (the encoders), 6.
    """
    script.write_data(tmp_path)
    monkeypatch.chdir(tmp_path)
    search, predicted = script.run_the_script()
    assert isinstance(predicted, pd.DataFrame)
    assert list(predicted.columns) == ["prediction"]
    assert len(predicted) == script.NEW_ROWS
    assert set(predicted["prediction"]) <= {0, 1}
    assert set(search.best_params_) == {"robust__center", "model__C"}
    assert search.results_.count("*").fetchall() == [(20,)]
    assert search.transforms_ == 10
    assert dict(STORE.learns) == {
        "median": 6,
        "mode": 6,
        "log1p": 6,
        "robust": 11,
        "onehot": 6,
        "target": 6,
        "quantile": 11,
        "polynomial": 11,
    }


def test_the_script_matches_scikit_learn():
    """The same scores, best setting, predictions and prepared columns.

    scikit-learn is handed sqlearn's outer folds and, within each fold's
    training rows, the target encoder's inner folds. Columns are compared by
    name: sqlearn writes the polynomial's terms where age stood, as
    ``age*income`` (ADR 0035), and the one-hot columns where city stood.
    """
    got = script.compare()
    assert got.scores == got.sk_scores
    assert got.search.best_params_ == got.best
    assert (got.predicted == got.sk_predicted).all()
    assert list(got.prepared.columns) == [
        "age",
        "income",
        "age^2",
        "age*income",
        "income^2",
        "city_kyiv",
        "city_lima",
        "city_oslo",
        "city_rome",
        "plan",
    ]
    assert set(got.sk_prepared.columns) == set(got.prepared.columns)
    for name in got.prepared.columns:
        ours = got.prepared[name].to_numpy(dtype=float)
        theirs = got.sk_prepared[name].to_numpy(dtype=float)
        assert np.abs(ours - theirs).max() <= script.BOUND * 2**-52, name


def test_the_slice_still_matches_scikit_learn():
    """The core's slice, in the grouped names, still validates."""
    assert {c["result"] for c in validate_slice.cases()} == {"pass"}


BIG = """
    SELECT
        CASE WHEN i % 11 = 0 THEN NULL
             ELSE 20 + (hash(i, 1) % 600) / 10 END::DOUBLE AS age,
        CASE WHEN i % 13 = 0 THEN NULL
             ELSE 1000 + hash(i, 2) % 100000 END::DOUBLE AS income,
        CASE WHEN i % 17 = 0 THEN NULL
             ELSE ['kyiv', 'lima', 'oslo', 'rome'][1 + (hash(i, 3) % 4)::BIGINT]
        END AS city,
        ['basic', 'plus', 'pro'][1 + (hash(i, 4) % 3)::BIGINT] AS plan,
        (hash(i, 5) % 100 < 30 + 20 * (hash(i, 4) % 3 = 0)::INTEGER)::INTEGER
            AS churned
    FROM range(20000000) t(i)
"""


@pytest.mark.slow
def test_the_preparation_runs_larger_than_memory(tmp_path, capsys):
    """§2's preparation learns and applies 20 million rows within 256 MB.

    The rows take about 800 MB in DuckDB's memory (117 MB as Parquet). The
    limit is 256 MB, not the slice's 64 MB: one learn statement here sorts
    for several exact quantiles in turn (the median, the robust scaler's
    quartiles, the bins' edges) and counts a mode, and under 64 MB, or
    128 MB, DuckDB cannot pin the blocks the later sorts need. The median
    then the robust scaler alone fit 64 MB at 10 million rows, not at 20.
    """
    path = tmp_path / "big.parquet"
    duckdb.execute(f"COPY ({BIG}) TO '{path}' (FORMAT parquet)")
    con = duckdb.connect()
    con.execute("set memory_limit = '256MB'")
    con.execute("set threads = 1")
    con.execute(f"set temp_directory = '{tmp_path / 'spill'}'")
    sq.set_config(connection=con)
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.impute("city", value="mode"),
            sq.transform.log1p("income"),
            sq.scale.robust(),
            sq.encode.onehot("city"),
            sq.encode.target("plan"),
            sq.bin.quantile("age", n=5),
            sq.features.polynomial("age", "income"),
        ]
    )
    out = tmp_path / "prepared.parquet"
    start = time.perf_counter()
    pipe.learn(str(path), target="churned")
    pipe.apply(str(path), out=sq.out.parquet(out))
    elapsed = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n20 million rows through §2's preparation in 256 MB: {elapsed:.1f} s")  # noqa: T201

    # DuckDB's own median and mode hold a column's values in memory: check
    # them on a connection without the limit.
    data = f"read_parquet('{path}')"
    medians, modes, means = (
        duckdb.connect()
        .sql(
            f"SELECT [median(age), median(income)], mode(city), "
            f"avg(churned) FROM {data}"
        )
        .fetchall()[0]
    )
    assert pipe["median"].value_ == pytest.approx(
        {"age": medians[0], "income": medians[1]}
    )
    assert pipe["mode"].value_ == {"city": modes}
    assert pipe["target"].target_mean_ == pytest.approx({"plan": means}, rel=1e-12)
    prepared = con.sql(f"SELECT count(*) FROM read_parquet('{out}')").fetchall()
    assert prepared == [(20_000_000,)]
