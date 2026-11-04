"""Tests of reading inputs and keying them for the store."""

import gc
import os
import weakref

import duckdb
import pandas as pd
import pytest

from sqlearn import SqlearnError, _config
from sqlearn import _inputs as inputs
from sqlearn._inputs import read


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


def test_a_relation_is_keyed_by_its_sql_and_rows():
    """A relation is keyed by its SQL text and row count."""
    rel = _config.connection().sql("SELECT 1 AS a")
    source = read(rel)
    assert source.key[0] == "relation"
    assert source.key[1] == rel.sql_query()
    assert source.key[2] == 1
    assert source.relation.fetchall() == [(1,)]


def test_a_relation_is_read_through_a_view_released_with_the_source():
    """A relation becomes a view on its connection, dropped with the source."""
    rel = _config.connection().sql("SELECT 1 AS a")
    source = read(rel)
    views = [v for v in _views() if v.startswith("_sqlearn_relation_")]
    assert len(views) == 1
    assert source.relation.sql_query() == f'SELECT * FROM "{views[0]}"'
    del source
    gc.collect()
    assert not any(v.startswith("_sqlearn_relation_") for v in _views())


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


def test_a_dropped_source_releases_its_frame():
    """The registered view and the reference to the frame go with the source."""
    df = pd.DataFrame({"a": [1, 2]})
    ref = weakref.ref(df)
    source = read(df)
    assert any(v.startswith("_sqlearn_frame_") for v in _views())
    del source
    gc.collect()
    assert not any(v.startswith("_sqlearn_frame_") for v in _views())
    del df
    gc.collect()
    assert ref() is None


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
