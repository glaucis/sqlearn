"""Steps and models as records, and the check of what a file may import.

A step is written as its class and its settings; a model as the ``sq.Model``
settings and its estimator, class and parameters. Nothing here imports a class
named in a file until `check_allowed` has passed every path.
"""

import importlib
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import Literal

from sqlearn._errors import SqlearnError
from sqlearn._model import Model
from sqlearn._saving.codec import decode, encode
from sqlearn._step import Step

__all__ = [
    "build_model",
    "build_step",
    "check_allowed",
    "class_path",
    "import_class",
    "model_record",
    "step_record",
]

_MODEL_SETTINGS = ("feed", "rows", "megabytes", "epochs", "shuffle", "seed")


def _refuse(where: str, what: str, why: str, fix: str) -> SqlearnError:
    return SqlearnError(f"{where}: {what}. Why: {why} Fix: {fix}")


def class_path(cls: type, where: str) -> str:
    """Return ``"module:qualname"`` for `cls`, a class a file can name.

    Parameters
    ----------
    cls : type
        The class of a step or model.
    where : str
        The place, for errors.

    Returns
    -------
    str
        The path ``module:qualname``.

    Raises
    ------
    SqlearnError
        When the class is defined in ``__main__`` or inside a function.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import class_path
    >>> class_path(sq.Model, "demo")
    'sqlearn._model:Model'
    """
    if cls.__module__ == "__main__" or "<locals>" in cls.__qualname__:
        raise _refuse(
            where,
            f"the class {cls.__qualname__} cannot be named in a file",
            "it is defined in __main__ or inside a function, so a later session "
            "cannot import it.",
            "define the step in an importable module, and import it from there.",
        )
    return f"{cls.__module__}:{cls.__qualname__}"


def check_allowed(paths: Iterable[str], allow: Collection[str]) -> None:
    """Refuse a file that names a package it may not import; import nothing.

    Parameters
    ----------
    paths : iterable of str
        Class paths (``"module:qualname"``) found in the file.
    allow : collection of str
        Top-level packages the caller trusts, besides ``sqlearn``.

    Raises
    ------
    SqlearnError
        Naming every package that is not allowed.

    Examples
    --------
    >>> from sqlearn._saving.recipe import check_allowed
    >>> check_allowed(["sqlearn.preprocessing.impute:Impute"], ())
    >>> check_allowed(["sklearn.svm:SVC"], ["sklearn"])
    """
    trusted = {"sqlearn", *allow}
    refused = sorted({path.partition(":")[0].split(".")[0] for path in paths} - trusted)
    if refused:
        names = ", ".join(repr(name) for name in refused)
        raise SqlearnError(
            f"the file names classes from {names}, which sq.load may not "
            "import. Why: importing a package runs its code, so a file can "
            "only name packages you allow. "
            f"Fix: pass allow={refused!r} if you trust the file."
        )


def import_class(
    path: str, kind: Literal["step", "model", "object"], where: str
) -> type:
    """Import the class a path names, and check it is of the kind wanted.

    Call `check_allowed` first: this imports the module.

    Parameters
    ----------
    path : str
        ``"module:qualname"``.
    kind : {"step", "model", "object"}
        A ``"step"`` must subclass `Step`; a ``"model"`` must have ``fit`` and
        ``predict``; an ``"object"`` is any class.
    where : str
        The place, for errors.

    Returns
    -------
    type
        The class.

    Raises
    ------
    SqlearnError
        When the module or class is missing, or the class is of another kind.

    Examples
    --------
    >>> from sqlearn._saving.recipe import import_class
    >>> import_class("sqlearn.preprocessing.impute:Impute", "step", "demo").__name__
    'Impute'
    """
    module, colon, qualname = path.partition(":")
    if not colon or not module or not qualname:
        raise _refuse(
            where,
            f"{path!r} is not a class path",
            "a class is written as module:qualname.",
            "save the pipeline again, or restore the file from where it came.",
        )
    try:
        found: object = importlib.import_module(module)
    except ImportError as error:
        raise _refuse(
            where,
            f"the module {module!r} cannot be imported ({error})",
            "the file names a class from a package this environment lacks.",
            f"install the package that provides {module!r}.",
        ) from error
    for part in qualname.split("."):
        try:
            found = getattr(found, part)
        except AttributeError as error:
            raise _refuse(
                where,
                f"{module!r} has no {qualname!r}",
                "the class was renamed, moved or removed since the file was saved, "
                "or the package is another version.",
                f"install the version of {module.split('.')[0]!r} the file was "
                "saved with.",
            ) from error
    if not isinstance(found, type):
        raise _refuse(
            where,
            f"{path!r} is not a class",
            "a file can only name classes.",
            "save the pipeline again, or restore the file from where it came.",
        )
    if kind == "step" and not issubclass(found, Step):
        raise _refuse(
            where,
            f"{path!r} is not a Step",
            "a pipeline step must subclass sq.Step.",
            "save the pipeline again, or restore the file from where it came.",
        )
    if kind == "model" and not (hasattr(found, "fit") and hasattr(found, "predict")):
        raise _refuse(
            where,
            f"{path!r} is not a model",
            "a model needs fit and predict.",
            "save the pipeline again, or restore the file from where it came.",
        )
    return found


