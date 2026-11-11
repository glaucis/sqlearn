"""``sq.save`` and ``sq.load``: a pipeline's recipe as a JSON file.

The file is data, never code: a step is its class path and its settings. See
``docs/specs/library-saving.md``, section 4.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import warnings
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._model import FEEDS, Model
from sqlearn._pipeline import Pipeline
from sqlearn._saving.codec import class_paths, decode, encode, no_class
from sqlearn._saving.learned import learned_record, offer_saved, restore_learned
from sqlearn._saving.models import FORMATS, ModelFormat
from sqlearn._saving.recipe import (
    build_model,
    build_step,
    check_imported,
    model_record,
    record_class_paths,
    step_record,
)
from sqlearn._step import Step

__all__ = ["FORMAT", "FORMAT_VERSION", "load", "save"]

FORMAT = "sqlearn.pipeline"
FORMAT_VERSION = 1

# The keys of a file, in the order they are written: "learned" after "steps",
# and "model_file" last.
_REQUIRED = ("format", "format_version", "sqlearn", "steps")
_OPTIONAL = ("learned", "model_file")
_MODEL_KEYS = ("format", "file", "sha256", "feed", "categories")


def _refuse(what: str, why: str, fix: str) -> SqlearnError:
    return SqlearnError(f"{what}. Why: {why} Fix: {fix}")


def _version() -> str:
    import sqlearn

    return sqlearn.__version__


def _numbers(version: str) -> tuple[int, ...]:
    match = re.match(r"\d+(?:\.\d+)*", version)
    return tuple(int(part) for part in match.group().split(".")) if match else ()


def _records(pipe: Pipeline) -> list[dict[str, object]]:
    steps, model = pipe._split()
    records: list[dict[str, object]] = []
    for position, (name, step) in enumerate(steps, start=1):
        record = step_record(name, step, position)
        records.append(
            {"name": record.pop("name"), "kind": "step", **record},
        )
    if model is not None:
        record = model_record(model, len(steps) + 1)
        records.append(
            {
                "name": pipe.steps[-1][0],
                "kind": "model",
                **{k: v for k, v in record.items() if k != "name"},
            },
        )
    return records


def save(
    pipe: Pipeline,
    path: str | os.PathLike[str],
    *,
    learned: bool = True,
    model: str | None = None,
) -> None:
    """Save a pipeline's recipe to a JSON file.

    The file holds each step's class and settings, as data. The same pipeline
    always gives the same bytes. A failed save leaves any file already at
    `path` as it was.

    Parameters
    ----------
    pipe : Pipeline
        The pipeline to save.
    path : str or os.PathLike
        The file to write. Its folder must exist.
    learned : bool, default True
        Whether to keep what the pipeline learned, so the loaded pipeline
        applies without learning again. False saves the recipe only. A
        pipeline that has not learned is saved as its recipe either way.
    model : {"pickle"}, optional
        Also save the trained model, in this format, to a file beside `path`
        (``churn.sqlearn.json`` gives ``churn.sqlearn.model.pickle``); the
        JSON names that file and its SHA-256. Left out, the model is not
        saved and the loaded pipeline must be trained again. A pickle can run
        code when opened, so `load` opens it only with ``trust_model=True``.

    Raises
    ------
    SqlearnError
        When a setting or class cannot be written, the folder does not exist,
        `model` is not a known format, or `model` is given for a pipeline not
        trained or with ``learned=False``.

    See Also
    --------
    load : Read a saved pipeline.

    Examples
    --------
    >>> import os, tempfile
    >>> import sqlearn as sq
    >>> pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard()])
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     target = os.path.join(folder, "pipe.json")
    ...     sq.save(pipe, target)
    ...     repr(sq.load(target).steps[1][1]) == repr(pipe.steps[1][1])
    True
    """
    target = Path(path)
    form = _model_format(pipe, model, learned=learned)
    if not target.parent.is_dir():
        raise _refuse(
            f"the folder {str(target.parent)!r} does not exist",
            "sq.save writes one file and does not make folders.",
            "create the folder, or save to a folder that exists.",
        )
    document: dict[str, object] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "sqlearn": _version(),
        "steps": _records(pipe),
    }
    record = learned_record(pipe) if learned else None
    if record is not None:
        document["learned"] = record
    # Everything is encoded before the disk is touched; the model file's
    # record, all plain values, waits only for the file's hash.
    text = _text(document)
    categories = encode(pipe._categories, "the model's categories")
    temporaries: list[Path] = []
    try:
        if form is None:
            os.replace(_written(target, text, temporaries), target)
            return
        name, form_of = form
        model_path = target.with_suffix(form_of.suffix)
        written = _temporary(target.parent, model_path.name, temporaries)
        _, fitted = pipe._split()
        assert fitted is not None
        form_of.save(fitted.estimator, written)
        document["model_file"] = {
            "format": name,
            "file": model_path.name,
            "sha256": hashlib.sha256(written.read_bytes()).hexdigest(),
            "feed": pipe._feed,
            "categories": categories,
        }
        _publishable(written)
        _commit_pair(
            (written, model_path),
            (_written(target, _text(document), temporaries), target),
            temporaries,
        )
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


def _model_format(
    pipe: Pipeline, model: str | None, *, learned: bool
) -> tuple[str, ModelFormat] | None:
    """Return the format `model` names, refusing what cannot be saved."""
    if model is None:
        return None
    form = FORMATS.get(model)
    if form is None:
        known = ", ".join(repr(name) for name in FORMATS)
        raise _refuse(
            f"model={model!r} is not a known model format (known: {known})",
            "sqlearn writes a trained model only in a format it knows.",
            f"pass model= one of {known}, or leave it out to save the recipe.",
        )
    if not learned:
        raise _refuse(
            "model= cannot be saved with learned=False",
            "the model was trained on the prepared data and predicts only "
            "through it, so it needs what the steps learned.",
            "drop learned=False to keep both, or drop model= to share the "
            "recipe alone.",
        )
    _, fitted = pipe._split()
    if fitted is None or pipe._feed is None or pipe._entries is None:
        raise _refuse(
            "this pipeline has not been trained, so it has no model to save",
            "model= saves a trained model, and there is none yet.",
            "call train(data, target=...) first, or leave model= out.",
        )
    return model, form


def _text(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _temporary(folder: Path, name: str, temporaries: list[Path]) -> Path:
    """Make an empty temporary file in `folder`, kept for removal."""
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".tmp")
    os.close(handle)
    temporaries.append(Path(temporary))
    return Path(temporary)


def _publishable(temporary: Path) -> None:
    """Give a temporary file the mode a file the user creates would get."""
    # mkstemp makes the file 0600. The umask can only be read by setting it.
    umask = os.umask(0)
    try:
        os.chmod(temporary, 0o666 & ~umask)
    finally:
        os.umask(umask)


def _written(target: Path, text: str, temporaries: list[Path]) -> Path:
    """Write `text` to a temporary file beside `target`, ready to rename."""
    temporary = _temporary(target.parent, target.name, temporaries)
    with temporary.open("w", encoding="utf-8", newline="\n") as out:
        out.write(text)
    _publishable(temporary)
    return temporary


def _commit_pair(
    model: tuple[Path, Path], pipeline: tuple[Path, Path], temporaries: list[Path]
) -> None:
    """Rename the model file, then the JSON; on failure, keep the old pair.

    The JSON's hash must always describe the model file beside it: if the
    JSON cannot be renamed, the model file it would have replaced comes back.
    """
    written, model_path = model
    backup: Path | None = None
    if model_path.exists():
        backup = _temporary(model_path.parent, model_path.name, temporaries)
        try:
            backup.unlink()
            os.link(model_path, backup)
        except OSError:
            # A folder without hard links: a copy keeps the old file too.
            shutil.copyfile(model_path, backup)
    os.replace(written, model_path)
    try:
        os.replace(*pipeline)
    except BaseException:
        if backup is None:
            model_path.unlink(missing_ok=True)
        else:
            os.replace(backup, model_path)
        raise


def _damaged(what: str) -> SqlearnError:
    return _refuse(
        what,
        "it is not a file sqlearn writes, so it is damaged or was edited.",
        "save the pipeline again, or restore the file from where it came.",
    )


def _read(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise _refuse(
            f"{str(path)!r} cannot be read ({error})",
            "sq.load needs a file it can open.",
            "check the path.",
        ) from error
    except ValueError as error:
        raise _refuse(
            f"{str(path)!r} is not a sqlearn file (it is not JSON: {error})",
            "sq.save writes JSON.",
            "pass a file sq.save wrote.",
        ) from error
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise _refuse(
            f"{str(path)!r} is not a sqlearn pipeline file (its format is "
            f"{data.get('format') if isinstance(data, dict) else None!r}, not "
            f"{FORMAT!r})",
            "sq.load reads only files sq.save wrote.",
            "pass a file sq.save wrote.",
        )
    return {str(key): value for key, value in data.items()}


def _check_keys(data: Mapping[str, object]) -> None:
    version = data.get("format_version")
    if type(version) is not int or version < 1:
        raise _damaged(
            f"the file's format_version is {version!r}, not a positive whole number"
        )
    if version > FORMAT_VERSION:
        raise _refuse(
            f"the file is format version {version}, newer than this sqlearn "
            f"reads ({FORMAT_VERSION})",
            "a newer sqlearn wrote it, in a layout this one does not know.",
            "upgrade sqlearn to read it.",
        )
    missing = [key for key in _REQUIRED if key not in data]
    unknown = [key for key in data if key not in (*_REQUIRED, *_OPTIONAL)]
    if missing:
        raise _damaged(f"the file has no {missing[0]!r}")
    if unknown:
        raise _refuse(
            f"the file has an unknown field {unknown[0]!r}",
            "it comes from a version of sqlearn that knows something this one "
            "does not, or it was edited.",
            "upgrade sqlearn, or restore the file from where it came.",
        )


@contextmanager
def _nesting(path: str | os.PathLike[str]) -> Generator[None]:
    """Refuse a file nested past Python's stack as damaged, in the house form.

    A context manager, not a wrapper function, so the warnings raised inside
    keep their stack level.
    """
    try:
        yield
    except RecursionError as error:
        raise _damaged(
            f"{str(path)!r} holds values nested too deeply to read"
        ) from error


def _warn_if_newer(written: object) -> None:
    if not isinstance(written, str):
        raise _damaged(f"the file's sqlearn version is {written!r}, not text")
    if _numbers(written) > _numbers(_version()):
        warnings.warn(
            f"the file was written by sqlearn {written}, newer than this "
            f"sqlearn {_version()}. It loads because its format is known. "
            "Fix: upgrade sqlearn if anything looks wrong.",
            SqlearnWarning,
            stacklevel=3,
        )


def _step_records(data: Mapping[str, object]) -> list[Mapping[str, object]]:
    steps = data["steps"]
    if not isinstance(steps, list):
        raise _damaged("the file's steps are not a list")
    records: list[Mapping[str, object]] = []
    for position, record in enumerate(steps, start=1):
        if not isinstance(record, dict):
            raise _damaged(f"step {position} is not an object")
        kind = record.get("kind")
        if kind not in ("step", "model") or (
            kind == "model" and position != len(steps)
        ):
            raise _damaged(f"step {position} has the kind {kind!r}")
        if not isinstance(record.get("name"), str):
            raise _damaged(f"step {position} has no name")
        records.append(record)
    return records


def load(
    path: str | os.PathLike[str],
    *,
    trust_model: bool = False,
) -> Pipeline:
    """Load a pipeline saved with `save`.

    Nothing is imported: you import the packages the file names (``import
    sklearn`` for a scikit-learn model) before loading, so loading a file can
    never run code you did not choose to run. Only steps, models, nested
    estimators and fold schemes are built.

    Parameters
    ----------
    path : str or os.PathLike
        The file `save` wrote.
    trust_model : bool, default False
        Open the trained model file the JSON names, when there is one. Opening
        a pickle can run any code its author put in it, and imports whatever
        modules it names: pass True only for files you
        trust. The file is opened only if its SHA-256 matches the JSON's, which
        proves only that the two files match, and its model is kept only if
        it is of the class the recipe names, checked after it is opened. Left
        False, the pipeline loads learned but not trained.

    Returns
    -------
    Pipeline
        The pipeline, with the saved steps and settings, and what it learned
        when the file holds it: it then applies without learning again. With
        a trusted model file, it is trained too and predicts at once.

    Raises
    ------
    SqlearnError
        When the file is not a sqlearn file, is of a newer format, is missing
        or has unknown fields, nests values too deeply, names a class whose
        module is not imported, or names
        a class that is missing, of the wrong kind or not one a file may build;
        when a step's class refuses its settings; with ``trust_model=True``,
        when the model file is missing, its SHA-256 differs from the JSON's,
        or it holds another class than the recipe's.

    Warns
    -----
    SqlearnWarning
        When the file was written by a newer sqlearn with a known format, or
        a step's class changed what it learns since the file was saved (its
        ``state_version``): the pipeline then loads as a recipe. When the file
        names a model file and ``trust_model`` is False: the pipeline then
        loads learned, not trained.

    See Also
    --------
    save : Write a pipeline.

    Examples
    --------
    >>> import os, tempfile
    >>> import sqlearn as sq
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     target = os.path.join(folder, "pipe.json")
    ...     sq.save(sq.Pipeline([sq.impute.median()]), target)
    ...     sq.load(target).steps[0][0]
    'median'
    """
    with _nesting(path):
        data = _read(Path(path))
        _check_keys(data)
        _warn_if_newer(data["sqlearn"])
        records = _step_records(data)
        learned = data.get("learned")
        if learned is not None and not isinstance(learned, dict):
            raise _damaged("the file's learned part is not an object")
        model_file = _model_file(data, records)
        paths: set[str] = set()
        for record in records:
            paths |= record_class_paths(record)
        if learned is not None:
            # A learned value may name a class too: checked before any import.
            paths |= class_paths(learned)
        if model_file is not None:
            paths |= class_paths(dict(model_file))
        check_imported(paths)
        built: list[tuple[str, Step | Model]] = []
        file = repr(str(path))
        for position, record in enumerate(records, start=1):
            name = str(record["name"])
            where = f"{name} (step {position})"
            if record["kind"] == "model":
                built.append((name, build_model(record, where, file)))
            else:
                built.append((name, build_step(record, where, file)))
        pipe = Pipeline(built)
        if learned is not None and _same_state(records, built):
            restore_learned(pipe, learned, "the file's learned part")
            offer_saved(pipe, str(path))
            if model_file is not None:
                _open_model(pipe, model_file, Path(path), trust=trust_model)
    return pipe


def _model_file(
    data: Mapping[str, object], records: Sequence[Mapping[str, object]]
) -> Mapping[str, object] | None:
    """Return the file's model record, checked for shape; open nothing."""
    record = data.get("model_file")
    if record is None:
        return None
    if not isinstance(record, dict) or list(record) != list(_MODEL_KEYS):
        raise _damaged("the file's model_file is not a model file record")
    if "learned" not in data or not records or records[-1]["kind"] != "model":
        raise _damaged("the file names a model file but has no learned model")
    form, name, digest, feed = (record[key] for key in _MODEL_KEYS[:4])
    if form not in FORMATS:
        known = ", ".join(repr(known) for known in FORMATS)
        raise _refuse(
            f"the model file is in the format {form!r}, which this sqlearn "
            f"does not know (known: {known})",
            "a newer sqlearn wrote it, or the file was edited.",
            "upgrade sqlearn to read it.",
        )
    if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name:
        raise _damaged(f"the model file's name {name!r} is not a file beside it")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise _damaged(f"the model file's SHA-256 {digest!r} is not a hash")
    if feed not in FEEDS:
        raise _damaged(f"the model file's feed {feed!r} is not a form")
    return {str(key): value for key, value in record.items()}


