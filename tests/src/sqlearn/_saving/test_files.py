"""``sq.save`` and ``sq.load`` for a recipe."""

import json
import os
import stat
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn._errors import SqlearnError, SqlearnWarning


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "age": [20.0, None, 40.0, 50.0],
            "income": [1.0, 2.0, None, 4.0],
            "city": ["a", "b", "a", None],
        }
    )


def _pipe() -> sq.Pipeline:
    return sq.Pipeline(
        [
            sq.impute.median(),
            sq.scale.standard(cols=sq.cols.numeric() - sq.cols("id")),
            sq.encode.onehot(),
        ]
    )


def _reprs(pipe: sq.Pipeline) -> list[str]:
    # Pipeline has no repr of its own: compare the steps'.
    return [repr(step) for _, step in pipe.steps]


def _write(path: Path, **changes: object) -> Path:
    sq.save(sq.Pipeline([sq.impute.median()]), path)
    data = json.loads(path.read_text())
    for key, value in changes.items():
        if value is KeyError:
            del data[key]
        else:
            data[key] = value
    path.write_text(json.dumps(data))
    return path


def test_a_recipe_loads_as_the_same_pipeline(tmp_path: Path) -> None:
    """A saved and loaded recipe has the same repr, names and output."""
    df, pipe = _frame(), _pipe()
    sq.save(pipe, tmp_path / "p.json")
    loaded = sq.load(tmp_path / "p.json")
    assert _reprs(loaded) == _reprs(pipe)
    assert [n for n, _ in loaded.steps] == [n for n, _ in pipe.steps]
    got, want = loaded.learn(df).apply(df), pipe.learn(df).apply(df)
    if not isinstance(want, pd.DataFrame):
        got, want = got.df(), want.df()
    pd.testing.assert_frame_equal(got, want)


def test_the_same_pipeline_gives_the_same_bytes(tmp_path: Path) -> None:
    """Saving twice gives equal bytes, starting with { and ending in a newline."""
    pipe = _pipe()
    sq.save(pipe, tmp_path / "a.json")
    sq.save(pipe, tmp_path / "b.json")
    first = (tmp_path / "a.json").read_bytes()
    assert first == (tmp_path / "b.json").read_bytes()
    assert first.startswith(b"{\n") and first.endswith(b"}\n")
    keys = list(json.loads(first))
    assert keys == ["format", "format_version", "sqlearn", "steps"]
    step = json.loads(first)["steps"][0]
    assert list(step)[:3] == ["name", "kind", "class"]


def test_a_model_needs_its_package_allowed(tmp_path: Path) -> None:
    """A model's package must be allowed to load, and the message says how."""
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(LogisticRegression())])
    sq.save(pipe, tmp_path / "m.json")
    with pytest.raises(SqlearnError) as raised:
        sq.load(tmp_path / "m.json")
    assert "sklearn" in str(raised.value) and "allow=" in str(raised.value)
    loaded = sq.load(tmp_path / "m.json", allow=["sklearn"])
    assert _reprs(loaded) == _reprs(pipe)
    assert isinstance(loaded.steps[-1][1], sq.Model)


def test_a_refused_save_leaves_the_old_file_as_it_was(tmp_path: Path) -> None:
    """A save that fails keeps the old file and leaves no temporary file."""
    path = tmp_path / "p.json"
    sq.save(_pipe(), path)
    before = path.read_bytes()
    bad = sq.Pipeline([sq.impute.median(), sq.Step(learn=lambda x: {})])
    with pytest.raises(SqlearnError):
        sq.save(bad, path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"format_version": 2}, ("upgrade", "Fix:")),
        ({"steps": KeyError}, ("steps", "Fix:")),
        ({"x": 1}, ("'x'", "Fix:")),
        ({"format": "other"}, ("format", "Fix:")),
    ],
)
def test_a_file_that_is_not_ours_is_refused(
    tmp_path: Path, changes: dict[str, object], words: tuple[str, ...]
) -> None:
    """A later version, a missing or extra key and another format are refused."""
    path = _write(tmp_path / "p.json", **changes)
    with pytest.raises(SqlearnError) as raised:
        sq.load(path)
    for word in words:
        assert word in str(raised.value)


