"""What a pipeline learned, as the ``learned`` part of a saved file.

Each step's store entry is saved (its columns, values and inner folds) with
what `apply` needs to rebuild every stage with the same SQL: the types the
steps learned from, the names of the columns they created and the columns
out. See ``docs/specs/library-saving.md``, sections 4 and 6.
"""

import os
import warnings
from collections.abc import Mapping

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._errors import PACKAGE_FILES, SqlearnError, SqlearnWarning
from sqlearn._inputs import DataKey
from sqlearn._pipeline import LearnedFrom, Pipeline
from sqlearn._saving.codec import decode, encode, no_class
from sqlearn._step import Step
from sqlearn._store import STORE, Entry, step_key

__all__ = ["learned_record", "offer_saved", "restore_learned"]

_UNKNOWN: dict[str, object] = {"kind": "unknown"}


def _pairs(columns: tuple[tuple[str, str], ...]) -> list[list[str]]:
    return [[name, dtype] for name, dtype in columns]


def _data_record(source: LearnedFrom | None) -> dict[str, object]:
    """Return the data a pipeline learned from as a record (spec section 6).

    Only data whose key means the same in another process is saved: a file
    or glob, a table of a database file, a pandas frame. A table with
    writes not yet checkpointed is saved as unknown, with a warning: the
    checkpoint DuckDB runs on close would give it another fingerprint.
    """
    if source is None:
        return dict(_UNKNOWN)
    origin, stable, columns = source
    if stable is None:
        return dict(_UNKNOWN)
    if stable[0] == "file" and origin is not None:
        return {
            "kind": "file",
            "pattern": os.path.join(origin[1], origin[2]),
            "files": [list(f) for f in stable[1]],
            "columns": _pairs(columns),
        }
    if stable[0] == "table":
        _, file, table, rows, table_columns, storage = stable
        if storage[1] or storage[2]:
            warnings.warn(
                f"the table {table} in {os.path.basename(file)} has writes "
                "not yet checkpointed, so the learned values are saved "
                "without its fingerprint and a new process learns them "
                "again. Why: DuckDB writes them at the next checkpoint (at "
                "the latest when the database closes), which changes the "
                "table's storage though its data does not. Fix: run "
                "CHECKPOINT before learning and saving, so the learned "
                "values carry across processes.",
                SqlearnWarning,
                skip_file_prefixes=PACKAGE_FILES,
            )
            return dict(_UNKNOWN)
        return {
            "kind": "table",
            "file": file,
            "table": table,
            "rows": rows,
            "columns": _pairs(table_columns),
            "storage": [list(storage[0]), list(storage[1]), storage[2]],
        }
    if stable[0] == "frame":
        _, rows, digest, frame_columns = stable
        return {
            "kind": "frame",
            "rows": rows,
            "digest": digest,
            "columns": _pairs(frame_columns),
        }
    return dict(_UNKNOWN)


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
        "data": _data_record(pipe._source),
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


def _numbers(value: object, where: str, what: str) -> list[int]:
    if not isinstance(value, list) or any(type(v) is not int for v in value):
        raise _damaged(where, f"the {what} are not a list of numbers")
    return list(value)


