"""``sq.save`` and ``sq.load`` for what a pipeline learned."""

import json
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
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


def _without(names: list[str], column: str) -> list[str]:
    return [n for n in names if n != column]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (
            lambda learned: learned.update(
                names=[{"b": ["b"]}], columns_out=_without(learned["columns_out"], "a")
            ),
            "'a'",
        ),
        (lambda learned: learned.update(names=[{"b": ["b"]}]), "'a'"),
        (lambda learned: learned["columns_out"].append("c"), "'c'"),
    ],
    ids=["kept column claimed dropped", "kept column unnamed", "dropped column out"],
)
def test_a_whole_row_step_damaged_at_load_is_refused(
    tmp_path: Path, change: Any, says: str
) -> None:
    """What a whole-row step gives is derived from its learned values at load.

    sq.select.best(k=2) keeps a and b: a file claiming otherwise is refused
    at load, not at apply, and nothing is restored.
    """
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 5.0, 6.0],
            "b": [1.0, 0.0, 2.0, 9.0],
            "c": [3.0, 1.0, 4.0, 1.0],
            "y": [0, 0, 1, 1],
        }
    )
    pipe = sq.Pipeline([sq.select.best(k=2)]).learn(df, target="y")
    assert pipe.columns_out_ == ["a", "b"]
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    record = json.loads(path.read_text())
    change(record["learned"])
    path.write_text(json.dumps(record))
    with pytest.raises(SqlearnError, match=rf"(?s){re.escape(says)}.*damaged.*Fix:"):
        sq.load(path)


def _selector_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, 5.0, 6.0],
            "b": [1.0, 0.0, 2.0, 9.0],
            "c": [3.0, 1.0, 4.0, 1.0],
            "y": [0, 0, 1, 1],
        }
    )


@pytest.mark.filterwarnings("ignore::sqlearn.errors.SqlearnWarning")
@pytest.mark.parametrize(
    "steps",
    [
        [sq.select.best(k=0, cols=["a", "b"])],
        [sq.select.percentile(percentile=0, cols=["a", "b"])],
        [sq.select.best(k=0, cols=["a", "b"]), sq.scale.standard()],
    ],
    ids=["best k=0", "percentile 0", "best k=0 mid-pipeline"],
)
def test_a_feature_selector_keeping_none_of_its_columns_loads(
    tmp_path: Path, steps: list[sq.Step]
) -> None:
    """A selector keeping none of its columns, with c passing beside them.

    At load its stage is rebuilt from its own columns only: that must not be
    refused as leaving no column, since c passes beside them when applied.
    """
    df = _selector_frame()
    pipe = sq.Pipeline(steps).learn(df, target="y")
    assert pipe.columns_out_ == ["c"]
    expected = pipe.apply(df, out="pandas")
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    STORE.clear()
    loaded = sq.load(path)
    assert loaded.columns_out_ == ["c"]
    pd.testing.assert_frame_equal(loaded.apply(df, out="pandas"), expected)
    assert not STORE.learns


def test_a_damaged_whole_row_step_gives_only_the_files_fix(tmp_path: Path) -> None:
    """The damage message carries one Fix line: the file's, not the step's."""
    pipe = sq.Pipeline([sq.select.best(k=2)]).learn(_selector_frame(), target="y")
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    record = json.loads(path.read_text())
    record["learned"]["names"] = [{"b": ["b"]}]
    path.write_text(json.dumps(record))
    with pytest.raises(SqlearnError, match="damaged") as caught:
        sq.load(path)
    assert str(caught.value).count("Fix:") == 1