def step_record(name: str, step: Step, position: int) -> dict[str, object]:
    """Return a step as a record: name, class, state version and settings.

    Parameters
    ----------
    name : str
        The step's name in the pipeline.
    step : Step
        The step.
    position : int
        Its position (from 1), for errors.

    Returns
    -------
    dict
        ``{"name", "class", "state_version", "settings"}``; every setting is
        written, the defaults too.

    Raises
    ------
    SqlearnError
        When the class or a setting cannot be written.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import step_record
    >>> step_record("t", sq.transform.log(), 1)["class"]
    'sqlearn.preprocessing.transform:Transform'
    """
    where = f"{name} (step {position})"
    cls = type(step)
    return {
        "name": name,
        "class": class_path(cls, where),
        "state_version": cls.state_version,
        "settings": {
            key: encode(value, f"{where}, setting {key!r}")
            for key, value in step.settings().items()
        },
    }


def _is_numpy_scalar(value: object) -> bool:
    return bool(
        type(value).__module__ == "numpy"
        and hasattr(value, "item")
        and getattr(value, "ndim", None) == 0
    )


def _estimator_record(estimator: object, where: str) -> dict[str, object]:
    get_params = getattr(estimator, "get_params")  # noqa: B009
    return {
        "$": "estimator",
        "class": class_path(type(estimator), where),
        "params": {
            name: _param(value, f"{where}, parameter {name!r}")
            for name, value in get_params(deep=False).items()
        },
    }


def _param(value: object, where: str) -> object:
    if _is_numpy_scalar(value):
        return encode(getattr(value, "item")(), where)  # noqa: B009
    if hasattr(value, "get_params") and not isinstance(value, type):
        return _estimator_record(value, where)
    if type(value) is list:
        return [_param(v, where) for v in value]
    if type(value) is tuple:
        return {"$": "tuple", "items": [_param(v, where) for v in value]}
    if type(value) is dict:
        return {
            "$": "dict",
            "items": [[_param(k, where), _param(v, where)] for k, v in value.items()],
        }
    try:
        return encode(value, where)
    except SqlearnError as error:
        raise _refuse(
            where,
            f"the value {type(value).__qualname__} cannot be saved ({error})",
            "a saved file holds data, never code or arrays.",
            "set it to a plain value, or save the model with its own library.",
        ) from error


def model_record(model: Model, position: int) -> dict[str, object]:
    """Return a model as a record: the ``sq.Model`` settings and its estimator.

    Parameters
    ----------
    model : Model
        The model step.
    position : int
        Its position (from 1), for errors.

    Returns
    -------
    dict
        ``{"name", "class", "settings", "estimator"}``; the estimator as
        ``{"$": "estimator", "class", "params"}``, nested estimators likewise.

    Raises
    ------
    SqlearnError
        When a parameter of the estimator has no encoding.

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import model_record
    >>> stub = SimpleNamespace(fit=print, predict=print, get_params=lambda deep: {})
    >>> model_record(sq.Model(stub), 1)["estimator"]
    {'$': 'estimator', 'class': 'types:SimpleNamespace', 'params': {}}
    """
    where = f"model (step {position})"
    return {
        "name": "model",
        "class": class_path(type(model), where),
        "settings": {
            key: encode(getattr(model, key), f"{where}, setting {key!r}")
            for key in _MODEL_SETTINGS
        },
        "estimator": _estimator_record(model.estimator, f"{where}, estimator"),
    }


