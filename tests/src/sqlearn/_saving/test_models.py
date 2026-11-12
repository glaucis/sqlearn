"""The training record: the user saves the model, sq.save keeps how it was fed."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import duckdb
import joblib
import pandas as pd
import pytest
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import BaggingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

import sqlearn as sq
from sqlearn._errors import SqlearnError, SqlearnWarning


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


def _predictions(pipe: sq.Pipeline, data: object) -> list[Any]:
    return pipe.predict(data, out="numpy")["prediction"].tolist()


def _onehot(estimator: object, feed: str | None = None) -> sq.Pipeline:
    model = sq.Model(estimator) if feed is None else sq.Model(estimator, feed)
    return sq.Pipeline([sq.impute.median(), sq.encode.onehot(), model])


# name -> (pipeline, packages to import before loading, file suffix, saver, opener)
def _cases() -> dict[str, tuple[sq.Pipeline, list[str], str]]:
    return {
        "logistic": (
            _onehot(LogisticRegression()),
            ["sklearn.linear_model"],
            "joblib",
        ),
        "bagging": (
            _onehot(BaggingClassifier(estimator=DecisionTreeClassifier())),
            ["sklearn.ensemble", "sklearn.tree"],
            "joblib",
        ),
        "lightgbm": (
            _onehot(LGBMClassifier(n_estimators=10, verbose=-1)),
            ["lightgbm"],
            "joblib",
        ),
        "catboost": (
            _onehot(
                CatBoostClassifier(iterations=10, verbose=0, allow_writing_files=False)
            ),
            ["catboost"],
            "cbm",
        ),
        "catboost_pandas": (
            sq.Pipeline(
                [
                    sq.impute.median(),
                    sq.Model(
                        CatBoostClassifier(
                            iterations=10,
                            verbose=0,
                            allow_writing_files=False,
                            cat_features=["city"],
                        ),
                        feed="pandas",
                    ),
                ]
            ),
            ["catboost"],
            "cbm",
        ),
    }


@pytest.mark.parametrize("name", list(_cases()))
def test_a_users_model_predicts_after_load_without_training(
    tmp_path: Path, name: str
) -> None:
    """The user saves the model; a new process loads, puts it back, predicts."""
    pipe, packages, how = _cases()[name]
    data = tmp_path / "customers.parquet"
    duckdb.from_df(_frame()).write_parquet(str(data))
    pipe.train(str(data), target="y")
    want = _predictions(pipe, str(data))
    sq.save(pipe, tmp_path / "pipe.sqlearn.json")
    if how == "joblib":
        joblib.dump(pipe.model_, tmp_path / "model.joblib")
        opener = "joblib.load('model.joblib')"
    else:
        pipe.model_.save_model(str(tmp_path / "model.cbm"))
        opener = "catboost.CatBoostClassifier().load_model('model.cbm')"
    script = textwrap.dedent(
        f"""
        import importlib
        import json

        import joblib

        import sqlearn as sq
        from sqlearn._store import STORE

        for package in {packages!r}:
            importlib.import_module(package)
        import catboost
        pipe = sq.load("pipe.sqlearn.json")
        pipe.use_model({opener})
        got = pipe.predict("customers.parquet", out="numpy")
        print(json.dumps({{
            "predictions": got["prediction"].tolist(),
            "learns": dict(STORE.learns),
        }}))
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
    assert got["predictions"] == want
    assert got["learns"] == {}


def test_the_file_holds_the_training_record_and_no_model(tmp_path: Path) -> None:
    """The JSON has the feed and categories, and it is the only file."""
    pipe, _, _ = _cases()["catboost_pandas"]
    path = tmp_path / "churn.sqlearn.json"
    sq.save(pipe.train(_frame(), target="y"), path)
    data = json.loads(path.read_text())
    assert list(data)[-1] == "trained"
    assert list(data["trained"]) == ["feed", "categories"]
    assert data["trained"]["feed"] == "pandas"
    assert "model_file" not in data
    assert [p.name for p in tmp_path.iterdir()] == ["churn.sqlearn.json"]
    loaded = sq.load(path)
    assert loaded._feed == "pandas"
    assert loaded._categories == {"city": ["a", "b", "c"]}


def test_a_pipeline_not_trained_has_no_training_record(tmp_path: Path) -> None:
    """A pipeline of steps only, learned, writes no trained key."""
    path = tmp_path / "p.json"
    sq.save(sq.Pipeline([sq.impute.median()]).learn(_frame()), path)
    assert "trained" not in json.loads(path.read_text())