@pytest.mark.parametrize("text", ["2.5", "1e100000000"], ids=["number", "huge"])
@pytest.mark.parametrize(
    ("score", "name", "index"),
    [
        ("f_classif", "stats", 2),
        ("f_classif", "stats", 3),
        ("f_classif", "stats", 4),
        ("chi2", "low", None),
        ("f_regression", "count", None),
        ("f_regression", "covariance", None),
        ("f_regression", "variance", None),
        ("f_regression", "target_variance", None),
    ],
    ids=[
        "stats count",
        "stats sum",
        "stats square sum",
        "low",
        "count",
        "covariance",
        "variance",
        "target variance",
    ],
)
def test_a_score_learned_as_text_is_refused_at_load(
    tmp_path: Path, score: str, name: str, index: int | None, text: str
) -> None:
    """A learned number given as text is damage, refused at once.

    The scores are taken exactly (`fractions.Fraction`), which reads text
    too: a few bytes ("1e100000000") would build a number of a hundred
    million digits, and loading would hang.
    """
    pipe = sq.Pipeline([sq.select.best(k=2, score=score)])
    pipe.learn(_selector_frame(), target="y")
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    record = json.loads(path.read_text())
    values = record["learned"]["steps"][0]["values"]["items"]
    per_column = next(v for n, v in values if n == name)["items"][0]
    if index is None:
        per_column[1] = text
    else:
        per_column[1][0]["items"][index] = text
    path.write_text(json.dumps(record))
    STORE.clear()
    with pytest.raises(SqlearnError, match="damaged"):
        sq.load(path)


@pytest.mark.parametrize("name", ["variance", "low", "high"])
def test_a_variance_learned_as_text_is_refused_at_load(
    tmp_path: Path, name: str
) -> None:
    """sq.select.variance's learned numbers given as text are damage.

    At threshold=0 it reads all three: the variance and the range.
    """
    pipe = sq.Pipeline([sq.select.variance()]).learn(_selector_frame())
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    record = json.loads(path.read_text())
    values = record["learned"]["steps"][0]["values"]["items"]
    next(v for n, v in values if n == name)["items"][0][1] = "2.5"
    path.write_text(json.dumps(record))
    STORE.clear()
    with pytest.raises(SqlearnError, match="damaged"):
        sq.load(path)


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


# Each damage as the JSON text written in place of a learned value: the
# huge text and number are 12 bytes, a hundred million digits if read
# exactly; the big int is too large for a float.
_DAMAGE = {
    "text": '"0.5"',
    "nested list": "[0.5]",
    "huge text": '"1e100000000"',
    "huge number": "1e100000000",
    "bool": "true",
    "big int": "1" + "0" * 400,
}


@pytest.mark.parametrize("damage", list(_DAMAGE))
@pytest.mark.parametrize(
    "slot",
    ["mean", "count", "missing", "infinite", "weights", "weight", "variance"],
)
@pytest.mark.parametrize(
    "settings", [{}, {"n_components": 0.9, "whiten": True}], ids=["all", "share"]
)
def test_a_pca_value_damaged_at_load_is_refused(
    tmp_path: Path, settings: dict[str, Any], slot: str, damage: str
) -> None:
    """Each value PCA learned, in SQL or from XᵀX, is checked at load.

    ``weight`` is one entry of a column's ``weights`` list; ``weights`` is
    the whole list. Every damage is refused with the damaged-file message
    (HANDOFF: probe every learned slot end to end).
    """
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(size=(20, 3)), columns=["a", "b", "c"])
    pipe = sq.Pipeline([sq.decompose.pca(**settings)]).learn(df)
    path = tmp_path / "p.json"
    sq.save(pipe, path)
    record = json.loads(path.read_text())
    values = record["learned"]["steps"][0]["values"]["items"]
    name = "weights" if slot == "weight" else slot
    per_column = next(v for n, v in values if n == name)["items"][1]
    if slot == "weight":
        per_column[1][0] = "__damage__"
    else:
        per_column[1] = "__damage__"
    path.write_text(json.dumps(record).replace('"__damage__"', _DAMAGE[damage]))
    STORE.clear()
    with pytest.raises(SqlearnError, match=r"(?s)damaged.*Fix:"):
        sq.load(path)
