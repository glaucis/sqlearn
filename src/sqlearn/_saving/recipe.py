"""Steps and models as records, and the check of what a file may import.

A step is written as its class and its settings; a model as the ``sq.Model``
settings and its estimator, class and parameters. Nothing here imports a class
named in a file is looked up: `check_imported` refuses a class whose module
is not imported, and nothing is ever imported.
"""

import sys
import types
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from typing import Literal, cast

from sqlearn._errors import SqlearnError
from sqlearn._model import Model
from sqlearn._saving.codec import check_classes, class_paths, decode, encode, rebuilt
from sqlearn._step import Step

__all__ = [
    "build_model",
    "build_step",
    "check_imported",
    "check_model",
    "check_step",
    "class_path",
    "import_class",
    "model_record",
    "record_class_paths",
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


def check_imported(paths: Iterable[str]) -> None:
    """Refuse a file that names a class whose module is not imported.

    sq.load imports nothing: the user imports the packages a file names, so
    loading can never run code the user did not choose to run.

    Parameters
    ----------
    paths : iterable of str
        Class paths (``"module:qualname"``) found in the file.

    Raises
    ------
    SqlearnError
        Naming every class whose module is not in ``sys.modules``.

    Examples
    --------
    >>> from sqlearn._saving.recipe import check_imported
    >>> check_imported(["sqlearn.preprocessing.impute:Impute"])
    """
    missing = sorted(
        {path for path in paths if sys.modules.get(path.partition(":")[0]) is None}
    )
    if missing:
        named = ", ".join(repr(path) for path in missing)
        imports: list[str] = []
        for path in missing:
            module, _, qualname = path.partition(":")
            imports.append(
                f"import {qualname.split('.')[-1]} from {module.split('.')[0]} "
                "before loading"
            )
        raise SqlearnError(
            f"the file names {named}, which "
            f"{'is' if len(missing) == 1 else 'are'} not imported. "
            "Why: sq.load imports nothing, so loading a file can never run "
            "code you did not choose to run. "
            f"Fix: {'; '.join(imports)}."
        )


def _is_module(value: object) -> bool:
    """Say whether `value` is a module, reading its type and running no code."""
    return issubclass(type(value), types.ModuleType)


def _namespace_of(module: object) -> Mapping[str, object]:
    """Return a module's namespace without asking the module for it."""
    return cast(
        "Mapping[str, object]", vars(types.ModuleType)["__dict__"].__get__(module)
    )


def _mro_of(cls: type) -> tuple[type, ...]:
    """Return a class's MRO without going through its metaclass."""
    return cast("tuple[type, ...]", type.__dict__["__mro__"].__get__(cls))


_CLASS_DICT = vars(type)["__dict__"]


def _inherits(cls: type, base: type) -> bool:
    """Say whether `base` is in a class's MRO, comparing by identity.

    ``in`` would call the ``__eq__`` of a metaclass a file names.
    """
    return any(entry is base for entry in _mro_of(cls))


def _static_attr(value: object, name: str) -> object | None:
    """Return a class attribute of `value` (or of its type), running no code.

    Reads each class namespace straight from the class, so a metaclass hook,
    a ``__class__`` property or a ``__getattr__`` is never reached. Nothing is
    bound: a descriptor comes back as itself.
    """
    owner = value if issubclass(type(value), type) else type(value)
    for entry in _mro_of(cast("type", owner)):
        found = _CLASS_DICT.__get__(entry).get(name)
        if found is not None:
            return cast("object", found)
    return None


def _has(cls: type, name: str) -> bool:
    """Say whether a class defines `name`, running no metaclass hook."""
    return _static_attr(cls, name) is not None


def _not_a_pipeline_part(path: str, where: str) -> SqlearnError:
    return _refuse(
        where,
        f"{path!r} is not a step, a model or an estimator",
        "a saved pipeline holds only those.",
        "check where this file came from.",
    )


def import_class(
    path: str,
    kind: Literal["step", "model", "nested", "object"],
    where: str,
) -> type:
    """Find the class a path names among the modules already imported.

    Nothing is imported: call `check_imported` first. The class is checked
    against the kind wanted before any instance is made.

    Parameters
    ----------
    path : str
        ``"module:qualname"``.
    kind : {"step", "model", "nested", "object"}
        A ``"step"`` must subclass `Step`; a ``"model"`` must have ``fit`` and
        ``predict``; a ``"nested"`` estimator must have ``get_params``; an
        ``"object"`` is any class (the caller checks its closed list).
    where : str
        The place, for errors.

    Returns
    -------
    type
        The class.

    Raises
    ------
    SqlearnError
        When the module is not imported, the class is missing, or it is of
        another kind.

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
    imported = sys.modules.get(module)
    if imported is None:
        check_imported([path])
    if not _is_module(imported):
        raise _refuse(
            where,
            f"{module!r} is not a module",
            "something other than a module sits in its place in sys.modules.",
            "check where this file came from.",
        )
    # Nothing a file can name runs: no module or object __getattr__, no
    # __class__ property, no metaclass hook. Every test below reads the type
    # and the namespaces directly, so a lookup can never import.
    first, *rest = qualname.split(".")
    found: object = _namespace_of(imported).get(first)
    for part in rest:
        if found is not None and not _is_module(found):
            found = _static_attr(found, part)
    if found is None or _is_module(found):
        gone = found is None
        raise _refuse(
            where,
            f"{module!r} has no {qualname!r}"
            if gone
            else f"{path!r} walks through the module {first!r}",
            "the class was renamed, moved or removed since the file was saved, "
            "or the package is another version."
            if gone
            else "a class path names a class of its module, not one reached "
            "through another module.",
            f"install the version of {module.split('.')[0]!r} the file was saved with."
            if gone
            else "save the pipeline again, or restore the file from where it came.",
        )
    if not issubclass(type(found), type):
        raise _refuse(
            where,
            f"{path!r} is not a class",
            "a file can only name classes.",
            "save the pipeline again, or restore the file from where it came.",
        )
    cls = cast("type", found)
    if kind == "step" and not _inherits(cls, Step):
        raise _not_a_pipeline_part(path, where)
    if kind == "model" and not (_has(cls, "fit") and _has(cls, "predict")):
        raise _not_a_pipeline_part(path, where)
    if kind == "nested" and not _has(cls, "get_params"):
        raise _not_a_pipeline_part(path, where)
    return cls


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


def _construct(cls: type, where: str, file: str | None, **kwargs: object) -> object:
    """Build `cls` from a file's settings; its refusal names the file and step."""
    place = where if file is None else f"{where} in {file}"
    try:
        return cls(**kwargs)
    except SqlearnError as error:
        # The class's own refusal is in the house form already.
        raise SqlearnError(f"{place}: {error}") from error
    except (TypeError, ValueError) as error:
        raise _refuse(
            place,
            f"{cls.__qualname__} refuses the saved settings ({error})",
            "the file's settings are not ones this version of the class "
            "takes: it was saved with another version, or edited.",
            f"install the version of {cls.__module__.split('.')[0]!r} the file "
            "was saved with, or save the pipeline again with this one.",
        ) from error


def record_class_paths(record: Mapping[str, object]) -> set[str]:
    """Return every class a step or model record names, for `check_imported`.

    Parameters
    ----------
    record : mapping
        A step or model record, as read from the file.

    Returns
    -------
    set of str
        The record's own class, the estimator's class if any, and every class
        nested in the settings and parameters.

    Raises
    ------
    SqlearnError
        When a class in the record is not text.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import record_class_paths, step_record
    >>> sorted(record_class_paths(step_record("t", sq.transform.log(), 1)))
    ['sqlearn.preprocessing.transform:Transform']
    """
    return {_path(record, "the file")} | class_paths(dict(record))


def build_step(
    record: Mapping[str, object],
    where: str,
    file: str | None = None,
) -> Step:
    """Return the step a record describes.

    Parameters
    ----------
    record : mapping
        What `step_record` returned, after a trip through JSON.
    where : str
        The place, for errors.
    file : str, optional
        The saved file, named when a class refuses its settings.

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
    resolve = partial(_registered, where=where)
    settings = _decoded_settings(record, where, resolve)
    built = _construct(cls, where, file, **settings)
    assert isinstance(built, Step)
    return built


def _registered(path: str, where: str) -> type:
    """Return a class a step's settings may hold: one `rebuilt` lists.

    A step's settings hold no estimator, and an object's class is checked
    against the list before this is called.
    """
    found = rebuilt().get(path)
    if found is None:
        raise _refuse(
            where,
            f"a setting names the estimator {path!r}",
            "a step's settings hold values, never an estimator, so the file is "
            "damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    return found[0]


def _import_of(path: str, top: str, where: str) -> type:
    """Return a class a model record may name, found among the imported.

    sqlearn has no estimators. An estimator path into sqlearn is refused as
    text, before it is imported; a path into an imported package that lands on
    a class of sqlearn (one that package imports) is refused once found,
    before it is built. A fold scheme comes back only for an object tag: the
    codec refuses an estimator tag naming one.
    """
    found = rebuilt().get(path)
    if found is not None:
        return found[0]
    if path.partition(":")[0].split(".")[0] == "sqlearn":
        raise _sqlearn_estimator(path, where)
    kind: Literal["model", "nested"] = "model" if path == top else "nested"
    cls = import_class(path, kind, where)
    owner = _CLASS_DICT.__get__(cls).get("__module__", "")
    if str(owner).split(".")[0] == "sqlearn":
        raise _sqlearn_estimator(path, where)
    return cls


def _sqlearn_estimator(path: str, where: str) -> SqlearnError:
    """Refuse an estimator that is a class of sqlearn, however it is named."""
    return _refuse(
        where,
        f"the estimator {path!r} is a class of sqlearn",
        "sqlearn has no estimators, and building another of its classes could "
        "run what it does on creation, so the file is damaged or was edited.",
        "save the pipeline again, or restore the file from where it came.",
    )


def _model_parts(
    record: Mapping[str, object], where: str
) -> tuple[type, dict[str, object], str]:
    """Return a model record's class, estimator record and estimator's path."""
    path = _path(record, where)
    cls = import_class(path, "object", where)
    if not _inherits(cls, Model):
        raise _refuse(
            where,
            f"{path!r} is not sq.Model",
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
    typed: dict[str, object] = {str(k): v for k, v in estimator_record.items()}
    return cls, typed, _path(typed, where)


def check_step(record: Mapping[str, object], where: str) -> None:
    """Refuse a step record's classes, building nothing.

    Parameters
    ----------
    record : mapping
        A step record, as read from the file.
    where : str
        The place, for errors.

    Raises
    ------
    SqlearnError
        When its class is not an imported step, or a setting names a class a
        step may not hold.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._saving.recipe import check_step, step_record
    >>> check_step(step_record("t", sq.transform.log(), 1), "t")
    """
    import_class(_path(record, where), "step", where)
    check_classes(_settings(record, where), where, partial(_registered, where=where))


def check_model(record: Mapping[str, object], where: str) -> None:
    """Refuse a model record's classes, building nothing.

    Parameters
    ----------
    record : mapping
        A model record, as read from the file.
    where : str
        The place, for errors.

    Raises
    ------
    SqlearnError
        When the record's class is not an imported ``sq.Model``, or the
        estimator or one nested in it is not an imported estimator.

    Examples
    --------
    >>> from sqlearn._errors import SqlearnError
    >>> from sqlearn._saving.recipe import check_model
    >>> try:
    ...     check_model({"class": "sqlearn._model:Model"}, "demo")
    ... except SqlearnError as error:
    ...     print(str(error).split(".")[0])
    demo: the record has no 'estimator'
    """
    _, estimator_record, top = _model_parts(record, where)
    resolve = partial(_import_of, top=top, where=where)
    check_classes(estimator_record, where, resolve)
    check_classes(_settings(record, where), where, partial(_registered, where=where))


def build_model(
    record: Mapping[str, object],
    where: str,
    file: str | None = None,
) -> Model:
    """Return the model a record describes, estimator and all.

    Parameters
    ----------
    record : mapping
        What `model_record` returned, after a trip through JSON.
    where : str
        The place, for errors.
    file : str, optional
        The saved file, named when a class refuses its settings.

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
    cls, estimator_record, top = _model_parts(record, where)
    resolve = partial(_import_of, top=top, where=where)
    estimator = decode(estimator_record, where, resolve)
    # sq.Model's own settings are values: they hold no estimator.
    settings = _decoded_settings(record, where, partial(_registered, where=where))
    built = _construct(cls, where, file, estimator=estimator, **settings)
    assert isinstance(built, Model)
    return built
