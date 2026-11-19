"""``sq.save`` and ``sq.load`` for what a pipeline learned."""

import json
import re
import sys
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
from tests.src.sqlearn._saving import test_recipe as recipe_cases


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


# best warns that "flat" is constant, at learn and again at load.
@pytest.mark.filterwarnings("ignore::sqlearn._errors.SqlearnWarning")
@pytest.mark.parametrize(
    "step",
    [sq.select.variance(), sq.select.best(k=1)],
    ids=repr,
)
def test_a_last_step_dropping_columns_loads(tmp_path: Path, step: sq.Step) -> None:
    """A last step giving nothing for a column it learned from still loads.

    A feature selector drops a column it scored: the columns out lack it,
    as the step gives them.
    """
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 5.0, 6.0],
            "flat": [3.0, 3.0, 3.0, 3.0],
            "y": [0, 0, 1, 1],
        }
    )
    pipe = sq.Pipeline([step]).learn(df, target="y")
    assert pipe.columns_out_ == ["a"]
    sq.save(pipe, tmp_path / "p.json")
    sq.store.clear()
    loaded = sq.load(tmp_path / "p.json")
    assert loaded.columns_out_ == ["a"]
    assert _rows(loaded.apply(df)) == _rows(pipe.apply(df))
    assert not STORE.learns


def test_learned_values_read_as_attributes_after_load(tmp_path: Path) -> None:
    """A step's learned values read as attributes after load."""
    pipe = _learned(_frame())
    sq.save(pipe, tmp_path / "p.json")
    learned = json.loads((tmp_path / "p.json").read_text())["learned"]
    assert list(learned) == [
        "data", "target", "columns_out", "types", "names", "depends_on", "steps",
    ]  # fmt: skip
    assert list(learned["data"]) == ["kind", "rows", "digest", "columns"]
    assert learned["data"]["kind"] == "frame"
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
        loaded = sq.load(tmp_path / "p.json")
    message = str(caught[0].message)
    assert "least" in message and "1" in message and "2" in message
    assert "Fix:" in message
    with pytest.raises(SqlearnError, match="has not learned yet"):
        loaded.apply(data)


def _round_trips(
    tmp_path: Path, sql: str, columns: list[str], *, as_text: bool = False
) -> None:
    def fetch(rel: duckdb.DuckDBPyRelation) -> list[tuple[Any, ...]]:
        # A zoned timestamp reaches Python only through pytz: read it as text.
        return (
            rel.project("CAST(COLUMNS(*) AS VARCHAR)") if as_text else rel
        ).fetchall()

    data = connection().sql(sql)
    pipe = sq.Pipeline([("least", Least(cols=columns))]).learn(data)
    want = fetch(pipe.apply(data))
    statement = _sql(pipe)
    sq.save(pipe, tmp_path / "p.json")
    loaded = sq.load(tmp_path / "p.json")
    assert fetch(loaded.apply(data)) == want
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
    """A learned TIMESTAMP WITH TIME ZONE applies as the same SQL after load.

    Alone or nested in a list or a struct, and with no pytz (#56).
    """
    _round_trips(
        tmp_path,
        """
        SELECT ts, [ts] AS listed, {'at': ts} AS held FROM (VALUES
            (TIMESTAMPTZ '2024-01-02 03:04:05.123456+02'),
            (TIMESTAMPTZ '2025-06-07 08:09:10+00')
        ) t(ts)
        """,
        ["ts", "listed", "held"],
        as_text=True,
    )


def _saved_standard(tmp_path: Path, **changes: object) -> Path:
    """Save a learned ``sq.scale.standard()``, with its learned part edited."""
    data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    path = tmp_path / "p.json"
    sq.save(sq.Pipeline([sq.scale.standard()]).learn(data), path)
    document = json.loads(path.read_text())
    for key, value in changes.items():
        if key == "values":
            document["learned"]["steps"][0]["values"] = value
        else:
            document["learned"][key] = value
    path.write_text(json.dumps(document))
    return path


