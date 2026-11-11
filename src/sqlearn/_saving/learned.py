"""What a pipeline learned, as the ``learned`` part of a saved file.

Each step's store entry is saved (its columns, values and inner folds) with
what `apply` needs to rebuild every stage with the same SQL: the types the
steps learned from, the names of the columns they created and the columns
out. See ``docs/specs/library-saving.md``, sections 4 and 6.
"""

from collections.abc import Mapping
from functools import partial

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._errors import SqlearnError
from sqlearn._pipeline import Pipeline
from sqlearn._saving.codec import decode, encode
from sqlearn._saving.recipe import import_class
from sqlearn._store import Entry

__all__ = ["learned_record", "restore_learned"]


def learned_record(pipe: Pipeline) -> dict[str, object] | None:
    """Return what a pipeline learned as a JSON-ready record.

    Parameters
    ----------
    pipe : Pipeline
        A pipeline, learned or not.

    Returns
    -------
    dict or None
        ``{"data", "target", "columns_out", "types", "names", "depends_on",
        "steps"}``, each step's values and folds encoded; None when the
        pipeline has not learned.

    Raises
    ------
    SqlearnError
        When a learned value has no encoding.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._saving.learned import learned_record
    >>> data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    >>> pipe = sq.Pipeline([sq.scale.standard()])
    >>> learned_record(pipe) is None
    True
    >>> learned_record(pipe.learn(data))["steps"][0]["columns"]
    ['a']
    """
    if pipe._entries is None:
        return None
    steps, _ = pipe._split()
    records: list[dict[str, object]] = []
    for position, ((name, _), entry) in enumerate(
        zip(steps, pipe._entries, strict=True), start=1
    ):
        where = f"{name} (step {position}), learned"
        records.append(
            {
                "columns": list(entry.columns),
                "values": encode(entry.values, f"{where} values"),
                "folds": encode(entry.folds, f"{where} folds"),
            }
        )
    return {
        # Task 5 saves the data's fingerprint here.
        "data": {"kind": "unknown"},
        "target": pipe._target,
        "columns_out": list(pipe._columns_out),
        "types": [{c: str(t) for c, t in types.items()} for types in pipe._types],
        "names": [
            {c: list(created) for c, created in names.items()} for names in pipe._names
        ],
        "depends_on": [list(d) for d in pipe._depends_on or []],
        "steps": records,
    }


def _damaged(where: str, what: str) -> SqlearnError:
    return SqlearnError(
        f"{where}: {what}. Why: it is not a record sqlearn writes, so the file "
        "is damaged or was edited. Fix: save the pipeline again, or restore "
        "the file from where it came."
    )


def _texts(value: object, where: str, what: str) -> list[str]:
    if not isinstance(value, list) or any(type(v) is not str for v in value):
        raise _damaged(where, f"the {what} are not a list of text")
    return list(value)


def _per_step(value: object, count: int, where: str, what: str) -> list[object]:
    if not isinstance(value, list) or len(value) != count:
        raise _damaged(where, f"the {what} are not a list of one per step")
    return list(value)


def _texts_by_text(value: object, where: str, what: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(type(v) is not str for v in value.values()):
        raise _damaged(where, f"the {what} are not an object of text")
    return {str(k): v for k, v in value.items()}


def _types(value: object, where: str) -> dict[str, DuckDBPyType]:
    types: dict[str, DuckDBPyType] = {}
    for column, text in _texts_by_text(value, where, "types").items():
        try:
            types[column] = duckdb.sqltype(text)
        except duckdb.Error as error:
            raise _damaged(where, f"the type {text!r} is not a type") from error
    return types


def _names(value: object, where: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise _damaged(where, "the created names are not an object")
    return {
        str(column): _texts(created, where, "created names")
        for column, created in value.items()
    }


def _mapping(value: object, where: str, what: str) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict) or any(
        not isinstance(k, str) or not isinstance(v, dict) for k, v in value.items()
    ):
        raise _damaged(where, f"the {what} are not an object of objects")
    return {k: dict(v) for k, v in value.items()}


def _entry(record: object, where: str) -> Entry:
    if not isinstance(record, dict):
        raise _damaged(where, "the learned record is not an object")
    resolve = partial(import_class, kind="object", where=where, allow=())
    columns = _texts(record.get("columns"), where, "columns")
    values = decode(record.get("values"), f"{where}, learned values", resolve)
    folds = decode(record.get("folds"), f"{where}, learned folds", resolve)
    return Entry(
        _mapping(values, where, "learned values"),
        columns,
        "",
        {
            fold: _mapping(fold_values, where, "learned folds")
            for fold, fold_values in _mapping(folds, where, "learned folds").items()
        },
    )


def restore_learned(pipe: Pipeline, record: Mapping[str, object], where: str) -> None:
    """Give a loaded pipeline what it learned, as `learn` would.

    Each step gets its values and hears them (`Step.learned`) once, so its
    attributes ending in ``_`` read as before and `apply` works at once.

    Parameters
    ----------
    pipe : Pipeline
        The pipeline built from the same file's steps.
    record : mapping
        What `learned_record` returned, after a trip through JSON.
    where : str
        The place, for errors.

    Raises
    ------
    SqlearnError
        When the record is damaged.

    Examples
    --------
    >>> import json
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._saving.learned import learned_record, restore_learned
    >>> data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    >>> record = learned_record(sq.Pipeline([sq.scale.standard()]).learn(data))
    >>> pipe = sq.Pipeline([sq.scale.standard()])
    >>> restore_learned(pipe, json.loads(json.dumps(record)), "demo")
    >>> pipe.apply(data).fetchall()
    [(-1.0,), (1.0,)]
    """
    steps, _ = pipe._split()
    count = len(steps)
    names = [f"{name} (step {position})" for position, (name, _) in enumerate(steps, 1)]
    target = record.get("target")
    if target is not None and type(target) is not str:
        raise _damaged(where, "the target is not text")
    columns_out = _texts(record.get("columns_out"), where, "columns out")
    types = [
        _types(t, n)
        for t, n in zip(
            _per_step(record.get("types"), count, where, "types"), names, strict=True
        )
    ]
    created = [
        _names(c, n)
        for c, n in zip(
            _per_step(record.get("names"), count, where, "created names"),
            names,
            strict=True,
        )
    ]
    depends_on: list[list[int]] = []
    for d in _per_step(record.get("depends_on"), count, where, "dependencies"):
        if not isinstance(d, list) or any(type(i) is not int for i in d):
            raise _damaged(where, "the dependencies are not lists of numbers")
        depends_on.append(sorted(d))
    entries = [
        _entry(r, n)
        for r, n in zip(
            _per_step(record.get("steps"), count, where, "learned steps"),
            names,
            strict=True,
        )
    ]
    # Task 5 reads the data's fingerprint; until then the input is unknown.
    pipe._restore(entries, types, created, columns_out, target, depends_on, None)
