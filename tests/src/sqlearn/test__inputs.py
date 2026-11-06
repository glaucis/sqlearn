"""Tests of reading inputs and keying them for the store."""

import gc
import os
import sys
import weakref

import duckdb
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn import _config
from sqlearn import _inputs as inputs
from sqlearn._inputs import read
from sqlearn._store import STORE
from sqlearn.errors import SqlearnError


def _write(path, text, mtime_ns=None):
    path.write_text(text)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def test_a_file_key_changes_when_the_file_changes(tmp_path):
    """Rewriting a file with other content and a later mtime changes the key."""
    path = tmp_path / "d.csv"
    _write(path, "a\n1\n", 1_000_000_000)
    first = read(path)
    assert first.relation.fetchall() == [(1,)]
    _write(path, "a\n1\n2\n", 2_000_000_000)
    second = read(str(path))
    assert first.key[0] == "file"
    assert first.key != second.key
    assert second.relation.fetchall() == [(1,), (2,)]
    assert [name for name, _ in first.schema] == ["a"]
    assert {second.key: 1}[read(path).key] == 1


def test_a_glob_reads_all_matches_in_order(tmp_path):
    """A glob reads every match, sorted by path."""
    _write(tmp_path / "b.csv", "a\n2\n")
    _write(tmp_path / "a.csv", "a\n1\n")
    source = read(str(tmp_path / "*.csv"))
    assert source.relation.fetchall() == [(1,), (2,)]
    assert len(source.key[1]) == 2


def test_a_glob_matching_nothing_is_named(tmp_path):
    """A pattern with no match raises an error naming it."""
    pattern = str(tmp_path / "*.parquet")
    with pytest.raises(SqlearnError, match=r"\*\.parquet"):
        read(pattern)


def test_parquet_and_json_are_read(tmp_path):
    """Parquet and JSON files are read, whatever the case of the suffix."""
    con = _config.connection()
    con.sql("SELECT 1 AS a").write_parquet(str(tmp_path / "p.PARQUET"))
    _write(tmp_path / "j.json", '[{"a": 5}]')
    assert read(tmp_path / "p.PARQUET").relation.fetchall() == [(1,)]
    assert read(tmp_path / "j.json").relation.fetchall() == [(5,)]


def test_a_table_name_is_keyed_by_row_count():
    """A table name reads that table; adding a row changes the key."""
    con = _config.connection()
    con.execute("CREATE TABLE t AS SELECT 1 AS a")
    first = read("t")
    con.execute("INSERT INTO t VALUES (2)")
    second = read("t")
    assert first.key[0] == "table"
    assert first.key != second.key
    assert second.relation.fetchall() == [(1,), (2,)]


def test_a_relation_is_keyed_by_its_connection_sql_and_rows():
    """A relation is keyed by its connection, SQL text and row count."""
    con = _config.connection()
    rel = con.sql("SELECT 1 AS a")
    source = read(rel)
    assert source.key[0] == "relation"
    assert source.key[1] == inputs._connection_token(con)
    assert source.key[2] == rel.sql_query()
    assert source.key[3] == 1
    assert source.relation.fetchall() == [(1,)]


def test_a_connection_token_is_never_given_twice():
    """Two connections get different tokens, and one keeps its own."""
    a, b = duckdb.connect(), duckdb.connect()
    assert inputs._connection_token(a) != inputs._connection_token(b)
    assert inputs._connection_token(a) == inputs._connection_token(a)


def test_equal_tables_on_two_connections_learn_their_own_values():
    """Same table name, same row count, other connection: learned anew (ADR 0014)."""
    a, b = duckdb.connect(), duckdb.connect()
    a.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1.0), (2.0), (3.0)) v(x)")
    b.execute("CREATE TABLE t AS SELECT * FROM (VALUES (10.0), (20.0), (60.0)) v(x)")
    _config.set_config(connection=a)
    first = sq.Pipeline([("fill", sq.impute.mean())]).learn(a.table("t"))
    assert first["fill"].value_ == {"x": 2.0}
    _config.set_config(connection=b)
    second = sq.Pipeline([("fill", sq.impute.mean())]).learn(b.table("t"))
    assert second["fill"].value_ == {"x": 30.0}
    assert STORE.learns["fill"] == 2


def test_a_relation_is_read_through_a_view_released_with_the_source():
    """A relation becomes a temporary view, dropped at the call after the source."""
    rel = _config.connection().sql("SELECT 1 AS a")
    source = read(rel)
    views = [v for v in _views() if v.startswith("_sqlearn_relation_")]
    assert len(views) == 1
    assert source.relation.sql_query() == f'SELECT * FROM "{views[0]}"'
    del source
    gc.collect()
    _next_call()
    assert not any(v.startswith("_sqlearn_relation_") for v in _views())


