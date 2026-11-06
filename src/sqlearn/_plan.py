"""The run planner: which run each step learns in, from the graph of columns."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import cast

import duckdb
from duckdb.sqltypes import DOUBLE, DuckDBPyType

from sqlearn._diagnose import diagnose
from sqlearn._errors import StepError
from sqlearn._names import name_columns
from sqlearn._selectors import Schema, Selector, _Cols, to_selector
from sqlearn._step import Learned, Step, classify, output_labels, row_outputs

__all__ = ["Plan", "plan"]


@dataclass
class Plan:
    """When each step of a pipeline learns, and which steps it reads from.

    Runs are numbered from 0. Build one with `plan`.

    Attributes
    ----------
    learn_run : list of int
        Per step, the run in which it learns (a static step that learns
        nothing gets the run its inputs allow).
    apply_run : list of int
        Per step, the run from which its output is available to later steps:
        the run it learns in for a static step, the run after for a dynamic
        one.
    feed_run : int
        The run that produces the data for the model, or for ``apply``.
    depends_on : list of frozenset of int
        Per step, the earlier steps whose output it reads, followed back
        through the graph of columns (ADR 0024).

    Examples
    --------
    >>> from sqlearn._plan import Plan
    >>> Plan(learn_run=[0], apply_run=[0], feed_run=0, depends_on=[frozenset()])
    Plan(learn_run=[0], apply_run=[0], feed_run=0, depends_on=[frozenset()])
    """

    learn_run: list[int] = field(default_factory=list)
    apply_run: list[int] = field(default_factory=list)
    feed_run: int = 0
    depends_on: list[frozenset[int]] = field(default_factory=list)


@dataclass(frozen=True, eq=False)
class _Column:
    """A column at some point in the pipeline, as the planner sees it.

    ``name`` None stands for the columns a dynamic step creates, whose names
    are not known before it learns; ``dtype`` None for any type.
    """

    name: str | None
    dtype: DuckDBPyType | None
    ready: int
    deps: frozenset[int]


def _reads_unknown(selector: Selector, column: _Column, known: set[str]) -> bool:
    if isinstance(selector, _Cols):
        return any(name not in known for name in selector.names)
    return column.dtype is None or selector.may_match(column.dtype)


def _may_read(step: Step, gone: _Column, known: set[str]) -> bool:
    """Whether a step's selector could have matched a column taken away."""
    if step.cols is None:
        return True
    selector = to_selector(step.cols)
    if isinstance(selector, _Cols) and gone.name is not None:
        return gone.name in selector.names
    return _reads_unknown(selector, gone, known)


def _consumes(step: Step, column: _Column) -> bool:
    # A read column is certainly consumed when it is known by name, or when
    # the step reads every column, or its selector must match the whole group.
    if column.name is not None or step.cols is None:
        return True
    selector = to_selector(step.cols)
    if isinstance(selector, _Cols) or column.dtype is None:
        return False
    return selector._must(column.dtype)


def _known(columns: list[_Column]) -> Schema:
    return [
        (c.name, c.dtype) for c in columns if c.name is not None and c.dtype is not None
    ]


def _reads_every_column(step: Step) -> bool:
    """Whether a step reads every column: no cols= and no default of its own."""
    return step.cols is None and type(step).inputs is Step.inputs


def _read(step: Step, columns: list[_Column]) -> list[_Column]:
    if _reads_every_column(step):
        return list(columns)
    if step.cols is None:
        # The step chooses its own columns (sq.scale.robust() the numeric
        # ones): it reads the known columns it chooses, and may choose any
        # column not yet known.
        try:
            chosen = set(step.inputs(_known(columns)))
        except Exception:  # noqa: BLE001  (refused at learn, with its message)
            return list(columns)
        return [
            c for c in columns if c.name is None or c.dtype is None or c.name in chosen
        ]
    selector = to_selector(step.cols)
    known = _known(columns)
    chosen = set(selector.resolve(known))
    names = {name for name, _ in known}
    return [
        c
        for c in columns
        if (c.name in chosen) or (c.name is None and _reads_unknown(selector, c, names))
    ]


