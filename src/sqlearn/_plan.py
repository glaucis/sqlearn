"""The run planner: which run each step learns in, from the graph of columns."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from duckdb.sqltypes import DuckDBPyType

from sqlearn._selectors import Schema, Selector, _Cols, to_selector
from sqlearn._step import Step, classify

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


def _read(step: Step, columns: list[_Column]) -> list[_Column]:
    if step.cols is None:
        return list(columns)
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
    that changes rows is read by every later step (ADR 0024).

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
    >>> p = plan([("onehot", OneHot("city")), ("scale", sq.Step(sq.numeric()))], schema)
    >>> p.learn_run, p.feed_run
    ([0, 1], 1)
    """
    columns = [_Column(name, dtype, 0, frozenset()) for name, dtype in schema]
    # The rows themselves, read by every step: a step that changes them
    # makes every later step wait for it and depend on it.
    rows = _Column(None, None, 0, frozenset())
    result = Plan()
    for i, (step_name, step) in enumerate(steps):
        dynamic = classify(step, _known(columns)) == "dynamic"
        read = _read(step, columns)
        learn = max((c.ready for c in [*read, rows]), default=0)
        deps = frozenset().union(*(c.deps for c in [*read, rows]))
        if step.cols is None:
            deps = frozenset(range(i))
        ready = learn + 1 if dynamic else learn
        mine = deps | {i}
        result.learn_run.append(learn)
        result.apply_run.append(ready)
        result.depends_on.append(deps)
        columns = _write(step, step_name, columns, read, ready, mine, dynamic)
        if step.changes_rows:
            rows = _Column(None, None, ready, mine)
    result.feed_run = max((c.ready for c in [*columns, rows]), default=0)
    return result


def _write(
    step: Step,
    step_name: str,
    columns: list[_Column],
    read: list[_Column],
    ready: int,
    deps: frozenset[int],
    dynamic: bool,
) -> list[_Column]:
    # Columns are compared by identity (`_Column` has eq=False on purpose):
    # two unknown groups may hold equal fields yet be different columns.
    chosen = {id(c) for c in read}
    out: list[_Column] = []
    for c in columns:
        if id(c) not in chosen or step.keep:
            out.append(c)
        elif dynamic and not _consumes(step, c):
            # The step may read only part of an unknown group: the rest stays.
            out.append(c)
        elif not dynamic:
            out.append(_Column(c.name, c.dtype, ready, deps))
        if id(c) in chosen and step.keep and not dynamic:
            name = None if c.name is None else f"{c.name}_{step.suffix or step_name}"
            out.append(_Column(name, c.dtype, ready, deps))
    if dynamic and read:
        out.append(_Column(None, step.creates, ready, deps))
    return out
