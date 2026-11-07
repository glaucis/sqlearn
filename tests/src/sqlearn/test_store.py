"""Tests of the public store."""

import pandas as pd

import sqlearn as sq
from sqlearn._store import STORE


def test_store_clear_relearns():
    """A `learn` after ``sq.store.clear()`` learns again."""
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    pipe = sq.Pipeline([("scale", sq.scale.standard())])
    pipe.learn(frame)
    pipe.learn(frame)
    assert STORE.learns["scale"] == 1
    sq.store.clear()
    assert len(STORE) == 0
    pipe.learn(frame)
    assert STORE.learns["scale"] == 1  # counts cleared, then one learn


def test_clear_of_a_missing_prepared_file_does_nothing(tmp_path):
    """Clearing a missing prepared file makes no file."""
    sq.store.clear(prepared=tmp_path / "none.duckdb")
    assert not (tmp_path / "none.duckdb").exists()


def test_prepared_lists_the_index_columns(tmp_path):
    """`prepared` lists the index columns."""
    index = sq.store.prepared(tmp_path / "none.duckdb")
    assert index.columns == [
        "table", "data", "steps", "folds", "fold", "sqlearn_version", "created",
    ]  # fmt: skip
