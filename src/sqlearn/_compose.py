"""The compositor: the one place that turns step pieces into SQL text.

A run is one chain of ``WITH`` stages (ADR 0012, ADR 0018). Each step has a
data stage, named after it (``s03_scale``), reading the stage before it; a
step that learns in the run also has a learn stage (``l03_scale``): one row of
aggregates over the stage before the step, cross-joined into the step's data
stage. Learned values are referenced there, never written in as numbers, so a
later step learns from an earlier step's output. Every identifier written goes
through `quote` (ADR 0015).

A median (`sqlearn.median`, a marker) is not an aggregate DuckDB can compute
larger than memory, so a learn stage's medians get stages of their own beside
it: the present values of every median column, numbered in sorted order by one
window (a sort, which spills to disk), and the one or two middle ones picked
from each. Their one-row result is cross-joined into the learn stage, so a
median comes back like any other learned value.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial

import duckdb
from duckdb import Expression

from sqlearn._errors import InternalError, SqlearnError, StepError
from sqlearn._expr import MEDIAN, quote
from sqlearn._selectors import Schema
from sqlearn._step import Learned, Step, output_names

__all__ = [
    "SOURCE",
    "Run",
    "Stage",
    "apply_sql",
    "build",
    "copy_sql",
    "describe",
    "execute",
    "number_rows",
    "stage_name",
    "step_stage",
]

SOURCE = "source"
"""The name of the first stage, which holds the data a run reads."""

_ROWS = "n"
"""The column of a learn stage counting the rows it learned from."""

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
    step : str
        The name of the step the stage belongs to, for messages.
    position : int
        The step's position in the pipeline, counting from 1.

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
    step: str = ""
    position: int = 0

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
    columns: Sequence[str] | None = None,
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
        The step's position in the pipeline, counting from 1.
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
    columns : sequence of str, optional
        The columns the step works on, as fixed when it learned; by default
        the step's selector is resolved against `schema`.

    Returns
    -------
    Stage
        The step's stage.

    Raises
    ------
    StepError
        If two output columns share a name (DuckDB names ignore case).
    SqlearnError
        If `values` lacks a value the step learns for one of its columns.

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
    >>> stage = step_stage(1, "centre", Centre(), [("a", DOUBLE)], SOURCE)
    >>> str(stage.columns["a"])
    '("source"."a" - "l01_centre"."v0")'
    >>> stage.learned
    {'v0': ('a', 'mean')}
    """
    name = stage_name(position, step_name)
    learn_name = stage_name(position, step_name, learn=True)
    exprs = {c: duckdb.ColumnExpression(previous, c) for c, _ in schema}
    chosen = step.inputs(schema) if columns is None else list(columns)
    learn: dict[str, Expression] = {}
    learned: dict[str, tuple[str, str]] = {}
    per_column: dict[str, Learned] = {}
    for c in chosen:
        aggregates = step.learn(exprs[c])
        if values is None:
            names: dict[str, str] = {}
            for key, aggregate in aggregates.items():
                internal = f"v{len(learn)}"
                learn[internal] = aggregate
                learned[internal] = (c, key)
                names[key] = internal
            per_column[c] = Learned.placeholders(learn_name, names)
        else:
            per_column[c] = Learned.values(_known(name, c, aggregates, values))
    out: list[tuple[str, Expression]] = []
    named = False  # names come from the learned values, not from suffix=
    for c, _ in schema:
        if c not in per_column or not applies:
            out.append((c, exprs[c]))
            continue
        if step.keep:
            out.append((c, exprs[c]))
        result = step.apply(exprs[c], per_column[c])
        named = named or not isinstance(result, Expression)
        out.extend(output_names(step_name, c, result, step.keep, step.suffix).items())
    clash = _clash([n for n, _ in out])
    if clash is not None:
        fix = (
            "Fix: rename the column before it. This step names its columns "
            "after the values it learned; how such names are chosen and "
            "clashes resolved is open in "
            "https://github.com/glaucis/sqlearn/issues/26."
            if named
            else "Fix: set suffix= on the step, or rename the column before it."
        )
        msg = (
            f"{step_name} (step {position}) makes two columns named {clash!r}: "
            "an output takes a name already in use (DuckDB names ignore case). "
            f"{fix}"
        )
        raise StepError(msg, step=step_name, position=position)

    remake = partial(step_stage, position, step_name, step, schema, previous)
    return Stage(
        name=name,
        columns=dict(out),
        learn=learn or None,
        reads=[learn_name] if learn and applies else [],
        learned=learned,
        remake=partial(remake, applies=applies, columns=chosen) if learn else None,
        step=step_name,
        position=position,
    )


