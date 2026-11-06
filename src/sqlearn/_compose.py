"""The compositor: the one place that turns step pieces into SQL text.

A run is one chain of ``WITH`` stages (ADR 0012, ADR 0018). Each step has a
data stage, named after it (``s03_scale``), reading the stage before it; a
step that learns in the run also has a learn stage (``l03_scale``): one row of
aggregates over the stage before the step, cross-joined into the step's data
stage. Learned values are referenced there, never written in as numbers, so a
later step learns from an earlier step's output. Every identifier written goes
through `quote` (ADR 0015).

An exact quantile (`sqlearn.agg.quantile`, `median`, `iqr`: a marker) is not
an aggregate DuckDB can compute larger than memory, so a learn stage's
quantiles get stages of their own beside it: the present values of every
expression they sort, numbered in sorted order by one window (a sort, which
spills to disk), and the one or two values each quantile needs picked from
them. A mode (`sqlearn.agg.mode`, a marker too) is counted in a ``GROUP BY``
stage of its own. A marker may sit anywhere in a learned value: it is
replaced by a scalar subquery reading its stage's one row, so a quantile
comes back like any other learned value.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial

import duckdb
from duckdb import Expression

from sqlearn._errors import InternalError, SqlearnError, StepError
from sqlearn._expr import MODE, QUANTILE, quote
from sqlearn._names import name_columns
from sqlearn._selectors import Schema
from sqlearn._step import Learned, Step, output_labels

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
    created : dict of str to list of str
        Input column to the names of the columns created from it, in order;
        fixed when the step learns and given back to `step_stage` at apply.

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
    created: dict[str, list[str]] = field(default_factory=dict)

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
    names: Mapping[str, Sequence[str]] | None = None,
) -> Stage:
    """Build a step's stage from its `learn` and `apply`.

    Without `values`, the step learns in this run: its aggregates form the
    learn stage, and `apply` reads them through placeholders. With `values`,
    they are constants and there is no learn stage. Columns are referenced
    qualified by `previous`, so no column can be confused with a learned
    value. The created columns are named from their labels by
    `sqlearn._names.name_columns`: a clash is numbered, never refused. With
    `names`, the names fixed when the step learned are used instead, so they
    do not change with the data applied to.

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
    names : mapping of str to sequence of str, optional
        The names of the created columns, per input column, as the step's
        stage gave them when it learned (`Stage.created`).

    Returns
    -------
    Stage
        The step's stage.

    Raises
    ------
    StepError
        With `names`, if a column passing through takes a fixed name
        (DuckDB names ignore case), or the step now creates other columns
        than it did when it learned.
    SqlearnError
        If `values` lacks a value the step learns for one of its columns.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from duckdb.sqltypes import DOUBLE
    >>> from sqlearn._compose import SOURCE, step_stage
    >>> class Centre(sq.Step):
    ...     def learn(self, x):
    ...         return {"mean": sq.agg.mean(x)}
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
            internal: dict[str, str] = {}
            for key, aggregate in aggregates.items():
                slot = f"v{len(learn)}"
                learn[slot] = aggregate
                learned[slot] = (c, key)
                internal[key] = slot
            per_column[c] = Learned.placeholders(learn_name, internal)
        else:
            per_column[c] = Learned.values(_known(name, c, aggregates, values))
    # Each output is a name passing through, or a (column, label) to name;
    # `owner` holds the input column of each output to name.
    out: list[tuple[str | tuple[str, str], Expression]] = []
    owner: list[str] = []
    for c, _ in schema:
        if c not in per_column or not applies:
            out.append((c, exprs[c]))
            continue
        if step.keep:
            out.append((c, exprs[c]))
        result = step.apply(exprs[c], per_column[c])
        full = not step.names_are_labels and not isinstance(result, Expression)
        for label, e in output_labels(step_name, result, step.keep, step.suffix):
            out.append(((label, "") if full else (c, label), e))
            owner.append(c)
    taken = [k for k, _ in out if isinstance(k, str)]
    planned = [k for k, _ in out if not isinstance(k, str)]
    if names is None:
        final = name_columns(planned, taken)
    else:
        final = _fixed(step_name, position, names, owner, taken)
    created: dict[str, list[str]] = {}
    for c, n in zip(owner, final, strict=True):
        created.setdefault(c, []).append(n)
    named = iter(final)
    outputs = {k if isinstance(k, str) else next(named): e for k, e in out}

    remake = partial(step_stage, position, step_name, step, schema, previous)
    return Stage(
        name=name,
        columns=outputs,
        learn=learn or None,
        reads=[learn_name] if learn and applies else [],
        learned=learned,
        remake=partial(remake, applies=applies, columns=chosen, names=names)
        if learn
        else None,
        step=step_name,
        position=position,
        created=created,
    )