def _open_model(
    pipe: Pipeline,
    record: Mapping[str, object],
    path: Path,
    *,
    trust: bool,
) -> None:
    """Open the model file `record` names, when trusted, and put it in place.

    The file's bytes are read once: the same bytes are hashed, then loaded.
    """
    name, form = str(record["file"]), FORMATS[str(record["format"])]
    if form.runs_code and not trust:
        warnings.warn(
            f"the trained model in {name} was not opened, as opening a "
            f"{record['format']} can run code. Fix: pass trust_model=True if "
            "you trust the file.",
            SqlearnWarning,
            stacklevel=3,
        )
        return
    categories = decode(record["categories"], "the model's categories", no_class)
    if not isinstance(categories, dict) or not all(
        isinstance(column, str)
        and isinstance(values, list)
        and all(isinstance(value, str) for value in values)
        for column, values in categories.items()
    ):
        raise _damaged("the model file's categories are not lists of text")
    try:
        content = (path.parent / name).read_bytes()
    except OSError as error:
        raise _refuse(
            f"the model file {name} cannot be read ({error})",
            f"{path.name} names it as the trained model, and it must sit beside it.",
            "put the model file beside the pipeline's file, or load without "
            "trust_model=True to train again.",
        ) from error
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise _refuse(
            f"the model file {name} is not the one saved with {path.name} "
            "(its SHA-256 differs), so it was not opened",
            "a file changed or swapped since the save could run any code.",
            "save the pipeline and its model again, or restore both files "
            "from where they came.",
        )
    _, model = pipe._split()
    assert model is not None
    estimator = form.load(content)
    expected = type(model.estimator)
    if not isinstance(estimator, expected):
        raise _refuse(
            f"the model file {name} holds a {type(estimator).__qualname__}, "
            f"not the {expected.__qualname__} its recipe names",
            "a model is put in place only as the class the recipe names.",
            "save the pipeline and its model again.",
        )
    model.estimator = estimator
    pipe._feed = str(record["feed"])
    pipe._categories = categories


def _same_state(
    records: Sequence[Mapping[str, object]],
    built: Sequence[tuple[str, Step | Model]],
) -> bool:
    """Say whether every step learns what it did when saved; warn if not."""
    changed: list[str] = []
    for position, (record, (name, step)) in enumerate(
        zip(records, built, strict=True), start=1
    ):
        if record["kind"] != "step" or not isinstance(step, Step):
            continue
        saved = record.get("state_version")
        if type(saved) is not int:
            raise _damaged(f"{name} (step {position}) has no state version")
        now = type(step).state_version
        if saved != now:
            changed.append(
                f"{name} (step {position}) was saved at state version {saved}, "
                f"its class is now at {now}"
            )
    if changed:
        warnings.warn(
            f"{'; '.join(changed)}. What it learned may no longer mean the "
            "same, so the pipeline loads as a recipe, unlearned. Fix: learn "
            "the pipeline again, and save it again.",
            SqlearnWarning,
            stacklevel=3,
        )
    return not changed
