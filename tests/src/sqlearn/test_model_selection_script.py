"""The model-selection spec's script (§2), end to end, and larger than memory.

The script, its data and scikit-learn's side live in the validation runner
(``validation/pipelines/validate_model_selection.py``), so the test and the
recorded validation run the very same code.
"""

import json
import subprocess
import sys

import duckdb
import pandas as pd
import pytest

import sqlearn as sq
from validation.pipelines import validate_model_selection as script

ROWS = 20_000
"""The script's training rows, scaled down from data larger than memory."""


def run_the_script(root, monkeypatch, trials=3):
    """Run §2's script from `root`, scaled down: few trials, small CatBoosts."""
    monkeypatch.chdir(root)
    return script.run_the_script(trials=trials, iterations=30)


def tmp_data_files(root, rows):
    """Write the script's Parquet files under `root`; return `root`."""
    return script.write_data(root, rows)


def test_the_script_runs(tmp_path, monkeypatch):
    """§2's script: Optuna over CatBoost, kept folds, scored files, a stream.

    Each of the 5 stratified folds is prepared once for every trial, as the
    kept file holds it; a second search on the same data and steps prepares
    nothing. CatBoost is handed text as categories, and its predictions are
    written to a Parquet file, one row per new row.
    """
    search, stream = run_the_script(tmp_data_files(tmp_path, ROWS), monkeypatch)
    assert set(search.best_params_) == {"model__depth", "model__learning_rate"}
    assert 4 <= search.best_params_["model__depth"] <= 10
    assert isinstance(search.best_params_["model__depth"], int)
    assert 0.01 <= search.best_params_["model__learning_rate"] <= 0.3
    assert 0 < search.best_score_ < 0.69  # better than a coin's log loss
    assert search.results_.count("*").fetchall() == [(15,)]
    assert search.transforms_ == 5
    assert len(sq.store.prepared("churn.duckdb")) == 5
    scored = duckdb.read_parquet("scored.parquet").df()
    assert list(scored.columns) == ["prediction"]
    assert len(scored) == ROWS // 5
    assert set(scored["prediction"]) <= {0, 1}
    predicted = stream.predict("data/new/*.parquet", out="pandas")
    assert isinstance(predicted, pd.DataFrame)
    assert len(predicted) == ROWS // 5

    again, _ = run_the_script(tmp_path, monkeypatch, trials=2)
    assert again.transforms_ == 0


def test_the_search_matches_scikit_learn():
    """Every validation case passes: scores, best settings, folds, repeats."""
    failed = [c for c in script.cases() if c["result"] != "pass"]
    assert failed == []


PEAK_BOUND = 384_000_000
"""The most a run may add to the process's peak memory: the budget and a half.

Measured on an 8-core macOS machine with 16 GB (2026-11-08), at 20 million
rows, over two runs: training added 162 to 188 MB to the peak (about 55 s),
and predicting all 20 million rows into a Parquet file 148 to 150 MB (3 s,
with the model trained on 10,000 rows so that training leaves no higher
peak); the whole test takes about 65 s. Without the budget
(``memory="16GB"``) the same training added 3.6 GB and the prediction
655 MB: the bound is what the budget holds, and the prediction's table in
DuckDB's attached in-memory database spills as a temporary table does. In
``just verify`` (four runs, under load) training added 131 to 244 MB and
predicting 148 to 167 MB, so the bound is half as much again as the budget,
still a tenth of what training adds without it.
"""

BIG = """
    SELECT
        CASE WHEN i % 11 = 0 THEN NULL ELSE (hash(i, 1) % 1000) / 10 END::DOUBLE
            AS a,
        (hash(i, 2) % 100000)::DOUBLE AS b,
        (hash(i, 3) % 997)::DOUBLE AS c,
        CASE WHEN i % 13 = 0 THEN NULL ELSE (hash(i, 4) % 5000) / 100 END::DOUBLE
            AS d,
        (hash(i, 5) % 365)::DOUBLE AS e,
        (hash(i, 6) % 10000)::DOUBLE / 7 AS f,
        ((hash(i, 1) % 1000) / 10 + (hash(i, 2) % 100000) / 2000
            + hash(i, 7) % 40 > 95)::INTEGER AS churned
    FROM range({rows}) t(i)
"""
"""Six numbers and a target: 20 million rows are about 1 GB of numbers."""

CHILD = """
import json, resource, sys
import sqlearn as sq
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sqlearn._config import connection


def peak():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024  # Linux: KB


part, path, out = sys.argv[1:]
sq.set_config(memory="256MB")
connection().execute("SET threads = 1")
pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.Model(SGDClassifier(loss="log_loss"), feed="stream", rows=100_000),
    ]
)
report = {}
if part == "train":
    before = peak()
    pipe.train(path, target="churned")
    report["grown"] = peak() - before
    try:
        sq.Pipeline([sq.impute.median(), sq.Model(LogisticRegression())]).train(
            path, target="churned"
        )
    except sq.errors.SqlearnError as exc:
        report["refused"] = str(exc)
else:
    small = connection().read_parquet(path).limit(10_000)
    pipe.train(small, target="churned")
    pipe.predict(small.limit(100), out="numpy")
    before = peak()
    pipe.predict(path, out=sq.out.parquet(out))
    report["grown"] = peak() - before
    report["rows"] = connection().read_parquet(out).count("*").fetchall()[0][0]
print("report:", json.dumps(report))
"""
"""One part of the run in a fresh process, reporting what it added to its peak.

A process's peak (``ru_maxrss``) only grows, so a part measured in the test
process would read the peak of the tests before it. Each part runs alone:
training on every row, then (``predict``) predicting every row with a model
trained on a few. ``ru_maxrss`` is bytes on macOS and kilobytes on Linux.
DuckDB runs on one thread, as the core's slow tests do: at 128 MB, the
budget's DuckDB half, eight threads each holding their own buffers run out
of memory in the median's sort.
"""


def run_part(part, path, tmp_path):
    """Run one part of the big run in its own process; return its report."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD,
            part,
            str(path),
            str(tmp_path / "scored.parquet"),
        ],
        cwd=tmp_path,  # DuckDB spills into .tmp here
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    # DuckDB's progress bar may share the line: the report is what follows.
    return json.loads(done.stdout.rpartition("report: ")[2])


@pytest.mark.slow
def test_the_stream_trains_larger_than_memory(tmp_path, capsys):
    """§2's streamed pipeline on 20 million rows within a 256 MB budget.

    Training and predicting each add less than `PEAK_BOUND` to the peak, and
    a model handed the rows whole is refused before the fetch, suggesting
    the stream.
    """
    path = tmp_path / "big.parquet"
    duckdb.execute(f"COPY ({BIG.format(rows=20_000_000)}) TO '{path}' (FORMAT parquet)")
    trained = run_part("train", path, tmp_path)
    predicted = run_part("predict", path, tmp_path)
    with capsys.disabled():
        print(  # noqa: T201
            f"\n20 million rows streamed in a 256 MB budget: training added "
            f"{trained['grown'] / 1e6:.0f} MB to the peak, predicting "
            f"{predicted['grown'] / 1e6:.0f} MB"
        )
    assert trained["grown"] < PEAK_BOUND
    assert predicted["grown"] < PEAK_BOUND
    assert predicted["rows"] == 20_000_000
    assert 'feed="stream"' in trained["refused"]