def _fixed(
    step_name: str,
    position: int,
    names: Mapping[str, Sequence[str]],
    owner: list[str],
    taken: list[str],
) -> list[str]:
    """Give the created columns their names fixed at learn, refusing a clash."""
    counts = {c: owner.count(c) for c in dict.fromkeys([*owner, *names])}
    for c, count in counts.items():
        if count != len(names.get(c, ())):
            msg = (
                f"{step_name} (step {position}) creates {count} columns from "
                f"{c!r} now, but {len(names.get(c, ()))} when it learned; "
                "apply must create the same columns from the same learned "
                "values. Fix: make the step's apply depend only on what it "
                "learned."
            )
            raise StepError(msg, step=step_name, position=position)
    given = {c: iter(names[c]) for c in counts}
    final = [next(given[c]) for c in owner]
    made = {n.lower(): n for n in final}
    for t in taken:
        if t.lower() in made:
            msg = (
                f"{step_name} (step {position}) creates the column "
                f"{made[t.lower()]!r}, named when it learned, but the data "
                f"reaching it also has a column {t!r} (DuckDB names ignore "
                "case). The names a step learned do not change at apply, so "
                f"the two would clash. Fix: rename or drop {t!r} before "
                "apply, or learn the pipeline again on this data."
            )
            raise StepError(msg, step=step_name, position=position)
    return final


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


_OPEN = "([{"
_CLOSE = ")]}"


@dataclass(frozen=True)
class _Marker:
    """One staged marker found in a learned value's SQL text.

    `start` and `end` delimit the whole call in the text; `args` are its
    arguments' texts, split at the commas outside any bracket or quote.
    """

    kind: str
    start: int
    end: int
    args: tuple[str, ...]


def _scan(text: str, start: int) -> tuple[int, list[str]]:
    """Read a call's arguments from the ``(`` at `start` to its matching ``)``.

    Returns the index after the ``)`` and the arguments' texts, or ``-1``
    when the brackets do not close. Brackets inside quotes do not count; a
    doubled quote inside a literal closes and reopens it, still inside.
    """
    depth = 0
    quoted: str | None = None
    args: list[str] = []
    begin = start + 1
    for i in range(start, len(text)):
        ch = text[i]
        if quoted is not None:
            if ch == quoted:
                quoted = None
        elif ch in "'\"":
            quoted = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                args.append(text[begin:i].strip())
                return i + 1, args
        elif ch == "," and depth == 1:
            args.append(text[begin:i].strip())
            begin = i + 1
    return -1, args


def _markers(text: str) -> list[_Marker]:
    """Find every staged marker (a quantile or a mode) in `text`, in order.

    A marker's name is matched only outside quotes and not as the end of a
    longer name, so a column named after one is not taken for it.
    """
    found: list[_Marker] = []
    quoted: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quoted is not None:
            if ch == quoted:
                quoted = None
            i += 1
            continue
        if ch in "'\"":
            quoted = ch
            i += 1
            continue
        kind = next(
            (k for k in (QUANTILE, MODE) if text.startswith(f"{k}(", i)),
            None,
        )
        if kind is not None and (
            i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")
        ):
            end, args = _scan(text, i + len(kind))
            if end < 0:
                break
            found.append(_Marker(kind, i, end, tuple(args)))
            i = end
            continue
        i += 1
    return found


def _refuse(stage: Stage, text: str, why: str, fix: str) -> StepError:
    msg = f"{stage.step} (step {stage.position}) learns {text}, {why} Fix: {fix}"
    return StepError(msg, step=stage.step, position=stage.position)