def _known(
    stage: str,
    column: str,
    aggregates: Mapping[str, Expression],
    values: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Pick one column's learned values, refusing one that is missing."""
    for key in aggregates:
        if column not in values.get(key, {}):
            msg = (
                f"stage {stage!r} has no learned value {key!r} for column "
                f"{column!r}; the values do not match what the step learns."
            )
            raise SqlearnError(msg)
    return {k: v[column] for k, v in values.items() if column in v}


def _clash(names: list[str]) -> str | None:
    seen: set[str] = set()
    for n in names:
        if n.lower() in seen:
            return n
        seen.add(n.lower())
    return None


def _items(items: Mapping[str, Expression]) -> str:
    return ", ".join(f"{e} AS {quote(k)}" for k, e in items.items())


def apply_sql(stage: Stage) -> str:
    """Return the SQL text of a stage's data stage, as the store keeps it.

    Parameters
    ----------
    stage : Stage
        The stage, usually built with its learned values as constants.

    Returns
    -------
    str
        The select list of the data stage.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._compose import Stage, apply_sql
    >>> apply_sql(Stage("s01_double", {"a": duckdb.ColumnExpression("a") * 2}))
    'SELECT ("a" * 2) AS "a"'
    """
    return f"SELECT {_items(stage.columns)}"


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


def _balanced(sql: str) -> bool:
    """Say whether no parenthesis in `sql` closes one opened before it."""
    depth = 0
    quoted: str | None = None
    for ch in sql:
        if quoted is not None:
            # A doubled quote inside a literal closes and reopens: still inside.
            if ch == quoted:
                quoted = None
        elif ch in "'\"":
            quoted = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _median_of(stage: Stage, expression: Expression) -> str | None:
    """Return the SQL a median marker wraps, or None when it is no median.

    A marker anywhere but at the top of a learned value is refused: the
    median is computed in stages of its own, so it must be a whole value.
    """
    text = str(expression)
    head = f"{MEDIAN}("
    if text.startswith(head) and text.endswith(")"):
        inner = text[len(head) : -1]
        if MEDIAN not in inner and _balanced(inner):
            return inner
    if MEDIAN in text:
        msg = (
            f"{stage.step} (step {stage.position}) learns {text}, which uses "
            "sq.median inside a larger expression; a median is computed by "
            "sorting, in a stage of its own, so it must be a whole learned "
            "value. Fix: learn the median as its own value, such as "
            '{"median": sq.median(x)}, and combine it in apply.'
        )
        raise StepError(msg, step=stage.step, position=stage.position)
    return None


def _median_ctes(name: str, medians: dict[str, str], previous: str) -> list[str]:
    """Return the stages computing a learn stage's medians, as one row.

    Every median of the stage is computed in one sort: the present values of
    each, tagged with the median's number, numbered in order of tag, then
    value, by one window over all of them (no partitions), which spills to
    disk. Each tag's values then hold the positions after those of the tags
    before it, so its middle one or two are found from the counts per tag.
    Each median is the middle value, or halfway between the two middle ones
    (DuckDB's ``median`` interpolates so); NULL when there is no value.

    One sort, not one per column: two sorts running in one statement hold
    memory together, and do not fit where one does. Nor one partition per
    column: a window over partitions needed more memory. DuckDB's sort itself
    keeps a little memory per row, so this reaches as far as its ``ORDER BY``
    does: under 64 MB, 20 million rows of two columns, not 60 million.
    """
    values, counts, each = (
        quote(f"{name}_{part}") for part in ("values", "counts", "each")
    )
    t, x, r, n, start, m = (quote(c) for c in ("t", "x", "r", "n", "start", "m"))
    tagged = " UNION ALL ".join(
        f"SELECT {tag} AS {t}, CAST({inner} AS DOUBLE) AS {x} FROM {quote(previous)}"
        for tag, inner in enumerate(medians.values())
    )
    pivot = ", ".join(
        f"max({m}) FILTER (WHERE {t} = {tag}) AS {quote(key)}"
        for tag, key in enumerate(medians)
    )
    return [
        f"{values} AS (SELECT {t}, {x} FROM ({tagged}) "
        f"WHERE {x} IS NOT NULL AND NOT isnan({x}))",
        f"{counts} AS (SELECT {t}, {n}, sum({n}) OVER (ORDER BY {t}) - {n} AS {start} "
        f"FROM (SELECT {t}, count(*) AS {n} FROM {values} GROUP BY {t}))",
        f"{each} AS (SELECT {t}, min({x}) + (max({x}) - min({x})) * 0.5 AS {m} "
        f"FROM (SELECT {t}, {x}, row_number() OVER (ORDER BY {t}, {x}) AS {r} "
        f"FROM {values}) JOIN {counts} USING ({t}) "
        f"WHERE {r} - {start} IN (({n} + 1) // 2, ({n} + 2) // 2) GROUP BY {t})",
        f"{quote(name)} AS MATERIALIZED (SELECT {pivot} FROM {each})",
    ]


def _learn_ctes(stage: Stage, learn: dict[str, Expression], previous: str) -> list[str]:
    """Return a learn stage, after the stages of the medians it learns."""
    ctes: list[str] = []
    aggregates: dict[str, Expression] = {}
    medians: dict[str, str] = {}
    for key, expression in learn.items():
        inner = _median_of(stage, expression)
        if inner is None:
            aggregates[key] = expression
        else:
            medians[key] = inner
    # MATERIALIZED, never NOT MATERIALIZED: the one row is computed once.
    # The row count beside the values tells "no rows" from NULL values.
    items = [_items(aggregates)] if aggregates else []
    select = (
        f"SELECT {', '.join([*items, f'count(*) AS {quote(_ROWS)}'])} "
        f"FROM {quote(previous)}"
    )
    if medians:
        name = f"{stage.learn_name}_median"
        ctes.extend(_median_ctes(name, medians, previous))
        select = f"SELECT * FROM ({select}) CROSS JOIN {quote(name)}"
    ctes.append(f"{quote(stage.learn_name)} AS MATERIALIZED ({select})")
    return ctes


def _chain(source_sql: str, stages: list[Stage], every_learn: bool) -> list[str]:
    read = {r for s in stages for r in s.reads}
    ctes = [f"{quote(SOURCE)} AS (SELECT * FROM ({source_sql}))"]
    previous = SOURCE
    for stage in stages:
        _check(stage)
        if stage.learn and (every_learn or stage.learn_name in read):
            ctes.extend(_learn_ctes(stage, stage.learn, previous))
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
        for i, (s, k) in enumerate(
            (s, k) for s in learning for k in [_ROWS, *(s.learn or {})]
        )
    )
    sources = " CROSS JOIN ".join(quote(s.learn_name) for s in learning)
    return "WITH " + ",\n".join(ctes) + f"\nSELECT {picks} FROM {sources}"


