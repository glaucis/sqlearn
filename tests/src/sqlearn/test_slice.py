"""The slice, end to end: spec §2's script and what it shows, proved together."""

import copy
import time

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE, FLOAT, INTEGER
from sklearn.linear_model import LogisticRegression
from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE

CUSTOMERS = """
    SELECT
        CASE WHEN hash(i, 1) % 10 = 0 THEN NULL
             ELSE 20 + hash(i, 2) % 50 END::DOUBLE AS age,
        CASE WHEN hash(i, 3) % 10 = 0 THEN NULL
             ELSE 1000 + hash(i, 4) % 4000 END::DOUBLE AS income,
        ['kyiv', 'oslo', 'rome'][1 + (hash(i, 5) % 3)::BIGINT] AS city,
        ['basic', 'pro', 'team'][1 + (hash(i, 6) % 3)::BIGINT] AS plan,
        (hash(i, 7) % 100 < 30 + 30 * (city = 'oslo')::INTEGER)::INTEGER AS churned
    FROM range({start}, {stop}) t(i)
"""
"""The slice's data, generated from the row number: no seed, no download.

Two numbers with gaps, a city, a plan, and whether the customer churned
(more often in Oslo, so the model has something to learn).
"""


def write_parquet(path, start, stop):
    """Write rows `start` to `stop` of the slice's data to a Parquet file."""
    query = CUSTOMERS.format(start=start, stop=stop)
    duckdb.execute(f"COPY ({query}) TO '{path}' (FORMAT parquet)")


def slice_data(root):
    """Write the slice's files under `root`: three training files and new data."""
    (root / "data" / "train").mkdir(parents=True)
    for part in range(3):
        start = part * 200
        write_parquet(root / "data" / "train" / f"{part}.parquet", start, start + 200)
    write_parquet(root / "data" / "new.parquet", 600, 750)


def run_the_slice():
    """Run spec §2's script, as written there, from the current directory."""
    pipe = sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric())),
            ("model", LogisticRegression()),
        ]
    )

    search = sq.Search(
        pipe,
        params={"model__C": [0.1, 1, 10], "impute__value": ["median", "mean"]},
        metric=sq.metrics.accuracy,
    )
    search.train("data/train/*.parquet", target="churned")
    print(search.best_params_, search.best_score_)  # noqa: T201  (the script prints)
    search.results_.show()
    return search, search.predict("data/new.parquet", out="pandas")


def test_the_slice_script_runs(tmp_path, monkeypatch):
    """Spec §2's script runs on Parquet files, with the counts it promises."""
    slice_data(tmp_path)
    monkeypatch.chdir(tmp_path)
    search, predicted = run_the_slice()
    assert isinstance(predicted, pd.DataFrame)
    assert list(predicted.columns) == ["prediction"]
    assert len(predicted) == 150
    assert set(predicted["prediction"]) <= {0, 1}
    assert set(search.best_params_) == {"model__C", "impute__value"}
    assert 0 <= search.best_score_ <= 1
    assert search.results_.count("*").fetchall() == [(30,)]
    # Fold first: 5 folds x 2 imputer settings; C changes nothing upstream.
    assert search.transforms_ == 10
    # The folds' learning, plus the final training on all the data.
    assert dict(STORE.learns) == {"impute": 11, "scale": 11, "onehot": 6, "ordinal": 6}


def test_store_size_is_reported(tmp_path, monkeypatch, capsys):
    """After the slice's search the store holds values and SQL only: under 1 MB."""
    slice_data(tmp_path)
    monkeypatch.chdir(tmp_path)
    run_the_slice()
    size = STORE.size_bytes()
    with capsys.disabled():
        print(f"\nstore after the slice's search: {size} bytes")  # noqa: T201
    assert 0 < size < 1_000_000


class DeclaredScale(MyScale):
    """MyScale, declared static."""

    static = True


class DeclaredEncoder(MyEncoder):
    """MyEncoder, declared dynamic, creating integer columns."""

    dynamic = True
    creates = INTEGER


CITIES = ["city_kyiv", "city_oslo", "city_rome"]
PLANS = ["plan_basic", "plan_pro", "plan_team"]