def plan(steps: Sequence[tuple[str, Step]], schema: Schema) -> Plan:
    """Plan the runs of a pipeline before any SQL is run.

    Each step goes in the earliest run its own inputs allow (ADR 0018). The
    columns a dynamic step creates are unknown until the run after it learns;
    a step reads them when it names a column not yet known, when its selector
    may match their declared type (any type when ``creates`` is None), or when
    it works on every column (then it depends on every earlier step). A step
    left without ``cols`` that chooses its own (``sq.scale.robust()`` the
    numeric columns, by its ``inputs``) reads the known columns it chooses
    and every column not yet known. A step
    that changes rows is read by every later step (ADR 0024). A column a
    dynamic step takes away decides what a later step reads too: a step whose
    selector could have matched it (by name, by kind, or every column)
    depends on the step that took it away, and on what that step depends on.
    Every output of a whole-row step (``rowwise``) reads every input it
    selected; its outputs are named as the compositor names them, or unknown
    when its inputs or outputs are not known before it learns. A step that
    learns from the target (``uses_target``) ends its run, as a dynamic step
    does: in training, the rows reaching a later step take their values from
    what it learned on their inner fold's complement, known only once it has
    learned. Its outputs are known: one DOUBLE per input, named as a static
    step's.

    Parameters
    ----------
    steps : sequence of (str, Step)
        The named steps, in pipeline order.
    schema : list of (str, DuckDBPyType)
        The columns of the data reaching the first step.

    Returns
    -------
    Plan
        The run of each step, the run that feeds the model, and what each
        step depends on.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from duckdb.sqltypes import DOUBLE, VARCHAR
    >>> from sqlearn._plan import plan
    >>> class OneHot(sq.Step):
    ...     static = False
    ...     creates = DOUBLE
    >>> schema = [("city", VARCHAR), ("age", DOUBLE)]
    >>> p = plan(
    ...     [("onehot", OneHot("city")), ("scale", sq.Step(sq.cols.numeric()))], schema
    ... )
    >>> p.learn_run, p.feed_run
    ([0, 1], 1)
    """
    columns = [_Column(name, dtype, 0, frozenset()) for name, dtype in schema]
    # The rows themselves, read by every step: a step that changes them
    # makes every later step wait for it and depend on it.
    rows = _Column(None, None, 0, frozenset())
    # The columns dynamic steps took away, each carrying its remover's
    # dependencies: their absence decides what a later selector matches.
    removed: list[_Column] = []
    result = Plan()
    for i, (step_name, step) in enumerate(steps):
        if step.static and step.dynamic:
            msg = (
                f"{step_name} (step {i + 1}) declares both static=True and "
                "dynamic=True, which contradict each other. "
                "Fix: declare one, or neither (sqlearn will then detect it)."
            )
            raise StepError(msg, step=step_name, position=i + 1)
        if step.uses_target:
            _check_target_step(step, step_name, i + 1)
        dynamic = classify(step, _known(columns)) == "dynamic"
        read = _read(step, columns)
        learn = max((c.ready for c in [*read, rows]), default=0)
        names = {name for name, _ in _known(columns)}
        absent = [c for c in removed if _may_read(step, c, names)]
        deps = frozenset().union(*(c.deps for c in [*read, rows, *absent]))
        if _reads_every_column(step):
            deps = frozenset(range(i))
        ready = learn + 1 if dynamic or step.uses_target else learn
        mine = deps | {i}
        result.learn_run.append(learn)
        result.apply_run.append(ready)
        result.depends_on.append(deps)
        try:
            if step.rowwise and not dynamic:
                columns, gone = _write_row(step, step_name, columns, read, ready, mine)
            elif step.uses_target and not dynamic:
                columns, gone = _write(
                    step, step_name, columns, read, ready, mine, False, DOUBLE
                )
            else:
                columns, gone = _write(
                    step, step_name, columns, read, ready, mine, dynamic
                )
        except Exception as exc:
            # A step declared static whose apply cannot be read before it
            # learns (`_labels`, `_write_row`): say which and why (ADR 0019).
            err = diagnose(exc, steps, partial(_at, i + 1))
            if err is exc:
                raise
            raise err from exc
        removed.extend(gone)
        if step.changes_rows:
            rows = _Column(None, None, ready, mine)
    result.feed_run = max((c.ready for c in [*columns, rows]), default=0)
    return result