def test_a_loaded_pipeline_does_not_predict_until_its_model_is_back(
    tmp_path: Path,
) -> None:
    """Loaded, it is learned but untrained: predict names use_model."""
    path = tmp_path / "p.json"
    sq.save(_trained(), path)
    loaded = sq.load(path)
    with pytest.raises(SqlearnError, match="not been trained") as raised:
        loaded.predict(_frame())
    assert "use_model" in str(raised.value).split("Fix:")[1]
    with pytest.raises(SqlearnError, match="no trained model"):
        _ = loaded.model_


def test_a_loaded_pipeline_saved_again_keeps_its_training_record(
    tmp_path: Path,
) -> None:
    """Load, save a copy, load the copy: use_model needs no data."""
    original = _trained()
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    sq.save(original, first)
    sq.save(sq.load(first), second)
    assert (
        json.loads(first.read_text())["trained"]
        == json.loads(second.read_text())["trained"]
    )
    copy = sq.load(second)
    copy.use_model(original.model_)
    assert _predictions(copy, _frame()) == _predictions(original, _frame())


def _with(path: Path, change: Any) -> Path:
    sq.save(_trained(), path)
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    return path


def _no_learned(data: dict[str, Any]) -> None:
    del data["learned"]


def _no_model(data: dict[str, Any]) -> None:
    data["steps"][-1]["kind"] = "step"


@pytest.mark.parametrize(
    "change",
    [
        _no_learned,
        _no_model,
        lambda d: d["trained"].update(feed="tensor"),
        lambda d: d["trained"].update(feed=3),
        lambda d: d["trained"].update(categories={"$": "dict", "items": [["a", [1]]]}),
        lambda d: d["trained"].update(categories=["a"]),
        lambda d: d["trained"].pop("categories"),
        lambda d: d.update(trained=[]),
    ],
)
def test_a_damaged_trained_key_is_refused(tmp_path: Path, change: Any) -> None:
    """A training record that is not one sqlearn writes is refused as damaged."""
    path = _with(tmp_path / "p.json", change)
    with pytest.raises(SqlearnError, match=r"(?s)Why:.*damaged.*Fix:"):
        sq.load(path)


def test_a_changed_state_version_drops_the_training_record(tmp_path: Path) -> None:
    """A step that learns differently now drops the learned part and the record."""
    path = _with(
        tmp_path / "p.json",
        lambda d: d["steps"][0].update(
            state_version=d["steps"][0]["state_version"] + 1
        ),
    )
    with pytest.warns(SqlearnWarning, match="state version"):
        loaded = sq.load(path)
    assert loaded._feed is None
    with pytest.raises(SqlearnError, match="no training record"):
        loaded.use_model(_trained().model_)


def test_the_old_switches_are_gone(tmp_path: Path) -> None:
    """model=, allow= and trust_model= are not parameters any more."""
    path = tmp_path / "p.json"
    removed: dict[str, Any] = {"model": "pickle"}
    with pytest.raises(TypeError, match="model"):
        sq.save(_trained(), path, **removed)
    sq.save(_trained(), path)
    for name, value in (("allow", ["sklearn"]), ("trust_model", True)):
        with pytest.raises(TypeError, match=name):
            sq.load(path, **{name: value})


_WITH_DATA = textwrap.dedent(
    """
    import json

    import catboost
    import sqlearn as sq
    from sqlearn._store import STORE

    {build}
    pipe.use_model(
        catboost.CatBoostClassifier().load_model("model.cbm"),
        data="customers.parquet",
        target="y",
    )
    {after}
    got = pipe.predict("customers.parquet", out="numpy")
    print(json.dumps({{"predictions": got["prediction"].tolist()}}))
    """
)

_BUILD = """pipe = sq.Pipeline([
        sq.impute.median(),
        sq.Model(
            catboost.CatBoostClassifier(
                iterations=10, verbose=0, allow_writing_files=False,
                cat_features=["city"],
            ),
            feed="pandas",
        ),
    ])"""


def _in_new_process(tmp_path: Path, build: str, after: str) -> list[Any]:
    script = _WITH_DATA.format(build=build, after=after)
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])["predictions"]