# Each case: the steps, and the runs `learn` takes, derived by hand from ADR
# 0018. A step learns in the earliest run its inputs allow; a dynamic step's
# new columns exist from the run after it learns. A step waits for them when
# it names a column not yet known, when its selector could match the type the
# dynamic step declared (any type when it declared none), or when it reads
# every column (cols=None). So the runs are the longest chain of dynamic
# steps that wait for each other, plus one when a step waits for the last.
# The data: age, income (DOUBLE, with gaps), visits (INTEGER), city, plan.
RUNS = [
    pytest.param(
        # Static steps only: everything in one run.
        lambda: [
            ("impute", sq.impute.median(["age", "income"])),
            ("scale", sq.scale.standard(cols=["age", "income"])),
        ],
        1,
        id="static-by-name",
    ),
    pytest.param(
        # Static steps only, chained through numeric(): one run.
        lambda: [("impute", sq.impute()), ("scale", sq.scale.standard())],
        1,
        id="static-numeric",
    ),
    pytest.param(
        # OneHot and Ordinal read different columns: both learn in run 1.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
        ],
        1,
        id="independent-dynamic",
    ),
    pytest.param(
        # string() cannot match OneHot's INTEGER columns: no wait.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=sq.cols.string())),
        ],
        1,
        id="string-does-not-wait",
    ),
    pytest.param(
        # Scale names a column that exists from the start: no wait.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("scale", sq.scale.standard(["age"])),
        ],
        1,
        id="known-name-does-not-wait",
    ),
    pytest.param(
        # Scale names OneHot's new columns: run 1 OneHot, run 2 Scale.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("scale", sq.scale.standard(CITIES)),
        ],
        2,
        id="new-names-wait",
    ),
    pytest.param(
        # The slice's preparation: numeric() could match OneHot's and
        # Ordinal's INTEGER columns, so Scale waits: two runs.
        lambda: [
            ("impute", sq.impute()),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard()),
        ],
        2,
        id="the-slice",
    ),
    pytest.param(
        # ADR 0018's own example: the two chains share their runs, two not three.
        lambda: [
            ("onehot_city", sq.encode.onehot(cols=["city"])),
            ("scale_city", sq.scale.standard(CITIES)),
            ("onehot_plan", sq.encode.onehot(cols=["plan"])),
            ("scale_plan", sq.scale.standard(PLANS)),
        ],
        2,
        id="two-chains-share-runs",
    ),
    pytest.param(
        # A chain of dynamic steps: Ordinal's plan is new (its values are
        # learned), OneHot of it waits a run, and Scale of numeric() waits
        # for OneHot: three runs.
        lambda: [
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("onehot", sq.encode.onehot(cols=["plan"])),
            ("scale", sq.scale.standard()),
        ],
        3,
        id="chain-of-dynamic",
    ),
    pytest.param(
        # A step reading every column depends on every step before it.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", MyScale(cols=None)),
        ],
        2,
        id="reads-everything",
    ),
    pytest.param(
        # Combined selectors: numeric() & ~cols(...) could still match
        # OneHot's INTEGER columns, so Scale waits.
        lambda: [
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric() & ~sq.cols("visits"))),
        ],
        2,
        id="combined-selector-waits",
    ),
    pytest.param(
        # An undeclared user step found static: one run.
        lambda: [("impute", sq.impute()), ("scale", MyScale())],
        1,
        id="undeclared-static",
    ),
    pytest.param(
        # A declared static user step: one run.
        lambda: [("impute", sq.impute()), ("scale", DeclaredScale())],
        1,
        id="declared-static",
    ),
    pytest.param(
        # An undeclared dynamic user step: numeric() waits for it.
        lambda: [("encode", MyEncoder()), ("scale", sq.scale.standard())],
        2,
        id="undeclared-dynamic-numeric-waits",
    ),
    pytest.param(
        # Undeclared, its new columns may be of any type: string() waits too.
        lambda: [
            ("encode", MyEncoder()),
            ("ordinal", sq.encode.ordinal(sq.cols.string())),
        ],
        2,
        id="undeclared-dynamic-string-waits",
    ),
    pytest.param(
        # Declared as creating INTEGER columns: string() does not wait.
        lambda: [
            ("encode", DeclaredEncoder()),
            ("ordinal", sq.encode.ordinal(sq.cols.string())),
        ],
        1,
        id="declared-dynamic-string-does-not-wait",
    ),
    pytest.param(
        # ...and numeric() still does.
        lambda: [("encode", DeclaredEncoder()), ("scale", sq.scale.standard())],
        2,
        id="declared-dynamic-numeric-waits",
    ),
]

PEOPLE = """
    CREATE TABLE people AS SELECT
        CASE WHEN i % 7 = 3 THEN NULL ELSE 20 + (i * 37) % 50 END::DOUBLE AS age,
        CASE WHEN i % 5 = 1 THEN NULL ELSE 1000 + (i * 7919) % 3000 END::DOUBLE
            AS income,
        ((i * 13) % 9)::INTEGER AS visits,
        ['kyiv', 'oslo', 'rome'][1 + i % 3] AS city,
        ['basic', 'pro', 'team'][1 + (i * 7) % 3] AS plan
    FROM range(60) t(i)
"""


