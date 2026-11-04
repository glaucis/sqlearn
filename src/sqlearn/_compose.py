"""The compositor: the one place that turns step pieces into SQL text.

A run is one chain of ``WITH`` stages (ADR 0012, ADR 0018). Each step has a
data stage, named after it (``s03_scale``), reading the stage before it; a
step that learns in the run also has a learn stage (``l03_scale``): one row of
aggregates over the stage before the step, cross-joined into the step's data
stage. Learned values are referenced there, never written in as numbers, so a
later step learns from an earlier step's output. Every identifier written goes
through `quote` (ADR 0015).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial

import duckdb
from duckdb import Expression

from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import quote
from sqlearn._selectors import Schema
from sqlearn._step import Learned, Step, output_names

__all__ = [
    "SOURCE",
    "Run",
    "Stage",
    "build",
    "describe",
    "execute",
    "stage_name",
    "step_stage",
]

SOURCE = "source"
"""The name of the first stage, which holds the data a run reads."""

Values = dict[str, dict[str, object]]
"""What one step learned: learned name, then column, to value (as the store)."""


def stage_name(position: int, step_name: str, learn: bool = False) -> str:
    """Name the stage of a step, so an error can be traced back to it.

    Parameters
    ----------
    position : int
        The step's position in the pipeline (zero-padded to two digits).
    step_name : str
        The step's name.
    learn : bool, default False
        Name the learn stage (``l``) rather than the data stage (``s``).

    Returns
    -------
    str
        ``s03_scale`` for data, ``l03_scale`` for learn.

    Examples
    --------
    >>> from sqlearn._compose import stage_name
    >>> stage_name(3, "scale"), stage_name(3, "scale", learn=True)
    ('s03_scale', 'l03_scale')
    """
    return f"{'l' if learn else 's'}{position:02d}_{step_name}"


@dataclass
class Stage:
    """One step's stages in a run: its data stage and, if it learns, its learn stage.

    Build one with `step_stage`. The learn stage, when there is one, is named
    `learn_name` and aggregates over the stage before this one.

    Attributes
    ----------
    name : str
        The data stage's name, from `stage_name`.
    columns : dict of str to duckdb.Expression
        Every output column, in order: untouched columns pass through.
    learn : dict of str to duckdb.Expression or None
        Internal name (``v0``, ``v1``, ...) to aggregate; None when the step
        learns nothing in this run.
    reads : list of str
        The learn stages the data stage cross-joins.
    learned : dict of str to (str, str)
        Internal name to the ``(column, learned name)`` it stores.
    remake : callable or None
        Builds this stage again from learned values (`Values`), with them as
        constants; None when the stage learns nothing.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._compose import Stage, build
    >>> stage = Stage("s00_copy", {"a": duckdb.ColumnExpression("a")})
    >>> build("SELECT 1 AS a", [stage]).splitlines()[-1]
    'SELECT * FROM "s00_copy"'
    """

    name: str
    columns: dict[str, Expression]
    learn: dict[str, Expression] | None = None
    reads: list[str] = field(default_factory=list)
    learned: dict[str, tuple[str, str]] = field(default_factory=dict)
    remake: Callable[[Values], "Stage"] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def learn_name(self) -> str:
        """The learn stage's name: the data stage's, with ``l`` for ``s``.

        Returns
        -------
        str
            ``l03_scale`` for the data stage ``s03_scale``.

        Examples
        --------
        >>> from sqlearn._compose import Stage
        >>> Stage("s03_scale", {}).learn_name
        'l03_scale'
        """
        return "l" + self.name[1:]


@dataclass
class Run:
    """The SQL statements one run executed, in order.

    Attributes
    ----------
    statements : list of str
        The learn statement (if the run learns), then the data query (if it
        produces).

    Examples
    --------
    >>> from sqlearn._compose import Run
    >>> Run(["SELECT 1"]).statements
    ['SELECT 1']
    """

    statements: list[str] = field(default_factory=list)


def step_stage(
    position: int,
    step_name: str,
    step: Step,
    schema: Schema,
    previous: str,
    values: Mapping[str, Mapping[str, object]] | None = None,
    *,
    applies: bool = True,
) -> Stage:
    """Build a step's stage from its `learn` and `apply`.

    Without `values`, the step learns in this run: its aggregates form the
    learn stage, and `apply` reads them through placeholders. With `values`,
    they are constants and there is no learn stage. Columns are referenced
    qualified by `previous`, so no column can be confused with a learned
    value.

    Parameters
    ----------
    position : int
        The step's position in the pipeline, counting from zero.
    step_name : str
        The step's name.
    step : Step
        The step.
    schema : list of (str, DuckDBPyType)
        The columns of the stage before, in order (see `describe`).
    previous : str
        The name of the stage before: `SOURCE` or another stage's name.
    values : mapping, optional
        What the step learned (learned name, then column, to value).
    applies : bool, default True
        False for a dynamic step learning in this run: its output is not
        known yet, so its columns pass through.

    Returns
    -------
    Stage
        The step's stage.

    Raises
    ------
    StepError
        If two output columns share a name (DuckDB names ignore case).

    Examples
    --------
    >>> import sqlearn as sq
    >>> from duckdb.sqltypes import DOUBLE
    >>> from sqlearn._compose import SOURCE, step_stage
    >>> class Centre(sq.Step):
    ...     def learn(self, x):
    ...         return {"mean": sq.avg(x)}
    ...
    ...     def apply(self, x, learned):
    ...         return x - learned.mean
    >>> stage = step_stage(0, "centre", Centre(), [("a", DOUBLE)], SOURCE)
    >>> str(stage.columns["a"])
    '("source"."a" - "l00_centre"."v0")'
    >>> stage.learned
    {'v0': ('a', 'mean')}
    """
    name = stage_name(position, step_name)
    learn_name = stage_name(position, step_name, learn=True)
    columns = {c: duckdb.ColumnExpression(previous, c) for c, _ in schema}
    learn: dict[str, Expression] = {}
    learned: dict[str, tuple[str, str]] = {}
    per_column: dict[str, Learned] = {}
    for c in step.inputs(schema):
        if values is None:
            names: dict[str, str] = {}
            for key, aggregate in step.learn(columns[c]).items():
                internal = f"v{len(learn)}"
                learn[internal] = aggregate
                learned[internal] = (c, key)
                names[key] = internal
            per_column[c] = Learned.placeholders(learn_name, names)
        else:
            per_column[c] = Learned.values(
                {k: v[c] for k, v in values.items() if c in v},
            )
    out: list[tuple[str, Expression]] = []
    for c, _ in schema:
        if c not in per_column or not applies:
            out.append((c, columns[c]))
            continue
        if step.keep:
            out.append((c, columns[c]))
        result = step.apply(columns[c], per_column[c])
        out.extend(output_names(step_name, c, result, step.keep, step.suffix).items())
    clash = _clash([n for n, _ in out])
    if clash is not None:
        msg = (
            f"{step_name} (step {position}) makes two columns named {clash!r}: "
            "an output takes a name already in use (DuckDB names ignore case). "
            "Fix: set suffix= on the step, or rename the column before it."
        )
        raise StepError(msg, step=step_name, position=position)

    remake = partial(step_stage, position, step_name, step, schema, previous)
    return Stage(
        name=name,
        columns=dict(out),
        learn=learn or None,
        reads=[learn_name] if learn and applies else [],
        learned=learned,
        remake=partial(remake, applies=applies) if learn else None,
    )


def _clash(names: list[str]) -> str | None:
    seen: set[str] = set()
    for n in names:
        if n.lower() in seen:
            return n
        seen.add(n.lower())
    return None


def _items(items: Mapping[str, Expression]) -> str:
    return ", ".join(f"{e} AS {quote(k)}" for k, e in items.items())


def _check(stage: Stage) -> None:
    if not stage.columns:
        msg = f"stage {stage.name!r} has no columns; a stage must output one."
        raise SqlearnError(msg)
    clash = _clash(list(stage.columns))
    if clash is not None:
        msg = (
            f"stage {stage.name!r} has two columns named {clash!r} "
            "(DuckDB names ignore case); rename one of them."
        )
        raise SqlearnError(msg)
    if stage.learn and set(stage.learned) != set(stage.learn):
        msg = (
            f"stage {stage.name!r} learns values not mapped to a column and "
            "a name; build the stage with step_stage."
        )
        raise SqlearnError(msg)


def _chain(source_sql: str, stages: list[Stage], every_learn: bool) -> list[str]:
    read = {r for s in stages for r in s.reads}
    ctes = [f"{quote(SOURCE)} AS (SELECT * FROM ({source_sql}))"]
    previous = SOURCE
    for stage in stages:
        _check(stage)
        if stage.learn and (every_learn or stage.learn_name in read):
            # MATERIALIZED, never NOT MATERIALIZED: the one row is computed once.
            ctes.append(
                f"{quote(stage.learn_name)} AS MATERIALIZED "
                f"(SELECT {_items(stage.learn)} FROM {quote(previous)})",
            )
        joins = "".join(f" CROSS JOIN {quote(r)}" for r in stage.reads)
        ctes.append(
            f"{quote(stage.name)} AS "
            f"(SELECT {_items(stage.columns)} FROM {quote(previous)}{joins})",
        )
        previous = stage.name
    return ctes


def build(source_sql: str, stages: list[Stage]) -> str:
    """Compose stages into one ``WITH`` query producing the last stage's data.

    Parameters
    ----------
    source_sql : str
        The data: a query (such as a relation's ``sql_query()``) or a table
        or view name, wrapped as the first stage, `SOURCE`.
    stages : list of Stage
        The steps' stages, in pipeline order.

    Returns
    -------
    str
        The query, ending in ``SELECT * FROM`` the last data stage. Only the
        learn stages some data stage reads are included.

    Raises
    ------
    SqlearnError
        If a stage has no columns or two columns sharing a name.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._compose import Stage, build
    >>> stage = Stage("s00_double", {"a": duckdb.ColumnExpression("a") * 2})
    >>> sql = build("SELECT 21 AS a", [stage])
    >>> duckdb.sql(sql).fetchall()
    [(42,)]
    """
    ctes = _chain(source_sql, stages, every_learn=False)
    last = stages[-1].name if stages else SOURCE
    return "WITH " + ",\n".join(ctes) + f"\nSELECT * FROM {quote(last)}"


def _learn_sql(source_sql: str, stages: list[Stage]) -> str:
    last = max(i for i, s in enumerate(stages) if s.learn)
    ctes = _chain(source_sql, stages[: last + 1], every_learn=True)
    learning = [s for s in stages if s.learn]
    picks = ", ".join(
        f"{quote(s.learn_name)}.{quote(k)} AS {quote(f'r{i}')}"
        for i, (s, k) in enumerate((s, k) for s in learning for k in s.learn or {})
    )
    sources = " CROSS JOIN ".join(quote(s.learn_name) for s in learning)
    return "WITH " + ",\n".join(ctes) + f"\nSELECT {picks} FROM {sources}"


def describe(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    stages: list[Stage],
) -> Schema:
    """Return the columns the stages output, binding the query without running it.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection holding the data.
    source_sql : str
        The data, as for `build`.
    stages : list of Stage
        The stages, in pipeline order.

    Returns
    -------
    list of (str, DuckDBPyType)
        The last stage's columns and their types.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._compose import describe
    >>> describe(duckdb.connect(), "SELECT 1.5 AS a", [])
    [('a', DECIMAL(2,1))]
    """
    rel = con.sql(build(source_sql, stages))
    return list(zip(rel.columns, rel.types, strict=True))


def execute(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    stages: list[Stage],
    *,
    produce: bool,
) -> tuple[dict[str, Values], duckdb.DuckDBPyRelation | None, Run]:
    """Execute one run: learn its values, and produce its data if asked.

    A run that learns is first one statement: the chain of stages, ending in
    one row holding every learn stage's values, fetched. If the run also
    produces, the data query follows, with the learned values as constants
    (each learning stage is remade), returned as a lazy relation. A run that
    only applies is the data query alone. There are no temporary tables.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection holding the data.
    source_sql : str
        The data, as for `build`.
    stages : list of Stage
        The steps' stages, in pipeline order.
    produce : bool
        Whether to return the data query.

    Returns
    -------
    values : dict of str to Values
        Per learning stage, keyed by its data stage's name (such as
        ``"s03_scale"``): learned name, then column, to value.
    relation : duckdb.DuckDBPyRelation or None
        The data, not yet executed; None unless `produce`.
    run : Run
        The statements, in order.

    Raises
    ------
    SqlearnError
        If `produce` is asked for and a learning stage cannot be remade.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> from duckdb.sqltypes import DOUBLE
    >>> from sqlearn._compose import SOURCE, execute, step_stage
    >>> class Centre(sq.Step):
    ...     def learn(self, x):
    ...         return {"mean": sq.avg(x)}
    ...
    ...     def apply(self, x, learned):
    ...         return x - learned.mean
    >>> stage = step_stage(0, "centre", Centre(), [("a", DOUBLE)], SOURCE)
    >>> source = "SELECT * FROM (VALUES (1.0), (3.0)) t(a)"
    >>> values, rel, run = execute(duckdb.connect(), source, [stage], produce=True)
    >>> values
    {'s00_centre': {'mean': {'a': 2.0}}}
    >>> rel.fetchall(), len(run.statements)
    ([(-1.0,), (1.0,)], 2)
    """
    learning = [s for s in stages if s.learn]
    if produce:
        for s in learning:
            if s.remake is None:
                msg = (
                    f"stage {s.name!r} learns but cannot be remade with its "
                    "values; build the stage with step_stage."
                )
                raise SqlearnError(msg)
    run = Run()
    values: dict[str, Values] = {}
    if learning:
        sql = _learn_sql(source_sql, stages)
        run.statements.append(sql)
        row = iter(con.sql(sql).fetchall()[0])
        for s in learning:
            mine: Values = {}
            for k in s.learn or {}:
                column, name = s.learned[k]
                mine.setdefault(name, {})[column] = next(row)
            values[s.name] = mine
    if not produce:
        return values, None, run
    final = [
        s.remake(values[s.name]) if s.learn and s.remake is not None else s
        for s in stages
    ]
    sql = build(source_sql, final)
    run.statements.append(sql)
    return values, con.sql(sql), run