@dataclass
class _Staged:
    """The staged aggregates of one learn stage, and how to reference them.

    `quantiles` maps ``(values, q, method)`` (SQL texts; `values` is the
    expression sorted) to the column of the quantile stage holding it;
    `modes` maps the expression counted to the mode stage holding its mode.
    """

    name: str
    quantiles: dict[tuple[str, str, str], str] = field(default_factory=dict)
    modes: dict[str, str] = field(default_factory=dict)

    def reference(self, stage: Stage, text: str, marker: _Marker) -> str:
        """Return the scalar subquery standing for `marker` in `text`."""
        whole = text[marker.start : marker.end]
        for arg in marker.args:
            if _markers(arg):
                raise _refuse(
                    stage,
                    whole,
                    "an aggregate of an aggregate (a quantile or mode of "
                    "one), which has no meaning over one column.",
                    "learn each aggregate of the column on its own.",
                )
        if marker.kind == MODE and len(marker.args) == 1:
            (values,) = marker.args
            table = self.modes.setdefault(values, f"{self.name}_mode{len(self.modes)}")
            return f"(SELECT {quote('m')} FROM {quote(table)})"
        method = marker.args[-1] if len(marker.args) == 3 else ""
        if marker.kind == QUANTILE and method in (
            "'linear'",
            "'averaged_inverted_cdf'",
        ):
            values, q, _ = marker.args
            key = (values, q, method.strip("'"))
            column = self.quantiles.setdefault(key, f"q{len(self.quantiles)}")
            return f"(SELECT {quote(column)} FROM {quote(self.name + '_quantile')})"
        raise _refuse(
            stage,
            whole,
            "a marker sq.agg did not build.",
            "build quantiles and modes with sq.agg, such as sq.agg.median(x).",
        )


def _ranks(method: str, q: str) -> tuple[str, str, str]:
    """Return the SQL of the low rank, high rank and weight of a quantile.

    In terms of ``n``, the number of present values, ranked from 1 in
    ascending order. The quantile is ``low + weight * (high - low)``, or the
    low value alone when the weight is 0, so no difference is formed for
    nothing. The positions are computed in DOUBLE as numpy computes them,
    so a position numpy finds whole is whole here too.
    """
    n = quote("n")
    if method == "linear":
        # numpy's virtual index (n - 1) * q, counted from 0; ranks from 1.
        index = f"(({n} - 1) * {q})"
        low = f"(floor({index}) + 1)"
        return low, f"least({low} + 1, {n})", f"({index} - floor({index}))"
    # averaged_inverted_cdf: g = n * q; a whole g averages ranks g and g + 1,
    # else rank ceil(g); each rank held within [1, n].
    g = f"({n} * {q})"
    whole = f"({g} = floor({g}))"
    low = f"greatest(least(ceil({g}), {n}), 1)"
    high = f"CASE WHEN {whole} THEN greatest(least({g} + 1, {n}), 1) ELSE {low} END"
    return low, high, f"CASE WHEN {whole} THEN 0.5 ELSE 0.0 END"