def _number(value: object, where: str, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _damaged(where, f"the {what} is not a number")
    return value


def _text(value: object, where: str, what: str) -> str:
    if type(value) is not str:
        raise _damaged(where, f"the {what} is not text")
    return value


def _column_pairs(value: object, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or any(
        not isinstance(p, list) or len(p) != 2 or any(type(v) is not str for v in p)
        for p in value
    ):
        raise _damaged(where, "the data's columns are not pairs of text")
    return tuple((str(p[0]), str(p[1])) for p in value)


def _learned_from(value: object, where: str) -> LearnedFrom | None:
    """Rebuild the data's origin and stable key exactly as `read` builds them.

    None for data of kind ``unknown``.
    """
    if not isinstance(value, dict):
        raise _damaged(where, "the data is not an object")
    kind = value.get("kind")
    where = f"{where}, data"
    if kind == "unknown":
        return None
    if kind == "file":
        pattern = _text(value.get("pattern"), where, "pattern")
        files = value.get("files")
        if not isinstance(files, list) or any(
            not isinstance(f, list)
            or len(f) != 3
            or type(f[0]) is not str
            or any(type(n) is not int for n in f[1:])
            for f in files
        ):
            raise _damaged(where, "the files are not [path, size, time] lists")
        stable: DataKey = ("file", tuple((p, n, t) for p, n, t in files))
        origin = ("file", os.path.dirname(pattern), os.path.basename(pattern))
        return origin, stable, _column_pairs(value.get("columns"), where)
    if kind == "table":
        file = _text(value.get("file"), where, "file")
        table = _text(value.get("table"), where, "table")
        columns = _column_pairs(value.get("columns"), where)
        storage = value.get("storage")
        if not isinstance(storage, list) or len(storage) != 3:
            raise _damaged(where, "the storage is not [blocks, row groups, count]")
        stable = (
            "table",
            file,
            table,
            _number(value.get("rows"), where, "row count"),
            columns,
            (
                tuple(_numbers(storage[0], where, "storage blocks")),
                tuple(_numbers(storage[1], where, "edited row groups")),
                _number(storage[2], where, "count of unwritten segments"),
            ),
        )
        return ("table", file, table), stable, columns
    if kind == "frame":
        columns = _column_pairs(value.get("columns"), where)
        stable = (
            "frame",
            _number(value.get("rows"), where, "row count"),
            _number(value.get("digest"), where, "digest"),
            columns,
        )
        return None, stable, columns
    raise _damaged(where, f"the kind {kind!r} is not known")


def _entry(record: object, where: str) -> Entry:
    if not isinstance(record, dict):
        raise _damaged(where, "the learned record is not an object")
    # DuckDB returns no objects: a class named here is refused, not built.
    columns = _texts(record.get("columns"), where, "columns")
    values = decode(record.get("values"), f"{where}, learned values", no_class)
    folds = decode(record.get("folds"), f"{where}, learned folds", no_class)
    return Entry(
        _mapping(values, where, "learned values"),
        columns,
        "",
        {
            fold: _mapping(fold_values, where, "learned folds")
            for fold, fold_values in _mapping(folds, where, "learned folds").items()
        },
    )


def _learns(step: Step) -> list[str] | None:
    """Return the names a step's `learn` gives, or None when it cannot say.

    `learn` is called on a placeholder column, as the planner does; a step
    whose names depend on the column or that cannot learn without data is
    not checked.
    """
    try:
        return list(step.learn(duckdb.ColumnExpression("x")))
    except Exception:  # noqa: BLE001  (a step that cannot say is not checked)
        return None


def _check_values(
    values: Mapping[str, Mapping[str, object]],
    columns: list[str],
    learns: list[str],
    where: str,
) -> None:
    for name in learns:
        have = values.get(name, {})
        for column in columns:
            if column not in have:
                raise _damaged(
                    where,
                    f"the learned value {name!r} has nothing for column {column!r}",
                )


def _check_step(
    step: Step,
    position: int,
    entry: Entry,
    types: dict[str, DuckDBPyType],
    created: dict[str, list[str]],
    depends_on: list[int],
    where: str,
) -> None:
    """Refuse a step's learned part that does not match what it learns."""
    columns = set(entry.columns)
    if set(types) != columns:
        raise _damaged(
            where, f"the types name {sorted(types)}, not its columns {entry.columns}"
        )
    stray = sorted(set(created) - columns)
    if stray:
        raise _damaged(where, f"names columns {stray} it did not learn from")
    late = [i for i in depends_on if not 0 <= i < position - 1]
    if late:
        raise _damaged(
            where, f"depends on step {late[0] + 1}, which is not a step before it"
        )
    learns = _learns(step)
    if learns is not None:
        _check_values(entry.values, entry.columns, learns, where)
        for fold_values in entry.folds.values():
            _check_values(fold_values, entry.columns, learns, where)


def _check_columns_out(
    columns_out: list[str],
    step: Step,
    entry: Entry,
    created: dict[str, list[str]],
    where: str,
) -> None:
    """Refuse columns out that the last step cannot have given.

    A column the step learned from and created nothing from passed through
    under its own name, except for a whole-row step without ``keep``: its
    created names are every column it gives, so it gave nothing from that
    column (a feature selector drops it).
    """
    if len(set(columns_out)) != len(columns_out):
        raise _damaged(where, "the columns out name a column twice")
    out = set(columns_out)
    dropped = step.rowwise and not step.keep
    for column in entry.columns:
        made = created.get(column, [] if dropped else [column])
        missing = [c for c in made if c not in out]
        if missing:
            raise _damaged(
                where,
                f"the columns out lack {missing[0]!r}, which the last step gives",
            )


def restore_learned(
    pipe: Pipeline,
    record: Mapping[str, object],
    where: str,
) -> None:
    """Give a loaded pipeline what it learned, as `learn` would.

    Each step gets its values and hears them (`Step.learned`) once, so its
    attributes ending in ``_`` read as before and `apply` works at once.
    Every part is checked first: a damaged record changes nothing.

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
        When the record is damaged, names a class (a learned value never
        does), or does not match the pipeline's steps.

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
    places = [
        f"{where}, {name} (step {position})"
        for position, (name, _) in enumerate(steps, 1)
    ]
    target = record.get("target")
    if target is not None and type(target) is not str:
        raise _damaged(where, "the target is not text")
    columns_out = _texts(record.get("columns_out"), where, "columns out")
    types = [
        _types(t, n)
        for t, n in zip(
            _per_step(record.get("types"), count, where, "types"), places, strict=True
        )
    ]
    created = [
        _names(c, n)
        for c, n in zip(
            _per_step(record.get("names"), count, where, "created names"),
            places,
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
            places,
            strict=True,
        )
    ]
    for position, (step, entry, t, c, d, n) in enumerate(
        zip(
            (s for _, s in steps),
            entries,
            types,
            created,
            depends_on,
            places,
            strict=True,
        ),
        start=1,
    ):
        _check_step(step, position, entry, t, c, d, n)
    if entries:
        _check_columns_out(columns_out, steps[-1][1], entries[-1], created[-1], where)
    source = _learned_from(record.get("data"), where)
    pipe._restore(entries, types, created, columns_out, target, depends_on, source)


def offer_saved(pipe: Pipeline, file: str) -> None:
    """Offer a loaded pipeline's values to the store, by the data's stable key.

    A `learn`, `train` or search of a pipeline with the same steps on the
    same unchanged data then finds them and learns nothing; a file or table
    is also remembered, so a change since the save is said at the next
    learn (spec section 6). Nothing happens for data of kind ``unknown``.

    Parameters
    ----------
    pipe : Pipeline
        A pipeline given its learned values by `restore_learned`.
    file : str
        The saved file, as `load` was given it, for the warning.

    Examples
    --------
    >>> import json, os, tempfile
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> from sqlearn._store import STORE
    >>> frame = pd.DataFrame({"a": [1.0, 3.0]})
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     target = os.path.join(folder, "pipe.json")
    ...     sq.save(sq.Pipeline([sq.scale.standard()]).learn(frame), target)
    ...     sq.store.clear()
    ...     loaded = sq.load(target)  # calls offer_saved
    >>> _ = sq.Pipeline(loaded.steps).learn(frame)
    >>> STORE.learns
    Counter()
    """
    if pipe._source is None or pipe._entries is None:
        return
    origin, saved, _ = pipe._source
    if saved is None:
        return
    stable = saved if pipe._target is None else (*saved, ("target", pipe._target))
    steps, _ = pipe._split()
    for i, entry in enumerate(pipe._entries):
        depends_on = frozenset((pipe._depends_on or [])[i])
        key = step_key(stable, None, steps, i, depends_on, entry.columns)
        STORE.put_stable(key, entry)
    if origin is not None:
        STORE.remember_saved(origin, saved, file)
