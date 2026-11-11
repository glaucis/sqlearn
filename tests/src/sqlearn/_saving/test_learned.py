"""``sq.save`` and ``sq.load`` for what a pipeline learned."""

import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest
from duckdb import ConstantExpression, Expression

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._store import STORE


class Least(sq.Step):
    """Learn each column's minimum and put it in every row."""

    state_version = 1

    def learn(self, x):
        """Learn the minimum."""
        return {"min": sq.agg.min(x)}

    def apply(self, x, learned):
        """Put the minimum learned in place of the column."""
        least = learned.min
        # A learned list stays a Python list: make it a constant.
        return least if isinstance(least, Expression) else ConstantExpression(least)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20.0, None, 40.0, 50.0, 31.0, 22.0],
            "income": [1.0, 2.0, None, 4.0, 3.5, 0.5],
            "city": ["a", "b", "a", "b", "a", "b"],
            "town": ["x", "y", "x", None, "y", "x"],
            "y": [1.0, 0.0, 1.0, 1.0, 0.0, 0.0],
        }
    )


def _learned(df: pd.DataFrame) -> sq.Pipeline:
    pipe = sq.Pipeline(
        [
            ("impute", sq.impute.median()),
            ("target", sq.encode.target("city")),
            ("scale", sq.scale.standard()),
            ("onehot", sq.encode.onehot("town")),
        ]
    )
    return pipe.learn(df, target="y")


def _sql(pipe: sq.Pipeline) -> str:
    # Each read registers the data under a new name: compare the rest.
    statement = pipe.runs_[0].statements[0]
    return re.sub(r"_sqlearn_(frame|relation)_\d+", "_sqlearn_data", statement)


def _rows(result: object) -> list[tuple[Any, ...]]:
    if isinstance(result, pd.DataFrame):
        return list(result.itertuples(index=False, name=None))
    assert isinstance(result, duckdb.DuckDBPyRelation)
    return result.fetchall()


def test_a_loaded_pipeline_applies_without_learning(tmp_path: Path) -> None:
    """A loaded pipeline applies the same SQL, with no learn."""
    df = _frame()
    pipe = _learned(df)
    want = _rows(pipe.apply(df))
    sql = _sql(pipe)
    sq.save(pipe, tmp_path / "p.json")
    sq.store.clear()
    loaded = sq.load(tmp_path / "p.json")
    got = _rows(loaded.apply(df))
    assert not STORE.learns
    assert _sql(loaded) == sql
    assert got == want


def test_learned_values_read_as_attributes_after_load(tmp_path: Path) -> None:
    """A step's learned values read as attributes after load."""
    pipe = _learned(_frame())
    sq.save(pipe, tmp_path / "p.json")
    learned = json.loads((tmp_path / "p.json").read_text())["learned"]
    assert list(learned) == [
        "data", "target", "columns_out", "types", "names", "depends_on", "steps",
    ]  # fmt: skip
    assert learned["data"] == {"kind": "unknown"}
    assert list(learned["steps"][0]) == ["columns", "values", "folds"]
    loaded = sq.load(tmp_path / "p.json")
    # sq.impute.median() learns its medians as "value".
    assert loaded["impute"].value_ == pipe["impute"].value_
    assert loaded["target"].encodings_ == pipe["target"].encodings_
    assert loaded.columns_out_ == pipe.columns_out_


def test_a_pipeline_saved_without_its_learned_part_loads_unlearned(
    tmp_path: Path,
) -> None:
    """With learned=False, a learned pipeline loads as a recipe."""
    df = _frame()
    sq.save(_learned(df), tmp_path / "p.json", learned=False)
    with pytest.raises(SqlearnError, match="has not learned yet"):
        sq.load(tmp_path / "p.json").apply(df)


def test_a_changed_state_version_loads_the_recipe_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step whose state version changed loads unlearned, with a warning."""
    data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    pipe = sq.Pipeline([("least", Least())]).learn(data)
    sq.save(pipe, tmp_path / "p.json")
    monkeypatch.setattr(Least, "state_version", 2)
    with pytest.warns(SqlearnWarning) as caught:
        loaded = sq.load(tmp_path / "p.json", allow=["tests"])
    message = str(caught[0].message)
    assert "least" in message and "1" in message and "2" in message
    assert "Fix:" in message
    with pytest.raises(SqlearnError, match="has not learned yet"):
        loaded.apply(data)


def _round_trips(tmp_path: Path, sql: str, columns: list[str]) -> None:
    data = connection().sql(sql)
    pipe = sq.Pipeline([("least", Least(cols=columns))]).learn(data)
    want = pipe.apply(data).fetchall()
    statement = _sql(pipe)
    sq.save(pipe, tmp_path / "p.json")
    loaded = sq.load(tmp_path / "p.json", allow=["tests"])
    assert loaded.apply(data).fetchall() == want
    assert _sql(loaded) == statement


def test_a_learned_value_of_every_type_round_trips(tmp_path: Path) -> None:
    """Learned values of DuckDB's own types apply as the same SQL after load."""
    _round_trips(
        tmp_path,
        """
        SELECT * FROM (VALUES
            (DATE '2024-01-02', TIMESTAMP '2024-01-02 03:04:05.123456',
             12.50::DECIMAL(10, 2), '\\xAA\\x00'::BLOB,
             '5f0c1f4e-3b0a-4a39-9c3e-2d6c5f0b1a2e'::UUID, ['b', 'a']),
            (DATE '2025-06-07', TIMESTAMP '2025-06-07 08:09:10',
             99.99::DECIMAL(10, 2), '\\xFF'::BLOB,
             'ffffffff-3b0a-4a39-9c3e-2d6c5f0b1a2e'::UUID, ['c'])
        ) t(d, ts, money, raw, id, tags)
        """,
        ["d", "ts", "money", "raw", "id", "tags"],
    )


def test_a_learned_timestamp_with_a_zone_round_trips(tmp_path: Path) -> None:
    """A learned TIMESTAMP WITH TIME ZONE applies as the same SQL after load."""
    # DuckDB returns a zoned timestamp to Python only with pytz installed.
    pytest.importorskip("pytz")
    _round_trips(
        tmp_path,
        """
        SELECT * FROM (VALUES
            (TIMESTAMPTZ '2024-01-02 03:04:05.123456+02'),
            (TIMESTAMPTZ '2025-06-07 08:09:10+00')
        ) t(ts)
        """,
        ["ts"],
    )