def number_rows(source_sql: str, name: str) -> str:
    """Return the data with each row numbered from 1 in the order it is read.

    ``row_number() OVER ()`` with an empty window is DuckDB's streaming
    window: it numbers rows as the scan hands them on, in the input's order
    (DuckDB keeps insertion order by default). The number then travels with
    its row, so a result can be sorted back into the input's order.

    Parameters
    ----------
    source_sql : str
        The data, as for `build`.
    name : str
        The name of the numbering column.

    Returns
    -------
    str
        The query: every column of the data, then the number.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._compose import number_rows
    >>> duckdb.sql(number_rows("SELECT 'a' AS c", "row")).fetchall()
    [('a', 1)]
    """
    return f"SELECT *, row_number() OVER () AS {quote(name)} FROM ({source_sql})"


_FORMATS = ("parquet", "csv", "json")


def copy_sql(query: str, path: str, file_format: str) -> str:
    """Return the statement writing a query's rows to a file (``COPY ... TO``).

    Parameters
    ----------
    query : str
        The query whose rows are written.
    path : str
        The file to write; quoted as a string literal.
    file_format : {"parquet", "csv", "json"}
        The file format.

    Returns
    -------
    str
        The ``COPY`` statement.

    Raises
    ------
    SqlearnError
        If `file_format` is not one of the three.

    Examples
    --------
    >>> from sqlearn._compose import copy_sql
    >>> copy_sql("SELECT 1", "it's.csv", "csv")
    "COPY (SELECT 1) TO 'it''s.csv' (FORMAT csv)"
    """
    if file_format not in _FORMATS:
        msg = f"cannot write {file_format!r} files; the formats are {_FORMATS}."
        raise SqlearnError(msg)
    literal = "'" + path.replace("'", "''") + "'"
    return f"COPY ({query}) TO {literal} (FORMAT {file_format})"


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
    StepError
        If a step learns from no rows.
    InternalError
        If the learn statement does not return exactly one row.

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
    >>> stage = step_stage(1, "centre", Centre(), [("a", DOUBLE)], SOURCE)
    >>> source = "SELECT * FROM (VALUES (1.0), (3.0)) t(a)"
    >>> values, rel, run = execute(duckdb.connect(), source, [stage], produce=True)
    >>> values
    {'s01_centre': {'mean': {'a': 2.0}}}
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
        rows = con.sql(sql).fetchall()
        if len(rows) != 1:
            msg = (
                f"the learn statement returned {len(rows)} rows, not one row. "
                "This is a bug in sqlearn: please report it with the statement "
                f"below.\n{sql}"
            )
            raise InternalError(msg)
        row = iter(rows[0])
        for s in learning:
            if next(row) == 0:
                msg = (
                    f"{s.step} (step {s.position}) learned from no rows: the data "
                    "reaching it is empty, so there is nothing to learn. "
                    "Fix: pass data with at least one row."
                )
                raise StepError(msg, step=s.step, position=s.position)
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