def test_a_relation_never_leaves_a_view_in_a_database_file(tmp_path):
    """The view is temporary: none is stored, even while the source is alive."""
    path = str(tmp_path / "user.db")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE t AS SELECT range::DOUBLE AS x FROM range(10)")
    _config.set_config(connection=con)
    rel = con.sql("SELECT * FROM t WHERE x > 1")
    pipe = sq.Pipeline([("s", sq.scale.standard())]).learn(rel)
    out = pipe.apply(rel)
    con.execute("CHECKPOINT")
    stored = con.sql(
        "SELECT view_name FROM duckdb_views() WHERE NOT temporary AND NOT internal"
    )
    assert stored.fetchall() == []
    assert len(out.fetchall()) == 8
    con.close()
    again = duckdb.connect(path)
    assert (
        again.sql("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()
        == []
    )
    again.close()


def test_a_read_only_database_accepts_a_relation(tmp_path):
    """Reading a relation writes nothing to the user's database."""
    path = str(tmp_path / "user.db")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE t AS SELECT range::DOUBLE AS x FROM range(10)")
    con.close()
    con = duckdb.connect(path, read_only=True)
    _config.set_config(connection=con)
    pipe = sq.Pipeline([("s", sq.scale.standard())]).learn(
        con.sql("SELECT * FROM t WHERE x > 1")
    )
    assert pipe["s"].center_ == {"x": 5.5}
    con.close()


def test_a_relation_of_another_connection_is_refused():
    """A relation on another connection is refused, saying how to fix it."""
    other = duckdb.connect()
    rel = other.sql("SELECT 1 AS a")
    with pytest.raises(SqlearnError, match=r"another DuckDB connection.*set_config"):
        read(rel)
    left = other.sql("SELECT view_name FROM duckdb_views()").fetchall()
    assert not any(v[0].startswith("_sqlearn_relation_") for v in left)


def test_a_replacement_scan_relation_is_read():
    """A relation scanning a Python frame by its name keeps working."""
    frame = pd.DataFrame({"a": [1.0, 3.0]})
    rel = _config.connection().sql("FROM frame")
    source = read(rel)
    del frame, rel
    gc.collect()
    assert source.relation.fetchall() == [(1.0,), (3.0,)]


def test_a_relation_duckdb_cannot_read_is_an_input_error():
    """A relation whose table is gone is named as the input, not a step."""
    con = _config.connection()
    con.sql("CREATE TABLE gone AS SELECT 1 AS a")
    rel = con.table("gone")
    con.sql("DROP TABLE gone")
    with pytest.raises(SqlearnError, match="cannot read the relation"):
        read(rel)


def test_an_edited_frame_gets_a_new_key():
    """Changing one value changes the frame's key; equal frames agree."""
    df = pd.DataFrame({"age": [1, 2, 3], "city": ["a", "b", "c"]})
    first = read(df)
    assert first.key == read(df.copy()).key
    df.loc[0, "age"] = 999
    assert first.key[0] == "frame"
    assert read(df).key != first.key


def test_reordered_rows_get_a_new_key():
    """The same rows in another order give another key."""
    df = pd.DataFrame({"age": [1, 2, 3]})
    assert read(df).key != read(df.iloc[::-1].reset_index(drop=True)).key
    assert read(df).relation.fetchall() == [(1,), (2,), (3,)]


def test_renamed_or_swapped_columns_get_a_new_key():
    """The same values under other names, or of another type, get another key."""
    df = pd.DataFrame({"a": [1.0, 2.0, 4.0], "b": [50.0, 60.0, 70.0]})
    swapped = pd.DataFrame({"b": [1.0, 2.0, 4.0], "a": [50.0, 60.0, 70.0]})
    keys = {read(df).key, read(swapped).key, read(df.rename(columns={"a": "z"})).key}
    assert len(keys) == 3
    assert read(df).key != read(df.astype("float32")).key


def test_swapped_columns_are_learned_again():
    """A frame with the names swapped is learned, not found in the store."""
    df = pd.DataFrame({"a": [1.0, 2.0, 4.0], "b": [50.0, 60.0, 70.0]})
    swapped = pd.DataFrame({"b": [1.0, 2.0, 4.0], "a": [50.0, 60.0, 70.0]})
    pipe = sq.Pipeline([("s", sq.scale.standard())]).learn(df)
    pipe.learn(swapped)
    assert pipe["s"].center_ == {"a": 60.0, "b": pytest.approx(7 / 3)}
    renamed = df.rename(columns={"a": "z"})
    assert pipe.learn(renamed)["s"].center_ == {"z": pytest.approx(7 / 3), "b": 60.0}


def test_a_table_or_relation_key_holds_its_schema():
    """Renaming a table's column, keeping its rows, changes its key."""
    con = _config.connection()
    con.execute("CREATE TABLE r AS SELECT 1 AS a")
    first = read("r")
    con.execute("ALTER TABLE r RENAME COLUMN a TO b")
    assert read("r").key != first.key
    assert read("r").key[-1] == (("b", "INTEGER"),)
    assert read(con.sql("SELECT 1 AS a")).key[-1] == (("a", "INTEGER"),)


def test_two_frames_do_not_collide():
    """Two frames read one after the other keep their own data."""
    a = read(pd.DataFrame({"x": [1]}))
    b = read(pd.DataFrame({"x": [2]}))
    assert a.relation.fetchall() == [(1,)]
    assert b.relation.fetchall() == [(2,)]


def test_a_polars_frame_is_refused_with_the_reason():
    """Polars is refused, pointing to the spec."""
    pl = pytest.importorskip("polars")
    with pytest.raises(SqlearnError, match=r"after the core.*§7"):
        read(pl.DataFrame({"a": [1]}))


def test_anything_else_lists_what_is_accepted():
    """An unsupported object raises an error listing accepted inputs."""
    with pytest.raises(SqlearnError, match="accepted"):
        read(42)


def test_a_missing_table_is_named():
    """A name that is no table raises an error naming it."""
    with pytest.raises(SqlearnError, match="nowhere"):
        read("nowhere")


def test_relation_type_is_duckdb():
    """The source's relation is a DuckDB relation."""
    source = read(pd.DataFrame({"a": [1]}))
    assert isinstance(source.relation, duckdb.DuckDBPyRelation)


def _views():
    rows = _config.connection().sql("SELECT view_name FROM duckdb_views()")
    return [r[0] for r in rows.fetchall()]


def _next_call():
    """Make a public call that registers nothing: it releases what is pending."""
    con = _config.connection()
    con.execute("CREATE OR REPLACE TABLE _next AS SELECT 1.0 AS x")
    sq.Pipeline([("s", sq.scale.standard())]).learn("_next")


def test_a_dropped_source_releases_its_frame():
    """The registered view and the reference to the frame go with the source."""
    df = pd.DataFrame({"a": [1, 2]})
    ref = weakref.ref(df)
    source = read(df)
    assert any(v.startswith("_sqlearn_frame_") for v in _views())
    del source
    gc.collect()
    _next_call()
    assert not any(v.startswith("_sqlearn_frame_") for v in _views())
    del df
    gc.collect()
    assert ref() is None


class _Model:
    """A model that predicts 0 for every row."""

    def fit(self, x, y):
        """Learn nothing."""
        return self

    def predict(self, x):
        """Predict 0."""
        return [0] * len(x)


def test_a_finaliser_never_calls_the_connection(monkeypatch):
    """With the collector firing all the time, nothing is raised, and nothing
    stays registered or alive after the next call."""
    raised = []
    monkeypatch.setattr(sys, "unraisablehook", raised.append)
    refs = []
    threshold = gc.get_threshold()
    gc.set_threshold(1, 1, 1)
    try:
        for _ in range(3):
            df = pd.DataFrame({"city": ["a", "b"], "x": [1.0, 2.0], "city_a": [0, 1]})
            refs.append(weakref.ref(df))
            pipe = sq.Pipeline(
                [("oh", sq.encode.onehot(["city"])), ("model", _Model())]
            )
            try:
                pipe.train(df, target="city_a")
            except (
                sq.errors.StepError
            ) as exc:  # its traceback holds the source in a cycle
                assert "city_a" in str(exc)  # noqa: PT017
            del df
            big = pd.DataFrame({"x": range(200_000), "y": [0, 1] * 100_000})
            big["c"] = big["y"].astype(str)  # scanning text calls into Python
            steps = [
                ("s", sq.scale.standard()),
                ("o", sq.encode.ordinal()),
                ("model", _Model()),
            ]
            pipe = sq.Pipeline(steps)
            pipe.train(big, target="y").predict(big).fetchall()
            sq.Pipeline([("s", sq.scale.standard())]).learn(big).apply(big).fetchall()
            del big, pipe
    finally:
        gc.set_threshold(*threshold)
    gc.collect()
    _next_call()
    assert raised == []
    assert not any(v.startswith("_sqlearn_") for v in _views())
    assert all(r() is None for r in refs)


def test_a_frame_is_not_copied_in_the_normal_case(monkeypatch):
    """A normal frame is registered itself, not a copy of it."""
    registered = []
    real = _config.connection()

    class Spy:
        def register(self, name, obj):
            registered.append(obj)
            return real.register(name, obj)

        def __getattr__(self, attr):
            return getattr(real, attr)

    monkeypatch.setattr(inputs, "connection", Spy)
    df = pd.DataFrame({"a": [1, 2]})
    source = read(df)
    assert len(registered) == 1
    assert registered[0] is df
    assert source.relation.fetchall() == [(1,), (2,)]
