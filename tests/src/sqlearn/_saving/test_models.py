"""The trained model, saved by pickle when asked and opened when trusted."""

import hashlib
import json
import os
import pickle
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

import sqlearn as sq
from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._store import STORE

from .recorded_pickle import Recorded


def _frame() -> pd.DataFrame:
    rows = range(60)
    return pd.DataFrame(
        {
            "age": [None if i % 11 == 0 else float(20 + i % 37) for i in rows],
            "income": [float((i * 7) % 13) for i in rows],
            "city": [("a", "b", "c")[i % 3] for i in rows],
            "y": [int((i * 7) % 13 > 5 or i % 3 == 0) for i in rows],
        }
    )


def _trained() -> sq.Pipeline:
    pipe = sq.Pipeline(
        [sq.impute.median(), sq.encode.onehot(), sq.Model(LogisticRegression())]
    )
    return pipe.train(_frame(), target="y")


def _predictions(pipe: sq.Pipeline, data: object):
    return pipe.predict(data, out="numpy")["prediction"].tolist()


def _cases() -> dict[str, tuple[sq.Pipeline, list[str]]]:
    def onehot(estimator: object) -> sq.Pipeline:
        return sq.Pipeline(
            [sq.impute.median(), sq.encode.onehot(), sq.Model(estimator)]
        )

    return {
        "logistic": (onehot(LogisticRegression()), ["sklearn"]),
        "lightgbm": (
            onehot(LGBMClassifier(n_estimators=10, verbose=-1)),
            ["lightgbm"],
        ),
        "catboost": (
            onehot(
                CatBoostClassifier(iterations=10, verbose=0, allow_writing_files=False)
            ),
            ["catboost"],
        ),
        "target": (
            sq.Pipeline(
                [
                    sq.impute.median(),
                    sq.encode.target("city"),
                    sq.scale.standard(),
                    sq.Model(LogisticRegression()),
                ]
            ),
            ["sklearn"],
        ),
    }


