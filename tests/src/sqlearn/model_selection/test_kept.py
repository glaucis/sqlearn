"""Tests of kept preparations: fold tables in a DuckDB file, across searches."""

import os
import subprocess
import sys
import textwrap
import time

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._pipeline import Pipeline
from sqlearn.errors import SqlearnError
from sqlearn.model_selection import kept

PIPE_WITH_SCALE = sq.Pipeline(
    [("scale", sq.scale.standard()), ("model", LogisticRegression())]
)
DATA = pd.DataFrame({"x": np.arange(30.0), "y": [0, 1, 1] * 10})


@pytest.fixture
def data_file(tmp_path):
    """Write the test data to a parquet file."""
    path = tmp_path / "data.parquet"
    DATA.to_parquet(path)
    return path


def _count(rel):
    return rel.count("*").fetchall()[0][0]


def _attached():
    return {
        name
        for (name,) in connection()
        .sql("SELECT database_name FROM duckdb_databases()")
        .fetchall()
    }


def test_a_second_search_prepares_nothing(tmp_path, data_file):
    """A second search prepares nothing."""
    kept_file = tmp_path / "kept.duckdb"
    first = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(3),
        keep_prepared=kept_file,
    )
    first.train(data_file, target="y")
    sq.store.clear()  # a new session's in-process store
    second = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [0.5]},
        folds=sq.folds.kfold(3),
        keep_prepared=kept_file,
    )
    second.train(data_file, target="y")
    assert first.transforms_ == 3 and second.transforms_ == 0
    assert second.results_.count("*").fetchall()[0][0] == 3


def test_kept_folds_score_as_temporary_ones(tmp_path, data_file):
    """A search reading kept tables gives the same scores as one without."""
    plain = sq.search(
        PIPE_WITH_SCALE, params={"model__C": [1.0]}, folds=sq.folds.kfold(3)
    ).train(data_file, target="y")
    run = lambda: sq.search(  # noqa: E731
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(3),
        keep_prepared=tmp_path / "kept.duckdb",
    ).train(data_file, target="y")
    written, read_back = run(), run()
    assert read_back.transforms_ == 0
    assert written.best_score_ == plain.best_score_ == read_back.best_score_


def test_the_file_is_detached_after_train(tmp_path, data_file):
    """Nothing stays attached, so another process can open the file."""
    sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=tmp_path / "kept.duckdb",
    ).train(data_file, target="y")
    assert "__sqlearn_kept" not in _attached()
    with duckdb.connect(str(tmp_path / "kept.duckdb")) as other:
        assert other.sql("SELECT count(*) FROM sqlearn_prepared._index").fetchall() == [
            (2,)
        ]


def test_the_file_is_detached_when_train_raises(tmp_path, data_file, monkeypatch):
    """The file is detached when train raises."""

    def fail(*args, **kwargs):
        raise SqlearnError("preparing failed")

    monkeypatch.setattr(Pipeline, "_fold_query", fail)
    with pytest.raises(SqlearnError, match="preparing failed"):
        sq.search(
            PIPE_WITH_SCALE,
            params={"model__C": [1.0]},
            folds=sq.folds.kfold(2),
            keep_prepared=tmp_path / "kept.duckdb",
        ).train(data_file, target="y")
    assert "__sqlearn_kept" not in _attached()
    assert _count(sq.store.prepared(tmp_path / "kept.duckdb")) == 0


