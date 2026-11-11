"""``sq.save`` and ``sq.load``: a pipeline's recipe as a JSON file.

The file is data, never code: a step is its class path and its settings. See
``docs/specs/library-saving.md``, section 4.
"""

import json
import os
import re
import tempfile
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._model import Model
from sqlearn._pipeline import Pipeline
from sqlearn._saving.codec import class_paths
from sqlearn._saving.learned import learned_record, offer_saved, restore_learned
from sqlearn._saving.recipe import (
    build_model,
    build_step,
    check_allowed,
    model_record,
    record_class_paths,
    step_record,
)
from sqlearn._step import Step

__all__ = ["FORMAT", "FORMAT_VERSION", "load", "save"]

FORMAT = "sqlearn.pipeline"
FORMAT_VERSION = 1

# The keys of a file, in the order they are written: "learned" after "steps",
# and Task 6 adds "model_file" after it.
_REQUIRED = ("format", "format_version", "sqlearn", "steps")
_OPTIONAL = ("learned", "model_file")
_MODEL_FORMATS: tuple[str, ...] = ()


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
    model : str, optional
        How to save a trained model. No format is known yet, so any value is
        refused.

    Raises
    ------
    SqlearnError
        When a setting or class cannot be written, the folder does not exist,
        or `model` is not a known format.

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
    if model is not None:
        known = ", ".join(repr(f) for f in _MODEL_FORMATS) or "none yet"
        raise _refuse(
            f"model={model!r} is not a known model format (known: {known})",
            "sqlearn writes a trained model only in a format it knows.",
            "leave model= out to save the recipe.",
        )
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
    # Everything is encoded before the disk is touched.
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    handle, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
        # mkstemp makes the file 0600; a saved file gets the mode a file the
        # user creates would. The umask can only be read by setting it.
        umask = os.umask(0)
        try:
            os.chmod(temporary, 0o666 & ~umask)
        finally:
            os.umask(umask)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
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
    if type(version) is not int:
        raise _damaged(f"the file's format_version is {version!r}, not a number")
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
    allow: Sequence[str] = (),
    trust_model: bool = False,
) -> Pipeline:
    """Load a pipeline saved with `save`.

    Nothing the file names is imported until every class in it has been
    checked: only ``sqlearn`` classes load unless you allow other packages.

    Parameters
    ----------
    path : str or os.PathLike
        The file `save` wrote.
    allow : sequence of str, default ()
        Top-level packages, besides ``sqlearn``, whose classes the file may
        name (``["sklearn"]`` for a pipeline ending in a scikit-learn model).
        Allow only a package you trust: importing it runs its code.
    trust_model : bool, default False
        Reserved for a saved model file; it has no effect yet.

    Returns
    -------
    Pipeline
        The pipeline, with the saved steps and settings, and what it learned
        when the file holds it: it then applies without learning again.

    Raises
    ------
    SqlearnError
        When the file is not a sqlearn file, is of a newer format, is missing
        or has unknown fields, names a package that is not allowed, or names a
        class that is missing or of the wrong kind.

    Warns
    -----
    SqlearnWarning
        When the file was written by a newer sqlearn with a known format, or
        a step's class changed what it learns since the file was saved (its
        ``state_version``): the pipeline then loads as a recipe.

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
    del trust_model  # Task 6 opens a saved model file.
    data = _read(Path(path))
    _check_keys(data)
    _warn_if_newer(data["sqlearn"])
    records = _step_records(data)
    learned = data.get("learned")
    if learned is not None and not isinstance(learned, dict):
        raise _damaged("the file's learned part is not an object")
    paths: set[str] = set()
    for record in records:
        paths |= record_class_paths(record)
    if learned is not None:
        # A learned value may name a class too: checked before any import.
        paths |= class_paths(learned)
    check_allowed(paths, allow)
    built: list[tuple[str, Step | Model]] = []
    for position, record in enumerate(records, start=1):
        name = str(record["name"])
        where = f"{name} (step {position})"
        if record["kind"] == "model":
            built.append((name, build_model(record, where, allow)))
        else:
            built.append((name, build_step(record, where, allow)))
    pipe = Pipeline(built)
    if learned is not None and _same_state(records, built):
        restore_learned(pipe, learned, "the file's learned part", allow)
        offer_saved(pipe, str(path))
    return pipe


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