def test_a_file_from_a_newer_sqlearn_warns(tmp_path: Path) -> None:
    """A newer sqlearn with a known format loads with a warning at the caller."""
    path = _write(tmp_path / "p.json", sqlearn="999.0.0")
    with pytest.warns(SqlearnWarning, match="999.0.0") as seen:
        sq.load(path)
    assert seen[0].filename == __file__


def test_an_older_file_does_not_warn(tmp_path: Path) -> None:
    """A file from the running version loads silently."""
    path = _write(tmp_path / "p.json")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sq.load(path)


def test_a_path_whose_folder_does_not_exist_is_refused(tmp_path: Path) -> None:
    """The folder must exist; the message says so."""
    with pytest.raises(SqlearnError, match="folder") as raised:
        sq.save(_pipe(), tmp_path / "nope" / "p.json")
    assert "Fix:" in str(raised.value)


def test_nothing_is_imported_before_every_class_is_allowed(tmp_path: Path) -> None:
    """A file naming a package not allowed is refused with no import at all."""
    sys.modules.pop("sqlearn_test_imported", None)
    path = _write(tmp_path / "p.json")
    data = json.loads(path.read_text())
    bad = dict(data["steps"][0], name="bad")
    bad["class"] = "tests.src.sqlearn._saving.recorded_import:X"
    data["steps"].append(bad)
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match=r"allow=") as raised:
        sq.load(path)
    assert "'tests'" in str(raised.value)
    assert "sqlearn_test_imported" not in sys.modules


def test_a_save_that_fails_while_writing_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the temporary file exists keeps the old file, no litter."""
    path = tmp_path / "p.json"
    sq.save(_pipe(), path)
    before = path.read_bytes()

    def fail(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        sq.save(sq.Pipeline([sq.impute.median()]), path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


def test_a_saved_file_has_the_mode_of_a_file_the_user_creates(
    tmp_path: Path,
) -> None:
    """The file gets 0o666 minus the umask, not the temporary file's 0o600."""
    old = os.umask(0o022)
    try:
        sq.save(_pipe(), tmp_path / "p.json")
        # Reading the umask must not have changed it.
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "p.json").stat().st_mode) == 0o644


def test_a_value_that_is_not_a_number_is_never_written_bare(
    tmp_path: Path,
) -> None:
    """NaN is written as tagged text, so the file is strict JSON."""
    path = tmp_path / "p.json"
    sq.save(sq.Pipeline([sq.impute.constant(float("nan"))]), path)
    json.loads(path.read_text(), parse_constant=_refuse_constant)


def _refuse_constant(name: str) -> None:
    raise AssertionError(f"bare {name} in the file")


_KEPT = "sqlearn.model_selection.kept:KeptFolds"


def _kept(tag: str, made: Path) -> dict[str, object]:
    body = "settings" if tag == "object" else "params"
    return {"$": tag, "class": _KEPT, body: {"path": str(made)}}


@pytest.mark.parametrize("tag", ["object", "estimator"])
def test_a_step_setting_naming_a_class_not_rebuilt_builds_nothing(
    tmp_path: Path, tag: str
) -> None:
    """A setting naming a sqlearn class outside the registry is refused."""
    made = tmp_path / "made.duckdb"
    path = _write(tmp_path / "p.json")
    data = json.loads(path.read_text())
    data["steps"][0]["settings"]["method"] = _kept(tag, made)
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match=r"(?s)KeptFolds.*Why:.*Fix:"):
        sq.load(path)
    assert not made.exists()