def test_a_trained_model_predicts_after_load_without_training(
    tmp_path: Path,
) -> None:
    """In a new process the model predicts as before, with nothing learned."""
    data = tmp_path / "customers.parquet"
    frame = _frame()
    duckdb.from_df(frame).write_parquet(str(data))
    want: dict[str, list[object]] = {}
    allow: dict[str, list[str]] = {}
    for name, (pipe, packages) in _cases().items():
        pipe.train(str(data), target="y")
        want[name] = _predictions(pipe, str(data))
        sq.save(pipe, tmp_path / f"{name}.sqlearn.json", model="pickle")
        allow[name] = packages
    script = textwrap.dedent(
        f"""
        import json

        import sqlearn as sq
        from sqlearn._store import STORE

        out = {{}}
        for name, packages in {allow!r}.items():
            STORE.learns.clear()
            pipe = sq.load(
                f"{{name}}.sqlearn.json", allow=packages, trust_model=True
            )
            got = pipe.predict("customers.parquet", out="numpy")
            out[name] = {{
                "predictions": got["prediction"].tolist(),
                "learns": dict(STORE.learns),
            }}
        print(json.dumps(out))
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    for name, predictions in want.items():
        assert got[name]["predictions"] == predictions, name
        assert got[name]["learns"] == {}, name


def test_a_model_not_trusted_loads_untrained_with_a_warning(tmp_path: Path) -> None:
    """Without trust_model=True the pickle stays shut and predict refuses."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    with pytest.warns(SqlearnWarning, match="trust_model=True") as caught:
        loaded = sq.load(path, allow=["sklearn"])
    message = str(caught[0].message)
    assert "churn.sqlearn.model.pickle was not opened" in message
    assert "Fix:" in message
    with pytest.raises(SqlearnError, match="not been trained"):
        loaded.predict(_frame())
    # Still learned: it trains without learning again.
    STORE.learns.clear()
    loaded.train(_frame(), target="y")
    assert dict(STORE.learns) == {}


def test_a_changed_model_file_is_refused_before_it_is_opened(tmp_path: Path) -> None:
    """A model file swapped after the save is never unpickled."""
    sys.modules.pop("sqlearn_test_unpickled", None)
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    model_file = tmp_path / "churn.sqlearn.model.pickle"
    model_file.write_bytes(pickle.dumps(Recorded(), protocol=5))
    with pytest.raises(SqlearnError, match="SHA-256") as raised:
        sq.load(path, allow=["sklearn"], trust_model=True)
    assert "Fix:" in str(raised.value)
    assert "sqlearn_test_unpickled" not in sys.modules


def test_a_model_file_changed_by_one_byte_is_refused(tmp_path: Path) -> None:
    """One byte flipped is enough for the hash to refuse the file."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    model_file = tmp_path / "churn.sqlearn.model.pickle"
    content = bytearray(model_file.read_bytes())
    content[len(content) // 2] ^= 1
    model_file.write_bytes(bytes(content))
    with pytest.raises(SqlearnError, match="SHA-256"):
        sq.load(path, allow=["sklearn"], trust_model=True)


def test_a_model_file_missing_is_refused(tmp_path: Path) -> None:
    """A trusted load needs the model file the JSON names."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    (tmp_path / "churn.sqlearn.model.pickle").unlink()
    with pytest.raises(SqlearnError, match=r"churn\.sqlearn\.model\.pickle") as raised:
        sq.load(path, allow=["sklearn"], trust_model=True)
    assert "Fix:" in str(raised.value)


def test_a_model_of_another_class_than_the_recipe_is_refused(tmp_path: Path) -> None:
    """The object unpickled must be of the class the recipe names."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    model_file = tmp_path / "churn.sqlearn.model.pickle"
    other = DecisionTreeClassifier().fit([[0.0], [1.0]], [0, 1])
    model_file.write_bytes(pickle.dumps(other, protocol=5))
    data = json.loads(path.read_text())
    data["model_file"]["sha256"] = hashlib.sha256(model_file.read_bytes()).hexdigest()
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match="DecisionTreeClassifier") as raised:
        sq.load(path, allow=["sklearn"], trust_model=True)
    assert "LogisticRegression" in str(raised.value)


def test_a_pipeline_not_trained_cannot_save_its_model(tmp_path: Path) -> None:
    """There is no trained model to save."""
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(LogisticRegression())])
    with pytest.raises(SqlearnError, match="not been trained") as raised:
        sq.save(pipe, tmp_path / "p.json", model="pickle")
    assert "Fix:" in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_an_unknown_model_format_is_refused(tmp_path: Path) -> None:
    """model= names a format sqlearn knows; the message lists them."""
    with pytest.raises(SqlearnError, match="known model format") as raised:
        sq.save(_trained(), tmp_path / "p.json", model="onnx")
    assert "'pickle'" in str(raised.value)
    assert "Fix:" in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_a_model_cannot_be_saved_without_the_learned_part(tmp_path: Path) -> None:
    """The model predicts only through the prepared data, so both are kept."""
    with pytest.raises(SqlearnError, match="learned=False") as raised:
        sq.save(_trained(), tmp_path / "p.json", model="pickle", learned=False)
    fix = str(raised.value).split("Fix:")[1]
    assert "learned=False" in fix
    assert "model=" in fix
    assert list(tmp_path.iterdir()) == []


def test_the_json_names_the_model_file_its_format_and_hash(tmp_path: Path) -> None:
    """The JSON stays data: the model is a file beside it, named last."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    data = json.loads(path.read_text())
    assert list(data)[-1] == "model_file"
    record = data["model_file"]
    assert record["format"] == "pickle"
    assert record["file"] == "churn.sqlearn.model.pickle"
    assert len(record["sha256"]) == 64
    assert record["feed"] == "numpy"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "churn.sqlearn.json",
        "churn.sqlearn.model.pickle",
    ]


def test_a_recipe_saved_without_model_has_no_model_file(tmp_path: Path) -> None:
    """By default the model is not saved, and the load does not warn."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path)
    assert "model_file" not in json.loads(path.read_text())
    assert [p.name for p in tmp_path.iterdir()] == ["churn.sqlearn.json"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sq.load(path, allow=["sklearn"])


def test_a_failed_save_keeps_the_old_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure between the two renames leaves the JSON and its model paired."""
    path = tmp_path / "churn.sqlearn.json"
    sq.save(_trained(), path, model="pickle")
    model_file = tmp_path / "churn.sqlearn.model.pickle"
    before = (path.read_bytes(), model_file.read_bytes())
    real = os.replace

    def fail_second(source, target):
        if Path(target) == path:
            raise OSError("disk full")
        real(source, target)

    monkeypatch.setattr(os, "replace", fail_second)
    pipe = sq.Pipeline(
        [sq.impute.median(), sq.encode.onehot(), sq.Model(LogisticRegression(C=0.1))]
    ).train(_frame(), target="y")
    with pytest.raises(OSError, match="disk full"):
        sq.save(pipe, path, model="pickle")
    monkeypatch.undo()
    assert (path.read_bytes(), model_file.read_bytes()) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "churn.sqlearn.json",
        "churn.sqlearn.model.pickle",
    ]
    loaded = sq.load(path, allow=["sklearn"], trust_model=True)
    assert _predictions(loaded, _frame()) == _predictions(_trained(), _frame())


def test_a_trusted_model_predicts_in_the_same_process(tmp_path: Path) -> None:
    """The loaded estimator, feed and categories are the trained ones."""
    pipe = _trained()
    path = tmp_path / "churn.sqlearn.json"
    sq.save(pipe, path, model="pickle")
    loaded = sq.load(path, allow=["sklearn"], trust_model=True)
    assert _predictions(loaded, _frame()) == _predictions(pipe, _frame())