def _quantile_ctes(
    name: str, quantiles: dict[tuple[str, str, str], str], previous: str
) -> list[str]:
    """Return the stages computing a learn stage's quantiles, as one row.

    Every quantile of the stage is computed in one sort: the present values
    of each expression sorted, tagged with the expression's number, numbered
    in order of tag, then value, by one window over all of them (no
    partitions), which spills to disk. Each tag's values then hold the
    positions after those of the tags before it, so the one or two values a
    quantile needs are found from the counts per tag. Several quantiles of
    one expression (an IQR and a median) share its tag.

    One sort, not one per column: two sorts running in one statement hold
    memory together, and do not fit where one does. Nor one partition per
    column: a window over partitions needed more memory. DuckDB's sort itself
    keeps a little memory per row, so this reaches as far as its ``ORDER BY``
    does: under 64 MB, 20 million rows of two columns, not 60 million.
    """
    values, counts, picked = (
        quote(f"{name}_quantile_{part}") for part in ("values", "counts", "picked")
    )
    t, x, r, n, start, k = (quote(c) for c in ("t", "x", "r", "n", "start", "k"))
    tags: dict[str, int] = {}
    for inner, _, _ in quantiles:
        tags.setdefault(inner, len(tags))
    tagged = " UNION ALL ".join(
        f"SELECT {tag} AS {t}, CAST({inner} AS DOUBLE) AS {x} FROM {quote(previous)}"
        for inner, tag in tags.items()
    )
    wanted: list[str] = []
    weights: list[str] = []
    finals: list[str] = []
    for (inner, q, method), column in quantiles.items():
        tag = tags[inner]
        low, high, weight = _ranks(method, q)
        wanted.append(f"({t} = {tag} AND {k} IN ({low}, {high}))")
        lo, hi, w = (quote(f"{column}_{part}") for part in ("lo", "hi", "w"))
        weights += [
            f"max({x}) FILTER (WHERE {t} = {tag} AND {k} = {low}) AS {lo}",
            f"max({x}) FILTER (WHERE {t} = {tag} AND {k} = {high}) AS {hi}",
            f"max({weight}) FILTER (WHERE {t} = {tag}) AS {w}",
        ]
        finals.append(
            f"CASE WHEN {w} = 0 THEN {lo} ELSE {lo} + {w} * ({hi} - {lo}) END "
            f"AS {quote(column)}"
        )
    return [
        f"{values} AS (SELECT {t}, {x} FROM ({tagged}) "
        f"WHERE {x} IS NOT NULL AND NOT isnan({x}))",
        f"{counts} AS (SELECT {t}, {n}, sum({n}) OVER (ORDER BY {t}) - {n} AS {start} "
        f"FROM (SELECT {t}, count(*) AS {n} FROM {values} GROUP BY {t}))",
        f"{picked} AS (SELECT {t}, {x}, {k}, {n} FROM "
        f"(SELECT {t}, {x}, {r} - {start} AS {k}, {n} "
        f"FROM (SELECT {t}, {x}, row_number() OVER (ORDER BY {t}, {x}) AS {r} "
        f"FROM {values}) JOIN {counts} USING ({t})) WHERE {' OR '.join(wanted)})",
        f"{quote(name + '_quantile')} AS MATERIALIZED (SELECT {', '.join(finals)} "
        f"FROM (SELECT {', '.join(weights)} FROM {picked}))",
    ]


def _mode_ctes(table: str, inner: str, previous: str) -> list[str]:
    """Return the stages computing one mode: count each value, keep the most.

    The count is a ``GROUP BY``, which spills to disk; of the values counted
    most often, the smallest is kept. NULL when there is no value.
    """
    counts = quote(f"{table}_counts")
    x, c, m = (quote(v) for v in ("x", "c", "m"))
    return [
        f"{counts} AS MATERIALIZED (SELECT {x}, count(*) AS {c} FROM "
        f"(SELECT {inner} AS {x} FROM {quote(previous)}) "
        f"WHERE {x} IS NOT NULL GROUP BY {x})",
        f"{quote(table)} AS MATERIALIZED (SELECT min({x}) AS {m} FROM {counts} "
        f"WHERE {c} = (SELECT max({c}) FROM {counts}))",
    ]


def _learn_ctes(stage: Stage, learn: dict[str, Expression], previous: str) -> list[str]:
    """Return a learn stage, after the stages of the quantiles and modes it learns.

    Each staged marker in a learned value is replaced by a scalar subquery
    reading the one row its stages computed, so a quantile may sit anywhere
    in a learned value (``iqr`` is one quantile less another).
    """
    staged = _Staged(stage.learn_name)
    items: list[str] = []
    for key, expression in learn.items():
        text = str(expression)
        pieces: list[str] = []
        last = 0
        for marker in _markers(text):
            pieces += [text[last : marker.start], staged.reference(stage, text, marker)]
            last = marker.end
        pieces.append(text[last:])
        items.append(f"{''.join(pieces)} AS {quote(key)}")
    ctes: list[str] = []
    if staged.quantiles:
        ctes.extend(_quantile_ctes(staged.name, staged.quantiles, previous))
    for inner, table in staged.modes.items():
        ctes.extend(_mode_ctes(table, inner, previous))
    # MATERIALIZED, never NOT MATERIALIZED: the one row is computed once.
    # The row count beside the values tells "no rows" from NULL values.
    select = (
        f"SELECT {', '.join([*items, f'count(*) AS {quote(_ROWS)}'])} "
        f"FROM {quote(previous)}"
    )
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
    ...         return {"mean": sq.agg.mean(x)}
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