@pytest.mark.parametrize("part", ["values", "folds"])
def test_a_learned_value_naming_a_class_builds_nothing(
    tmp_path: Path, part: str
) -> None:
    """A learned value or fold naming any class is refused before building."""
    made = tmp_path / "made.duckdb"
    path = tmp_path / "p.json"
    sq.save(sq.Pipeline([sq.impute.median()]).learn(_frame()), path)
    data = json.loads(path.read_text())
    data["learned"]["steps"][0][part] = _kept("object", made)
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match=r"(?s)KeptFolds.*Why:.*Fix:"):
        sq.load(path)
    assert not made.exists()


def test_a_model_parameter_naming_a_sqlearn_class_builds_nothing(
    tmp_path: Path,
) -> None:
    """A nested estimator of sqlearn's own is refused before building."""
    made = tmp_path / "made.duckdb"
    path = tmp_path / "m.json"
    sq.save(sq.Pipeline([sq.Model(LogisticRegression())]), path)
    data = json.loads(path.read_text())
    data["steps"][-1]["estimator"]["params"]["C"] = _kept("estimator", made)
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match=r"(?s)KeptFolds.*Why:.*Fix:"):
        sq.load(path, allow=["sklearn"])
    assert not made.exists()


def test_the_models_categories_naming_a_class_build_nothing(
    tmp_path: Path,
) -> None:
    """The model file's categories name no class, even with trust_model."""
    made = tmp_path / "made.duckdb"
    path = tmp_path / "m.json"
    frame = _frame().assign(y=[0, 1, 0, 1])
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(LogisticRegression())])
    sq.save(pipe.train(frame.drop(columns="city"), target="y"), path, model="pickle")
    data = json.loads(path.read_text())
    data["model_file"]["categories"] = {
        "$": "dict",
        "items": [["city", _kept("object", made)]],
    }
    path.write_text(json.dumps(data))
    with pytest.raises(SqlearnError, match=r"(?s)KeptFolds.*Why:.*Fix:"):
        sq.load(path, allow=["sklearn"], trust_model=True)
    assert not made.exists()


def test_allow_given_as_text_is_refused_with_a_list_in_the_fix(
    tmp_path: Path,
) -> None:
    """allow="sklearn" is refused, not read as the letters s, k, l..."""
    path = tmp_path / "m.json"
    sq.save(sq.Pipeline([sq.Model(LogisticRegression())]), path)
    with pytest.raises(SqlearnError) as raised:
        sq.load(path, allow="sklearn")  # type: ignore[arg-type]
    text = str(raised.value)
    assert "Why:" in text and 'Fix: allow=["sklearn"]' in text


@pytest.mark.parametrize("where", ["parse", "settings", "learned"])
def test_a_file_nested_too_deeply_is_refused_as_damaged(
    tmp_path: Path, where: str
) -> None:
    """Deeply nested arrays are refused in the house form, wherever they are."""
    path = tmp_path / "p.json"
    sq.save(sq.Pipeline([sq.impute.median()]).learn(_frame()), path)
    deep = "[" * 5000 + "]" * 5000
    text = path.read_text()
    if where == "parse":
        # Deep enough that the JSON parser itself runs out of stack.
        deeper = "[" * 100_000 + "]" * 100_000
        text = text.replace('"steps": [', f'"steps": [{deeper}, ', 1)
    elif where == "settings":
        text = text.replace('"indicator": false', f'"indicator": {deep}', 1)
    else:
        text = text.replace('"columns_out": [', f'"columns_out": [{deep}, ', 1)
    path.write_text(text)
    with pytest.raises(SqlearnError, match=r"(?s)nested.*Why:.*Fix:"):
        sq.load(path)


@pytest.mark.parametrize("version", [0, -1, 1.0, True, "1"])
def test_a_format_version_that_is_not_a_positive_number_is_refused(
    tmp_path: Path, version: object
) -> None:
    """format_version 0, negative, a float, a bool or text is damaged."""
    path = _write(tmp_path / "p.json", format_version=version)
    with pytest.raises(SqlearnError, match=r"(?s)format_version.*Why:.*Fix:"):
        sq.load(path)