def _field(record: Mapping[str, object], key: str, where: str) -> object:
    if key not in record:
        raise _refuse(
            where,
            f"the record has no {key!r}",
            "it is not a record sqlearn writes, so the file is damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    return record[key]


def _path(record: Mapping[str, object], where: str) -> str:
    path = _field(record, "class", where)
    if type(path) is not str:
        raise _refuse(
            where,
            f"the class is {path!r}, not text",
            "it is not a record sqlearn writes, so the file is damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    return path


def _settings(record: Mapping[str, object], where: str) -> dict[str, object]:
    settings = _field(record, "settings", where)
    if not isinstance(settings, dict):
        raise _refuse(
            where,
            "the settings are not an object",
            "it is not a record sqlearn writes, so the file is damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    return {str(key): value for key, value in settings.items()}


def _decoded_settings(
    record: Mapping[str, object], where: str, resolve: Callable[[str], type]
) -> dict[str, object]:
    return {
        key: decode(value, f"{where}, setting {key!r}", resolve)
        for key, value in _settings(record, where).items()
    }


def _construct(cls: type, where: str, **kwargs: object) -> object:
    try:
        return cls(**kwargs)
    except (SqlearnError, TypeError, ValueError) as error:
        raise SqlearnError(f"{where}: {error}") from error


def build_step(record: Mapping[str, object], where: str) -> Step:
    """Return the step a record describes.

    Parameters
    ----------
    record : mapping
        What `step_record` returned, after a trip through JSON.
    where : str
        The place, for errors.

    Returns
    -------
    Step
        The step, built by its class from the settings.

    Raises
    ------
    SqlearnError
        When the class cannot be imported or is not a step, or the settings
        are refused by it.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import build_step, step_record
    >>> build_step(step_record("t", sq.transform.log(), 1), "t")
    sq.transform.log()
    """
    cls = import_class(_path(record, where), "step", where)

    def resolve(path: str) -> type:
        return import_class(path, "object", where)

    settings = _decoded_settings(record, where, resolve)
    built = _construct(cls, where, **settings)
    assert isinstance(built, Step)
    return built


def build_model(record: Mapping[str, object], where: str) -> Model:
    """Return the model a record describes, estimator and all.

    Parameters
    ----------
    record : mapping
        What `model_record` returned, after a trip through JSON.
    where : str
        The place, for errors.

    Returns
    -------
    Model
        The ``sq.Model`` around a rebuilt estimator.

    Raises
    ------
    SqlearnError
        When a class cannot be imported, or the estimator or ``sq.Model``
        refuses its settings.

    Examples
    --------
    >>> from sqlearn._errors import SqlearnError
    >>> from sqlearn._saving.recipe import build_model
    >>> try:
    ...     build_model({"class": "sqlearn._model:Model"}, "demo")
    ... except SqlearnError as error:
    ...     print(str(error).split(".")[0])
    demo: the record has no 'estimator'
    """
    cls = import_class(_path(record, where), "object", where)
    if not issubclass(cls, Model):
        raise _refuse(
            where,
            f"{cls.__qualname__} is not sq.Model",
            "a model record holds an sq.Model.",
            "save the pipeline again, or restore the file from where it came.",
        )
    estimator_record = _field(record, "estimator", where)
    if not isinstance(estimator_record, dict):
        raise _refuse(
            where,
            "the estimator is not an object",
            "it is not a record sqlearn writes, so the file is damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    top = _path(estimator_record, where)

    def resolve(path: str) -> type:
        return import_class(path, "model" if path == top else "object", where)

    estimator = decode(estimator_record, where, resolve)
    settings = _decoded_settings(record, where, resolve)
    built = _construct(cls, where, estimator=estimator, **settings)
    assert isinstance(built, Model)
    return built