def _catboost_files(tmp_path: Path) -> list[Any]:
    pipe, _, _ = _cases()["catboost_pandas"]
    duckdb.from_df(_frame()).write_parquet(str(tmp_path / "customers.parquet"))
    pipe.train(str(tmp_path / "customers.parquet"), target="y")
    pipe.model_.save_model(str(tmp_path / "model.cbm"))
    return _predictions(pipe, str(tmp_path / "customers.parquet"))


def test_a_users_model_predicts_with_the_data_and_no_file(tmp_path: Path) -> None:
    """Built in code, given the model and the data: predictions as trained."""
    want = _catboost_files(tmp_path)
    assert _in_new_process(tmp_path, _BUILD, "") == want


def test_a_pipeline_given_its_model_with_data_saves_and_loads(
    tmp_path: Path,
) -> None:
    """The training record made from the data is saved; load needs no data."""
    want = _catboost_files(tmp_path)
    after = "sq.save(pipe, 'p.sqlearn.json')\npipe = sq.load('p.sqlearn.json')\n"
    after += "pipe.use_model(catboost.CatBoostClassifier().load_model('model.cbm'))"
    assert _in_new_process(tmp_path, _BUILD, after) == want


_NEVER_IMPORTED = "tests.src.sqlearn._saving.recorded_import:X"


def _object_tag() -> dict[str, Any]:
    return {"$": "object", "class": _NEVER_IMPORTED, "settings": {}}


def _estimator_tag() -> dict[str, Any]:
    return {"$": "estimator", "class": _NEVER_IMPORTED, "params": {}}


def _in_learned(tag: dict[str, Any]) -> Any:
    return lambda d: d["learned"]["steps"][0]["values"]["items"].append(["x", tag])


def _in_categories(tag: dict[str, Any]) -> Any:
    return lambda d: d["trained"].update(categories=tag)


def _in_step_setting(tag: dict[str, Any]) -> Any:
    return lambda d: d["steps"][0]["settings"].update(suffix=tag)


def _in_model_setting(tag: dict[str, Any]) -> Any:
    return lambda d: d["steps"][-1]["settings"].update(seed=tag)


def _in_estimator_params(tag: dict[str, Any]) -> Any:
    return lambda d: d["steps"][-1]["estimator"]["params"].update(C=tag)


@pytest.mark.parametrize(
    "change",
    [
        _in_learned(_object_tag()),
        _in_learned(_estimator_tag()),
        _in_categories(_object_tag()),
        _in_categories(_estimator_tag()),
        _in_step_setting(_object_tag()),
        _in_step_setting(_estimator_tag()),
        _in_model_setting(_object_tag()),
        _in_model_setting(_estimator_tag()),
        _in_estimator_params(_object_tag()),
    ],
)
def test_a_class_where_none_is_allowed_never_tells_the_user_to_import_it(
    tmp_path: Path, change: Any
) -> None:
    """A place that can never hold a class is refused as damaged, not as unimported."""
    sys.modules.pop("sqlearn_test_imported", None)
    path = _with(tmp_path / "p.json", change)
    with pytest.raises(SqlearnError) as raised:
        sq.load(path)
    message = str(raised.value)
    assert "Fix:" in message
    assert "Fix: import" not in message
    assert "imports nothing" not in message
    assert "sqlearn_test_imported" not in sys.modules


def test_a_null_learned_part_beside_a_training_record_is_refused(
    tmp_path: Path,
) -> None:
    """`"learned": null` with `trained` is damaged, not silently dropped."""
    path = _with(tmp_path / "p.json", lambda d: d.update(learned=None))
    with pytest.raises(SqlearnError, match=r"(?s)Why:.*damaged.*Fix:"):
        sq.load(path)


@pytest.mark.parametrize(
    "estimator",
    [
        {"$": "object", "class": "sqlearn.model_selection.folds:KFold", "settings": {}},
        {"$": "aggregate", "name": "mean", "settings": {}},
        {"$": "tuple", "items": []},
    ],
)
def test_a_model_record_whose_estimator_is_not_an_estimator_is_refused(
    tmp_path: Path, estimator: dict[str, Any]
) -> None:
    """The estimator is refused as damaged before anything is built."""
    path = _with(
        tmp_path / "p.json", lambda d: d["steps"][-1].update(estimator=estimator)
    )
    with pytest.raises(SqlearnError, match=r"(?s)estimator is not an estimator.*Why:"):
        sq.load(path)