def test_a_changed_file_is_prepared_again(tmp_path, data_file):
    """A changed file is prepared again."""
    kept_file = tmp_path / "kept.duckdb"
    script = textwrap.dedent(
        f"""
        import sqlearn as sq
        from sklearn.linear_model import LogisticRegression
        pipe = sq.Pipeline(
            [("scale", sq.scale.standard()), ("model", LogisticRegression())]
        )
        search = sq.search(
            pipe, params={{"model__C": [1.0]}}, folds=sq.folds.kfold(2),
            keep_prepared={str(kept_file)!r},
        ).train({str(data_file)!r}, target="y")
        print(search.transforms_)
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "2"
    run = lambda: sq.search(  # noqa: E731
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept_file,
    ).train(data_file, target="y")
    assert run().transforms_ == 0  # the key survived the restart
    os.utime(data_file, (time.time() + 10, time.time() + 10))
    assert run().transforms_ == 2
    assert _count(sq.store.prepared(kept_file)) == 4


def test_other_steps_settings_or_folds_are_prepared_again(tmp_path, data_file):
    """Other steps, or other folds, are prepared again."""
    kept_file = tmp_path / "kept.duckdb"

    def run(pipe, folds):
        return sq.search(
            pipe, params={"model__C": [1.0]}, folds=folds, keep_prepared=kept_file
        ).train(data_file, target="y")

    run(PIPE_WITH_SCALE, sq.folds.kfold(2))
    other_steps = sq.Pipeline(
        [("scale", sq.scale.minmax()), ("model", LogisticRegression())]
    )
    assert run(other_steps, sq.folds.kfold(2)).transforms_ == 2
    assert run(PIPE_WITH_SCALE, sq.folds.kfold(2, seed=1)).transforms_ == 2
    assert run(PIPE_WITH_SCALE, sq.folds.kfold(2)).transforms_ == 0


def test_a_step_setting_searched_is_kept_per_setting(tmp_path, data_file):
    """A searched step setting is kept once per value."""
    kept_file = tmp_path / "kept.duckdb"
    pipe = sq.Pipeline(
        [("impute", sq.impute.median()), ("model", LogisticRegression())]
    )
    params = {"impute__value": ["median", "mean"], "model__C": [1.0, 2.0]}

    def run():
        return sq.search(
            pipe, params=params, folds=sq.folds.kfold(2), keep_prepared=kept_file
        ).train(data_file, target="y")

    assert run().transforms_ == 4
    assert run().transforms_ == 0


def test_a_frame_is_kept_by_its_content(tmp_path):
    """A frame is kept by its content."""
    kept_file = tmp_path / "kept.duckdb"
    run = lambda frame: sq.search(  # noqa: E731
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept_file,
    ).train(frame, target="y")
    assert run(DATA).transforms_ == 2
    assert run(DATA.copy()).transforms_ == 0
    edited = DATA.copy()
    edited.loc[0, "x"] = 99.0
    assert run(edited).transforms_ == 2


def test_an_input_without_a_stable_identity_is_refused(tmp_path):
    """An input without a stable identity is refused."""
    rel = duckdb.sql("SELECT 1.0 AS x, 0 AS y")
    with pytest.raises(SqlearnError, match="keep_prepared"):
        sq.search(PIPE_WITH_SCALE, keep_prepared=tmp_path / "k.duckdb").train(
            rel, target="y"
        )


def test_a_relation_or_in_memory_table_of_the_connection_is_refused(tmp_path):
    """A relation or an in-memory table of the connection is refused."""
    con = connection()
    con.execute("CREATE OR REPLACE TABLE kept_in_memory AS FROM DATA")
    try:
        for data in (con.sql("FROM DATA"), "kept_in_memory"):
            with pytest.raises(SqlearnError, match="keep_prepared"):
                sq.search(
                    PIPE_WITH_SCALE,
                    params={"model__C": [1.0]},
                    folds=sq.folds.kfold(2),
                    keep_prepared=tmp_path / "k.duckdb",
                ).train(data, target="y")
    finally:
        con.execute("DROP TABLE kept_in_memory")


def test_the_connection_own_database_file_can_keep_them(tmp_path):
    """Kept in the database sqlearn computes in: used as it is, never detached."""
    path = tmp_path / "project.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE data AS FROM DATA")
    sq.set_config(connection=con)
    run = lambda: sq.search(  # noqa: E731
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=path,
    ).train("data", target="y")
    assert run().transforms_ == 2
    assert run().transforms_ == 0
    assert con.sql("SELECT count(*) FROM sqlearn_prepared._index").fetchall() == [(2,)]


def test_clear_removes_the_kept_tables(tmp_path, data_file):
    """`clear(prepared=...)` drops every kept table and index row."""
    kept_file = tmp_path / "kept.duckdb"
    sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept_file,
    ).train(data_file, target="y")
    sq.store.clear(prepared=kept_file)
    assert _count(sq.store.prepared(kept_file)) == 0
    with duckdb.connect(str(kept_file)) as other:
        tables = other.sql(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE schema_name = 'sqlearn_prepared'"
        ).fetchall()
    assert tables == [("_index",)]


def test_the_index_names_each_kept_table(tmp_path, data_file):
    """The index names each kept table."""
    kept_file = tmp_path / "kept.duckdb"
    sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept_file,
    ).train(data_file, target="y")
    index = sq.store.prepared(kept_file)
    assert index.columns == [
        "table", "data", "steps", "folds", "fold", "sqlearn_version", "created",
    ]  # fmt: skip
    rows = index.order("fold").fetchall()
    assert [r[4] for r in rows] == [0, 1]
    assert all(r[0].startswith(f"fold_{r[4]}_") for r in rows)
    assert all(r[5] == sq.__version__ for r in rows)


def test_prepared_of_a_missing_file_is_empty(tmp_path):
    """`prepared` of a missing file has no row and makes no file."""
    index = sq.store.prepared(tmp_path / "none.duckdb")
    assert _count(index) == 0
    assert not (tmp_path / "none.duckdb").exists()


def test_the_table_name_carries_the_key():
    """The table name carries the key."""
    steps = [("scale", sq.scale.standard())]
    name = kept.table_name(("file", "a"), steps, ("kfold", 3, 0), 1)
    assert name.startswith("fold_1_")
    assert len(name) == len("fold_1_") + 12
    assert name == kept.table_name(("file", "a"), steps, ("kfold", 3, 0), 1)
    assert name != kept.table_name(("file", "b"), steps, ("kfold", 3, 0), 1)
    assert name != kept.table_name(("file", "a"), steps, ("kfold", 3, 1), 1)
    other = [("scale", sq.scale.minmax())]
    assert name != kept.table_name(("file", "a"), other, ("kfold", 3, 0), 1)


def test_the_table_name_is_the_same_in_another_process():
    """The table name is the same in another process."""
    code = (
        "import sqlearn as sq\n"
        "from sqlearn.model_selection import kept\n"
        "print(kept.table_name(('file', 'a'), [('scale', sq.scale.standard())],"
        " ('kfold', 3, 0), 1))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    steps = [("scale", sq.scale.standard())]
    assert done.stdout.strip() == kept.table_name(
        ("file", "a"), steps, ("kfold", 3, 0), 1
    )


def _plus_one(x):
    return x + 1


def test_a_step_function_is_known_by_its_dotted_name():
    """A step function is known by its dotted name."""
    step = [("step", sq.Step(apply=_plus_one, cols=["x"]))]
    [(_, _, settings)] = kept.steps_identity(step)
    assert dict(settings)["apply"] == f"{__name__}._plus_one"


def test_a_lambda_or_an_object_without_a_repr_is_refused_for_keeping():
    """A lambda or an object without a repr is refused for keeping."""
    lam = [("step", sq.Step(apply=lambda x: x + 1, cols=["x"]))]
    with pytest.raises(SqlearnError, match="lambda"):
        kept.steps_identity(lam)

    class Opaque:
        pass

    class WithObject(sq.Step):
        def __init__(self, thing=None, cols=None):
            super().__init__(cols=cols)
            self.thing = thing

    with pytest.raises(SqlearnError, match="no repr of its own"):
        kept.steps_identity([("step", WithObject(thing=Opaque()))])
