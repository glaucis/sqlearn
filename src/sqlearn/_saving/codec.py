"""Values to JSON and back: the tagged encodings of a saved pipeline.

A value is written as plain JSON when JSON says it exactly, and as a tagged
object (an object whose first key is ``"$"``) otherwise. Every object in the
file's values is tagged, a plain mapping included, so a user's key never
collides with a tag. A value with no encoding is refused, never written with
``str()``.
"""

import base64
import binascii
import inspect
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlearn._errors import SqlearnError
from sqlearn._selectors import Selector, _And, _Cols, _Kind, _Not, _Or, _Sub
from sqlearn.agg.aggregates import Aggregate, lookup

__all__ = ["class_paths", "decode", "encode", "no_class", "rebuilt"]

_FLOATS = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}


def rebuilt() -> Mapping[str, tuple[type, tuple[str, ...]]]:
    """Return the classes an ``"object"`` tag may name, with their settings.

    The list is closed: a class is rebuilt from a file's settings only when
    it is here, as building any other class could run what it does on
    creation (open a database, write a file). Today it holds the fold
    schemes of ``sq.folds``; aggregates and constant text have tags of their
    own.

    Returns
    -------
    mapping
        ``"module:qualname"`` to the class and the names of its settings.

    Examples
    --------
    >>> from sqlearn._saving.codec import rebuilt
    >>> rebuilt()["sqlearn.model_selection.folds:KFold"][1]
    ('n', 'seed')
    """
    from sqlearn.model_selection.folds import (
        Grouped,
        Holdout,
        KFold,
        Stratified,
        TimeSplit,
    )

    schemes: tuple[tuple[type, tuple[str, ...]], ...] = (
        (KFold, ("n", "seed")),
        (Stratified, ("n", "seed")),
        (Grouped, ("by", "n", "seed")),
        (Holdout, ("test", "seed")),
        (TimeSplit, ("by", "n", "gap")),
    )
    return {_class_path(cls): (cls, names) for cls, names in schemes}


def no_class(path: str) -> type:
    """Refuse every class: the resolver for parts that never name one.

    What a step learned and the model's categories come from DuckDB, which
    returns no sqlearn object, so a class named there is refused.

    Parameters
    ----------
    path : str
        The class path the file names.

    Returns
    -------
    type
        Never returns.

    Raises
    ------
    SqlearnError
        Always, naming the class.

    Examples
    --------
    >>> from sqlearn._errors import SqlearnError
    >>> from sqlearn._saving.codec import no_class
    >>> try:
    ...     no_class("a:B")
    ... except SqlearnError as error:
    ...     print(str(error).split(".")[0])
    the file names the class 'a:B' where it holds only values
    """
    raise SqlearnError(
        f"the file names the class {path!r} where it holds only values. "
        "Why: what a step learned and the model's categories are values "
        "DuckDB returned, never objects, so the file is damaged or was "
        "edited. Fix: save the pipeline again, or restore the file from "
        "where it came."
    )


def _refuse(where: str, what: str, why: str, fix: str) -> SqlearnError:
    return SqlearnError(f"{where}: {what}. Why: {why} Fix: {fix}")