def test_a_learned_value_naming_a_class_is_refused_and_imports_nothing(
    tmp_path: Path,
) -> None:
    """A learned value holds no class: refused as text, never told to import."""
    sys.modules.pop("sqlearn_test_imported", None)
    named = {
        "$": "object",
        "class": "tests.src.sqlearn._saving.recorded_import:X",
        "settings": {},
    }
    path = _saved_standard(tmp_path, values={"$": "dict", "items": [["center", named]]})
    with pytest.raises(
        SqlearnError, match=r"(?s)recorded_import.*damaged.*Fix:"
    ) as raised:
        sq.load(path)
    assert "Fix: import" not in str(raised.value)
    assert "sqlearn_test_imported" not in sys.modules


@pytest.mark.parametrize(
    ("changes", "says"),
    [
        ({"types": [{"zzz": "DOUBLE"}]}, "types"),
        (
            {
                "values": {
                    "$": "dict",
                    "items": [
                        ["scale", {"$": "dict", "items": [["a", 1.0]]}],
                        ["infinite", {"$": "dict", "items": [["a", 0.0]]}],
                    ],
                }
            },
            "'center'",
        ),
        ({"depends_on": [[5]]}, "step 6"),
        ({"columns_out": ["zzz"]}, "columns out"),
        ({"names": [{"zzz": ["zzz_1"]}]}, "zzz"),
    ],
    ids=["wrong types", "missing value", "late dependency", "columns out", "names"],
)
def test_a_damaged_learned_part_is_refused_at_load(
    tmp_path: Path, changes: dict[str, object], says: str
) -> None:
    """A learned part that does not match its steps is refused at load."""
    path = _saved_standard(tmp_path, **changes)
    with pytest.raises(SqlearnError, match=rf"(?s){re.escape(says)}.*Why:.*Fix:"):
        sq.load(path)


def test_a_restore_that_does_not_fit_changes_nothing() -> None:
    """A restore whose parts do not cover every step leaves every step as it was."""
    data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    learned = sq.Pipeline([sq.impute.median(), sq.scale.standard()]).learn(data)
    fresh = sq.Pipeline([sq.impute.median(), sq.scale.standard()])
    entries = learned._entries
    assert entries is not None
    with pytest.raises(SqlearnError, match=r"(?s)covers 1.*Why:.*Fix:"):
        fresh._restore(
            entries[:1],
            learned._types[:1],
            learned._names[:1],
            learned._columns_out,
            None,
            [[]],
            None,
        )
    assert fresh._entries is None
    with pytest.raises(AttributeError, match="after the step has learned"):
        _ = fresh[0].value_


# Settings that fill a numeric column with text: they cannot learn on any
# frame of _PUBLIC_DATA, whose "a" is numeric.
_TEXT_FILLS = {"impute value=const text", "impute value=dict"}
_PUBLIC_CASES = [
    (key, make)
    for key, make in [*recipe_cases._default_cases(), *recipe_cases.DOCUMENTED_CHOICES]
    if key not in _TEXT_FILLS
]


# A step that warns about what it learned warns at learn and again at load.
@pytest.mark.filterwarnings("ignore::sqlearn._errors.SqlearnWarning")
@pytest.mark.parametrize(
    "make", [m for _, m in _PUBLIC_CASES], ids=[k for k, _ in _PUBLIC_CASES]
)
def test_every_public_step_loads_learned_and_applies_the_same(
    tmp_path: Path, make: Any
) -> None:
    """Every public step's learned part passes the load's checks and applies."""
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.5, 4.0, 5.0, 6.0],
            "b": [2.0, 3.0, 4.0, 5.0, 7.0, 9.0],
            "z": [1.5, 2.5, 3.5, 0.5, 2.0, 1.0],
            "city": ["x", "y", "x", None, "y", "x"],
            "y": [1.0, 0.0, 1.0, 1.0, 0.0, 0.0],
        }
    )
    pipe = sq.Pipeline([("s", make()), ("after", sq.Step())]).learn(df, target="y")
    sq.save(pipe, tmp_path / "p.json")
    loaded = sq.load(tmp_path / "p.json")
    assert _rows(loaded.apply(df)) == _rows(pipe.apply(df))