def one_step_at_a_time(steps, table):
    """Learn and apply each step in its own query, one step at a time.

    The reference that needs no planner: each step's result is written to a
    table, and the next step learns from that table.
    """
    con = connection()
    current = table
    for i, (name, step) in enumerate(steps):
        pipe = sq.Pipeline([(name, step)]).learn(con.table(current))
        assert len(pipe.runs_) == 1
        result = f"reference_{i}"
        pipe.apply(con.table(current)).to_table(result)
        current = result
    return con.table(current)


def assert_same(got, want):
    """Same columns, order and types; floats close, everything else equal."""
    assert got.columns == want.columns
    assert got.types == want.types
    got_columns = list(zip(*got.fetchall(), strict=True))
    want_columns = list(zip(*want.fetchall(), strict=True))
    for name, dtype, a, b in zip(
        got.columns, got.types, got_columns, want_columns, strict=True
    ):
        if dtype in (DOUBLE, FLOAT):
            as_float = [np.nan if v is None else v for v in a]
            to = [np.nan if v is None else v for v in b]
            assert np.allclose(as_float, to, equal_nan=True, rtol=1e-12), name
        else:
            assert list(a) == list(b), name


@pytest.mark.parametrize(("make", "runs"), RUNS)
def test_run_counts_for_every_combination(make, runs):
    """Each combination learns in the runs ADR 0018 gives, with the same result."""
    con = connection()
    con.execute(PEOPLE)
    steps = make()
    want = one_step_at_a_time([(n, copy.deepcopy(s)) for n, s in steps], "people")
    STORE.clear()
    pipe = sq.Pipeline(steps).learn(con.table("people"))
    assert len(pipe.runs_) == runs
    assert all(len(run.statements) == 1 for run in pipe.runs_)
    got = pipe.apply(con.table("people"))
    assert len(pipe.runs_) == 1
    assert_same(got, want)


def test_an_edited_frame_relearns():
    """An edited pandas frame is new data; the same frame unedited is not."""
    frame = pd.DataFrame(
        {"age": [20.0, None, 40.0, 50.0], "city": ["kyiv", "oslo", "kyiv", "rome"]}
    )
    pipe = sq.Pipeline(
        [("impute", sq.impute()), ("onehot", sq.encode.onehot(["city"]))]
    )
    pipe.learn(frame)
    assert dict(STORE.learns) == {"impute": 1, "onehot": 1}
    pipe.learn(frame)
    assert dict(STORE.learns) == {"impute": 1, "onehot": 1}
    assert pipe.runs_ == []
    frame.loc[0, "age"] = 30.0
    pipe.learn(frame)
    assert dict(STORE.learns) == {"impute": 2, "onehot": 2}
    assert pipe["impute"].value_ == {"age": 40.0}


BIG = """
    SELECT
        CASE WHEN i % 11 = 0 THEN NULL ELSE (hash(i, 1) % 1000) / 10 END::DOUBLE
            AS age,
        (hash(i, 2) % 100000)::DOUBLE AS income,
        ['kyiv', 'oslo', 'rome'][1 + (hash(i, 3) % 3)::BIGINT] AS city,
        ['basic', 'pro', 'team'][1 + (hash(i, 4) % 3)::BIGINT] AS plan
    FROM range(20000000) t(i)
"""


@pytest.mark.slow
def test_preparation_runs_larger_than_memory(tmp_path, capsys):
    """The slice's preparation learns and applies 20 million rows within 64 MB."""
    path = tmp_path / "big.parquet"
    duckdb.execute(f"COPY ({BIG}) TO '{path}' (FORMAT parquet)")
    con = duckdb.connect()
    con.execute("set memory_limit = '64MB'")
    con.execute("set threads = 1")
    con.execute(f"set temp_directory = '{tmp_path / 'spill'}'")
    sq.set_config(connection=con)
    pipe = sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric())),
        ]
    )
    out = tmp_path / "prepared.parquet"
    start = time.perf_counter()
    pipe.learn(str(path))
    pipe.apply(str(path), out=sq.out.parquet(out))
    elapsed = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n20 million rows prepared within 64 MB: {elapsed:.1f} s")  # noqa: T201

    # DuckDB's own median holds a column's values in memory: check it on a
    # connection without the limit.
    data = f"read_parquet('{path}')"
    medians = (
        duckdb.connect()
        .sql(f"SELECT median(age), median(income) FROM {data}")
        .fetchall()
    )
    assert pipe["impute"].value_ == pytest.approx(
        {"age": medians[0][0], "income": medians[0][1]}
    )
    filled = pipe["impute"].value_["age"]
    (mean,) = con.sql(f"SELECT avg(coalesce(age, {filled})) FROM {data}").fetchall()[0]
    assert pipe["scale"].center_["age"] == pytest.approx(mean, rel=1e-9)
    prepared = con.sql(f"SELECT count(*) FROM read_parquet('{out}')").fetchall()
    assert prepared == [(20_000_000,)]