def _at(position: int, _: str) -> int:
    """Return `position`, whatever the message: the step that failed."""
    return position


def _check_target_step(step: Step, step_name: str, position: int) -> None:
    """Refuse a target step without whole-number ``cv`` and ``seed`` settings."""
    for setting in ("cv", "seed"):
        value = getattr(step, setting, None)
        if isinstance(value, bool) or not isinstance(value, int):
            msg = (
                f"{step_name} (step {position}) learns from the target, so it "
                f"needs the setting {setting} as a whole number (its inner "
                f"folds), but has {setting}={value!r}. Fix: set self.{setting} "
                "in __init__, such as cv=5, seed=0."
            )
            raise StepError(msg, step=step_name, position=position)


def _write(
    step: Step,
    step_name: str,
    columns: list[_Column],
    read: list[_Column],
    ready: int,
    deps: frozenset[int],
    dynamic: bool,
    dtype: DuckDBPyType | None = None,
) -> tuple[list[_Column], list[_Column]]:
    """Return the columns after the step, and those it took away.

    `dtype`, when given, is the type of a static step's outputs. A static
    step whose `apply` returns labelled columns (a mapping or pairs) writes
    those columns, of the type it `creates`, named as the compositor names
    them.
    """
    # Columns are compared by identity (`_Column` has eq=False on purpose):
    # two unknown groups may hold equal fields yet be different columns.
    chosen = {id(c) for c in read}
    out: list[_Column] = []
    gone: list[_Column] = []
    new: list[tuple[int, str]] = []  # created columns to name, with labels
    labelled: list[int] = []  # those a labelled output created
    for c in columns:
        if id(c) not in chosen or step.keep:
            out.append(c)
        if id(c) not in chosen:
            continue
        labels = (
            None
            if dynamic or dtype or step.rowwise
            else _labels(step, step_name, c.name)
        )
        if labels is not None:
            for column, label in labels:
                labelled.append(len(out))
                new.append((len(out), label))
                out.append(_Column(column, step.creates, ready, deps))
        elif dynamic and not _consumes(step, c):
            # The step may read only part of an unknown group: the rest stays.
            if not step.keep:
                out.append(c)
        elif not dynamic:
            if step.keep:
                new.append((len(out), step.suffix or step_name))
            out.append(_Column(c.name, dtype or c.dtype, ready, deps))
        elif not step.keep:
            gone.append(_Column(c.name, c.dtype, ready, deps))
    _name_new(out, new)
    for i in labelled:
        # A column of unknown type is not known by name either.
        if out[i].dtype is None:
            out[i] = _Column(None, None, out[i].ready, out[i].deps)
    if dynamic and read:
        out.append(_Column(None, step.creates, ready, deps))
    return out, gone