def _class_path(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def encode(value: object, where: str) -> object:
    """Return `value` as a JSON-ready value.

    Parameters
    ----------
    value : object
        A setting or a learned value.
    where : str
        The place, for errors, such as ``"impute (step 1), setting 'cols'"``.

    Returns
    -------
    object
        Plain JSON values; every other kind as a tagged object.

    Raises
    ------
    SqlearnError
        When `value` has no encoding.

    Examples
    --------
    >>> from sqlearn._saving.codec import encode
    >>> encode((1, float("inf")), "demo")
    {'$': 'tuple', 'items': [1, {'$': 'float', 'value': 'inf'}]}
    """
    cls = type(value)
    if value is None or cls in (bool, int, str):
        return value
    if cls is float:
        assert isinstance(value, float)
        if math.isfinite(value):
            return value
        return {"$": "float", "value": "nan" if math.isnan(value) else repr(value)}
    if cls is list:
        assert isinstance(value, list)
        return [encode(v, where) for v in value]
    if cls is tuple:
        assert isinstance(value, tuple)
        return {"$": "tuple", "items": [encode(v, where) for v in value]}
    if cls is dict:
        assert isinstance(value, dict)
        items = [[encode(k, where), encode(v, where)] for k, v in value.items()]
        return {"$": "dict", "items": items}
    if cls is Decimal:
        return {"$": "decimal", "value": str(value)}
    if cls is datetime:
        assert isinstance(value, datetime)
        return {"$": "datetime", "value": value.isoformat()}
    if cls is date:
        assert isinstance(value, date)
        return {"$": "date", "value": value.isoformat()}
    if cls is time:
        assert isinstance(value, time)
        return {"$": "time", "value": value.isoformat()}
    if cls is timedelta:
        assert isinstance(value, timedelta)
        return {
            "$": "timedelta",
            "days": value.days,
            "seconds": value.seconds,
            "microseconds": value.microseconds,
        }
    if cls is UUID:
        return {"$": "uuid", "value": str(value)}
    if cls is bytes:
        assert isinstance(value, bytes)
        return {"$": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Selector):
        return _encode_selector(value, where)
    if isinstance(value, Aggregate):
        return _encode_aggregate(value, where)
    if _is_constant_text(value):
        return {"$": "constant_text", "value": str.__str__(value)}
    if _class_path(cls) in rebuilt():
        return _encode_object(value, where)
    kind = "function" if inspect.isroutine(value) else cls.__qualname__
    raise _refuse(
        where,
        f"a value of type {kind} cannot be saved",
        "a saved file holds data, never code, and this value has no JSON "
        "encoding: only plain values, selectors, the aggregates of sq.agg and "
        "the fold schemes of sq.folds have one.",
        "give a plain value (number, text, list, dict, date), or a step class in "
        "an importable module in place of a function.",
    )


def _is_constant_text(value: object) -> bool:
    from sqlearn.preprocessing.impute import _Text

    return type(value) is _Text


def _encode_aggregate(value: Aggregate, where: str) -> object:
    public = lookup(value.name)
    if public is None or public._build is not value._build:
        raise _refuse(
            where,
            f"the aggregate {value.name!r} cannot be saved",
            "only the aggregates of sq.agg can be rebuilt from a name, and this "
            "one was built by hand.",
            "use an aggregate from sq.agg, such as sq.agg.median.",
        )
    return {
        "$": "aggregate",
        "name": value.name,
        "settings": {
            name: encode(setting, f"{where}, sq.agg.{value.name} setting {name!r}")
            for name, setting in value.params.items()
        },
    }


def _encode_selector(value: Selector, where: str) -> object:
    if isinstance(value, _Cols):
        return {"$": "selector", "kind": "cols", "names": list(value.names)}
    if isinstance(value, _Kind):
        return {"$": "selector", "kind": value.label}
    if isinstance(value, _Or | _And | _Sub):
        kind = (
            "or"
            if isinstance(value, _Or)
            else "and"
            if isinstance(value, _And)
            else "sub"
        )
        return {
            "$": "selector",
            "kind": kind,
            "left": _encode_selector(value.left, where),
            "right": _encode_selector(value.right, where),
        }
    if isinstance(value, _Not):
        return {
            "$": "selector",
            "kind": "not",
            "operand": _encode_selector(value.inner, where),
        }
    raise _refuse(
        where,
        f"a selector of type {type(value).__qualname__} cannot be saved",
        "only the selectors of sq.cols have an encoding.",
        "build the selector from sq.cols(...), sq.cols.numeric() and | & - ~.",
    )


def _encode_object(value: object, where: str) -> object:
    cls = type(value)
    _, names = rebuilt()[_class_path(cls)]
    return {
        "$": "object",
        "class": _class_path(cls),
        "settings": {
            name: encode(
                getattr(value, name), f"{where}, {cls.__qualname__} setting {name!r}"
            )
            for name in names
        },
    }


def _bad(where: str, what: str) -> SqlearnError:
    return _refuse(
        where,
        f"the file holds {what}",
        "it is not a value sqlearn writes, so the file is damaged or was edited.",
        "save the pipeline again, or restore the file from where it came.",
    )


def decode(data: object, where: str, resolve: Callable[[str], type]) -> object:
    """Return the value that `data` was written from.

    Parameters
    ----------
    data : object
        What `encode` returned, after a trip through JSON.
    where : str
        The place, for errors.
    resolve : callable
        Imports a class path (``"module:qualname"``) and returns the class.

    Returns
    -------
    object
        The value, of the same type as the one written.

    Raises
    ------
    SqlearnError
        When a tag is of an unknown kind or a value is malformed.

    Examples
    --------
    >>> from sqlearn._saving.codec import decode
    >>> decode({"$": "tuple", "items": [1, 2]}, "demo", resolve=type)
    (1, 2)
    """
    if data is None or type(data) in (bool, int, float, str):
        return data
    if isinstance(data, list):
        return [decode(v, where, resolve) for v in data]
    if not isinstance(data, dict) or "$" not in data:
        raise _bad(where, f"an untagged value {data!r}")
    tag = data["$"]
    try:
        return _decode_tagged(tag, data, where, resolve)
    except SqlearnError:
        raise
    except (KeyError, TypeError, ValueError, InvalidOperation, binascii.Error) as error:
        raise _bad(where, f"a malformed {tag!r} value ({error})") from error


def _decode_tagged(
    tag: object, data: dict[str, object], where: str, resolve: Callable[[str], type]
) -> object:
    def sub(item: object) -> object:
        return decode(item, where, resolve)

    match tag:
        case "float":
            return _FLOATS[str(data["value"])]
        case "tuple":
            return tuple(sub(v) for v in _items(data["items"]))
        case "dict":
            pairs = _items(data["items"])
            result: dict[object, object] = {}
            for pair in pairs:
                key, val = _items(pair)
                result[sub(key)] = sub(val)
            return result
        case "decimal":
            return Decimal(str(data["value"]))
        case "date":
            return date.fromisoformat(str(data["value"]))
        case "datetime":
            return datetime.fromisoformat(str(data["value"]))
        case "time":
            return time.fromisoformat(str(data["value"]))
        case "timedelta":
            return timedelta(
                days=_int(data["days"]),
                seconds=_int(data["seconds"]),
                microseconds=_int(data["microseconds"]),
            )
        case "uuid":
            return UUID(str(data["value"]))
        case "bytes":
            return base64.b64decode(str(data["base64"]), validate=True)
        case "selector":
            return _decode_selector(data, where)
        case "constant_text":
            from sqlearn.preprocessing.impute import _Text

            return _Text(_text(data["value"]))
        case "aggregate":
            return _decode_aggregate(data, where, resolve)
        case "object":
            return _decode_object(data, where, resolve)
        case "estimator":
            path = _text(data["class"], "class")
            if path in rebuilt():
                raise _refuse(
                    where,
                    f"the file names {path!r} as an estimator",
                    "a fold scheme is saved as an object, never as an "
                    "estimator, so the file is damaged or was edited.",
                    "save the pipeline again, or restore the file from where it came.",
                )
            cls = resolve(path)
            params = data["params"]
            if not isinstance(params, dict):
                raise TypeError("params is not an object")
            return cls(**{name: sub(v) for name, v in params.items()})
    raise _bad(where, f"a tag of an unknown kind, {tag!r}")


def _decode_object(
    data: dict[str, object], where: str, resolve: Callable[[str], type]
) -> object:
    """Rebuild a registered class from its settings; refuse any other class.

    The class path is checked against `rebuilt` as text, before anything is
    imported; `resolve` then has its say (it refuses every class where a file
    holds only values).
    """
    path = _text(data["class"], "class")
    found = rebuilt().get(path)
    if found is None:
        raise _refuse(
            where,
            f"the file names the class {path!r}, which is not a step, a model or "
            "an estimator and which sq.load does not build from settings",
            "a file rebuilds only the fold schemes of sq.folds from settings, "
            "as building another class could run what it does on creation, "
            "so the file is damaged or was edited.",
            "save the pipeline again, or restore the file from where it came.",
        )
    cls, names = found
    if resolve(path) is not cls:
        raise _bad(where, f"the class {path!r} resolved to another class")
    settings = data["settings"]
    if not isinstance(settings, dict) or set(settings) != set(names):
        raise TypeError(f"the settings of {path!r} are not {list(names)}")
    return cls(**{name: decode(settings[name], where, resolve) for name in names})


def _text(value: object, what: str = "value") -> str:
    if type(value) is not str:
        raise TypeError(f"the {what} is not text")
    return value


def _decode_aggregate(
    data: dict[str, object], where: str, resolve: Callable[[str], type]
) -> Aggregate:
    name = _text(data["name"])
    found = lookup(name)
    if found is None:
        raise _bad(where, f"an aggregate of an unknown name, {name!r}")
    settings = data["settings"]
    if not isinstance(settings, dict):
        raise TypeError("settings is not an object")
    params = {k: decode(v, where, resolve) for k, v in settings.items()}
    rebuilt = found(None, **params)
    assert isinstance(rebuilt, Aggregate)
    return rebuilt


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected an array")
    return list[object](value)


def _int(value: object) -> int:
    if type(value) is not int:
        raise TypeError("expected an integer")
    return value


def _decode_selector(data: dict[str, object], where: str) -> Selector:
    kind = data["kind"]

    def part(name: str) -> Selector:
        found = data[name]
        if not isinstance(found, dict) or found.get("$") != "selector":
            raise TypeError(f"{name} is not a selector")
        return _decode_selector(found, where)

    match kind:
        case "cols":
            names = _items(data["names"])
            if not all(isinstance(n, str) for n in names):
                raise TypeError("names must be text")
            return _Cols(tuple(str(n) for n in names))
        case "numeric" | "string" as label:
            return _Kind(str(label))
        case "or":
            return _Or(part("left"), part("right"))
        case "and":
            return _And(part("left"), part("right"))
        case "sub":
            return _Sub(part("left"), part("right"))
        case "not":
            return _Not(part("operand"))
    raise _bad(where, f"a selector of an unknown kind, {kind!r}")


def class_paths(data: object) -> set[str]:
    """Return every class path inside tagged objects and estimators, nested.

    Parameters
    ----------
    data : object
        Encoded values, as read from the file.

    Returns
    -------
    set of str
        The ``"module:qualname"`` paths, for the ``check_imported`` check before any
        lookup.

    Raises
    ------
    SqlearnError
        When a tagged object or estimator names a class that is not text.

    Examples
    --------
    >>> from sqlearn._saving.codec import class_paths
    >>> class_paths([{"$": "object", "class": "a:B", "settings": {}}])
    {'a:B'}
    """
    found: set[str] = set()
    if isinstance(data, list):
        for item in data:
            found |= class_paths(item)
    elif isinstance(data, dict):
        if data.get("$") in ("object", "estimator"):
            path = data.get("class")
            if type(path) is not str:
                raise _bad("the file", f"a class that is not text, {path!r}")
            found.add(path)
        for item in data.values():
            found |= class_paths(item)
    return found