def _labels(
    step: Step, step_name: str, name: str | None
) -> list[tuple[str, str]] | None:
    """Return a static step's labelled outputs for a column, from placeholders.

    Each is ``(column, label)`` as the compositor plans it; None when `apply`
    returns one expression or the column is not known by name. A step left
    undeclared whose `apply` cannot be read with placeholders is planned as
    one output, as before; for one declaring ``static=True`` the failure is
    raised, since its columns must follow from its settings. A step learning
    from the target writes one expression per input.
    """
    if name is None or step.uses_target:
        return None
    x = duckdb.ColumnExpression(name)
    try:
        slots = {key: f"v{i}" for i, key in enumerate(step.learn(x))}
        result = step.apply(x, Learned.placeholders("learn", slots))
    except Exception:
        if step.static is True:
            raise  # explained by `plan`, as the compositor would
        return None  # undeclared: unreadable outputs are planned as one
    if isinstance(result, duckdb.Expression):
        return None
    pairs = output_labels(step_name, result, step.keep, step.suffix)
    if step.names_are_labels:
        return [(name, label) for label, _ in pairs]
    return [(label, "") for label, _ in pairs]


def _write_row(
    step: Step,
    step_name: str,
    columns: list[_Column],
    read: list[_Column],
    ready: int,
    deps: frozenset[int],
) -> tuple[list[_Column], list[_Column]]:
    """Return the columns after a static whole-row step (none is taken away).

    Each output carries `deps`, which joins the dependencies of every input,
    so a later step reading one output reads them all. An output is placed
    and named as `sqlearn._compose.step_stage` does it; when the inputs are
    not all known by name, or `apply_row` needs learned values, the outputs
    are one unknown group of the type the step `creates`.
    """
    chosen = {id(c) for c in read}
    names = [c.name for c in read]
    try:
        keys = None if None in names else row_outputs(step, cast("list[str]", names))
    except Exception:
        if step.static is True:
            raise  # declared static, so its outputs must be readable now
        keys = None  # unknown outputs are planned as unknown
    if keys is None:
        unknown, _ = _write(step, step_name, columns, read, ready, deps, dynamic=False)
        if read:
            unknown.append(_Column(None, step.creates, ready, deps))
        return unknown, []
    owned: dict[str | None, list[str]] = {name: [] for name in names}
    for key in keys:
        owned[key if key in owned else names[-1]].append(key)
    types = {c.name: c.dtype for c in read}
    label = (step.suffix or step_name) if step.keep and step.names_are_labels else ""
    out: list[_Column] = []
    new: list[int] = []
    for c in columns:
        if id(c) not in chosen or step.keep:
            out.append(c)
        if id(c) in chosen:
            for key in owned[c.name]:
                new.append(len(out))
                dtype = types.get(key, step.creates)
                out.append(_Column(key, dtype, ready, deps))
    taken = [c.name for i, c in enumerate(out) if i not in set(new)]
    final: list[str | None] = [None] * len(new)
    if None not in taken:
        planned = [(cast("str", out[i].name), label) for i in new]
        final = list(name_columns(planned, cast("list[str]", taken)))
    for i, name in zip(new, final, strict=True):
        c = out[i]
        # A column of unknown type is not known by name either.
        known = name if c.dtype is not None else None
        out[i] = _Column(known, c.dtype, c.ready, c.deps)
    return out, []


def _name_new(out: list[_Column], new: list[tuple[int, str]]) -> None:
    """Name the columns a step created as the compositor will.

    `new` holds each created column's place in `out` and its label; its
    planned name is ``<column>_<label>`` from the column name it holds now.
    The names follow `name_columns`, so a name in use is numbered. If an
    unknown column is present it might hold the name, so the new columns are
    left unknown too.
    """
    if not new:
        return
    places = {i for i, _ in new}
    known = [c.name for i, c in enumerate(out) if i not in places]
    columns = [out[i].name for i, _ in new]
    names: list[str | None] = [None] * len(new)
    if None not in known and None not in columns:
        planned = [(cast("str", out[i].name), label) for i, label in new]
        taken = [name for name in known if name is not None]
        names = list(name_columns(planned, taken))
    for (i, _), name in zip(new, names, strict=True):
        c = out[i]
        out[i] = _Column(name, c.dtype, c.ready, c.deps)
