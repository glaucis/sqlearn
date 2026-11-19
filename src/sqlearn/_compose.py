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
them. A mode (`sqlearn.agg.mode`, a marker too) is counted in a ``GROUP BY``;
a learn stage's modes share one stage. A marker may sit anywhere in a
learned value: it is replaced by ``any_value`` of a column of its stage's one
row, cross-joined into the learn stage's scan, so a quantile comes back like
any other learned value. A learned value that is one whole marker is read
beside the scan's one row instead, so no row of the scan carries it. The
target's statistics (`sqlearn._expr.target_stats`, a step learning from the
target) are grouped by inner fold and category in a ``GROUP BY`` stage, and
come back as one list.

While learning and training, columns no step sees travel beside the data
(``aside``): the target, under `TARGET`, and each row's inner fold for a
step learning from the target (`inner_name`), computed once from the row's
position in the data as read (`POSITION`, `inner_fold`). They pass through
every stage untouched.
"""

import datetime
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache, partial
from typing import cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn._errors import InternalError, SqlearnError, StepError
from sqlearn._expr import MODE, QUANTILE, STD, TARGET_STATS, VAR, const, quote
from sqlearn._names import name_columns
from sqlearn._selectors import Schema
from sqlearn._step import (
    Learned,
    Output,
    Step,
    apply_rows,
    cross_fitted,
    output_labels,
    row_owners,
)

__all__ = [
    "POSITION",
    "SOURCE",
    "TARGET",
    "Run",
    "Stage",
    "apply_sql",
    "build",
    "copy_sql",
    "describe",
    "execute",
    "inner_fold",
    "inner_name",
    "number_rows",
    "stage_name",
    "step_stage",
]

SOURCE = "source"
"""The name of the first stage, which holds the data a run reads."""

_ROWS = "n"
"""The column of a learn stage counting the rows it learned from."""

TARGET = "__sqlearn_target"
"""The name the target travels under beside the data, seen by no step."""

POSITION = "__sqlearn_position"
"""The column numbering the rows as read, from which inner folds are dealt."""

Values = dict[str, dict[str, object]]
"""What one step learned: learned name, then column, to value (as the store)."""


def inner_name(cv: int, seed: int) -> str:
    """Name the column holding each row's inner fold, for a step's settings.

    Parameters
    ----------
    cv : int
        The number of inner folds.
    seed : int
        The seed mixed into the hash.

    Returns
    -------
    str
        ``__sqlearn_inner_<cv>_<seed>``.

    Examples
    --------
    >>> from sqlearn._compose import inner_name
    >>> inner_name(5, 0)
    '__sqlearn_inner_5_0'
    """
    return f"__sqlearn_inner_{cv}_{seed}"


def inner_fold(position: str, cv: int, seed: int) -> Expression:
    """Return a row's inner fold, dealt by its position: ``KFold(cv, seed)``'s.

    ``hash(row(<position>), seed) % cv``: the fold `sq.folds.kfold` deals a
    row into over a relation of the position alone (its expression,
    ``hash(<alias>, seed) % n``, hashes a row as the struct of its values).
    The position is the row's number in the data as read, so every row gets
    its own fold, rows alike included, as scikit-learn's ``KFold`` deals
    them by place.

    Parameters
    ----------
    position : str
        The column numbering the rows (`POSITION`), from 1.
    cv : int
        The number of inner folds.
    seed : int
        The seed.

    Returns
    -------
    duckdb.Expression
        The fold, from 0 to ``cv - 1``.

    Examples
    --------
    >>> from sqlearn._compose import inner_fold
    >>> str(inner_fold("p", 5, 0))
    '(hash("row"("p"), 0) % 5)'
    """
    row = duckdb.FunctionExpression("row", duckdb.ColumnExpression(position))
    return duckdb.FunctionExpression("hash", row, const(seed)) % const(cv)


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
    row : dict of str to duckdb.Expression
        Internal name to a value a whole-row step computes once per row
        (`Step.row_values`), in a projection named `row_name` before the
        data stage, which reads it under the name of the stage before.

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
    row: dict[str, Expression] = field(default_factory=dict)

    @property
    def row_name(self) -> str:
        """The row-values projection's name: the data stage's, with ``r``.

        Returns
        -------
        str
            ``r03_normalize`` for the data stage ``s03_normalize``.

        Examples
        --------
        >>> from sqlearn._compose import Stage
        >>> Stage("s03_normalize", {}).row_name
        'r03_normalize'
        """
        return "r" + self.name[1:]

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
    aside: Sequence[str] = (),
    folds: Mapping[str, Mapping[str, Mapping[str, object]]] | None = None,
    held: Expression | None = None,
) -> Stage:
    """Build a step's stage from its `learn` and `apply`.

    Without `values`, the step learns in this run: its aggregates form the
    learn stage, and `apply` reads them through placeholders. With `values`,
    they are constants and there is no learn stage. Columns are referenced
    qualified by `previous`, so no column can be confused with a learned
    value. The created columns are named from their labels by
    `sqlearn._names.name_columns`: a clash is numbered, never refused. A
    whole-row step (``rowwise``) has its `apply_row` called once with every
    selected column, and its outputs take the places of those columns. With
    `names`, the names fixed when the step learned are used instead, so they
    do not change with the data applied to.

    A step learning from the target (``uses_target``) learns from the target
    as `TARGET`, beside the data. Given `folds` too (what it learned on each
    inner fold's complement), its output is cross-fitted: each row takes
    `apply` with the values of its own inner fold (``CASE <fold> WHEN k ...``,
    the fold read from its `inner_name` column), but a row `held` holds out
    takes the values learned on all rows.

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
    aside : sequence of str, default ()
        Columns of the stage before that are not in `schema` and pass
        through, last, untouched: the target and the inner folds.
    folds : mapping, optional
        For a step learning from the target, with `values`: per inner fold
        (``"0"``, ``"1"``, ...), what it learned on the rows outside it.
    held : duckdb.Expression, optional
        With `folds`: true for the rows encoded with `values` (a search's
        held-out rows) instead of their inner fold's.

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
    target = duckdb.ColumnExpression(previous, TARGET)
    for c in chosen:
        if values is not None and cross_fitted(step):
            # What it learned is derived from its aggregates, under other names.
            per_column[c] = Learned.values(_derived(name, c, values))
            continue
        # A target step's learn also takes the target (`Step.uses_target`).
        learn_from = cast("Callable[..., Mapping[str, Expression]]", step.learn)
        aggregates = (
            learn_from(exprs[c], target) if step.uses_target else learn_from(exprs[c])
        )
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
    row: dict[str, Expression] = {}
    rows = (
        _row_outputs(step, step_name, exprs, per_column, previous, row)
        if applies
        else {}
    )
    for c, _ in schema:
        if c not in per_column or not applies:
            out.append((c, exprs[c]))
            continue
        if step.keep:
            out.append((c, exprs[c]))
        if step.rowwise:
            pairs = rows.get(c, [])
        else:
            result: Output
            if folds is not None and cross_fitted(step):
                result = _cross_fitted(
                    step, step_name, position, exprs[c], per_column[c],
                    {k: Learned.values(_derived(name, c, v)) for k, v in folds.items()},
                    duckdb.ColumnExpression(previous, _inner(step)), held,
                )  # fmt: skip
            else:
                result = step.apply(exprs[c], per_column[c])
            if isinstance(result, Expression) and not step.keep:
                # One expression replacing the column keeps its name, as the
                # planner plans it: a column passing through is never renamed.
                out.append((c, result))
                continue
            full = not step.names_are_labels and not isinstance(result, Expression)
            pairs = [
                ((label, "") if full else (c, label), e)
                for label, e in output_labels(step_name, result, step.keep, step.suffix)
            ]
        for wanted, e in pairs:
            out.append((wanted, e))
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
    if not outputs and per_column:
        # A dynamic step keeping none of its columns, with none beside them.
        msg = (
            f"{step_name} (step {position}) leaves no column: it keeps none "
            "of the columns it chose, and no other column passes beside "
            "them. Why: a table needs a column, and a model a feature. Fix: "
            "keep one at least (for a feature selector, a larger k or "
            "percentile), or let a column it does not choose pass beside it."
        )
        raise StepError(msg, step=step_name, position=position)
    outputs.update({a: duckdb.ColumnExpression(previous, a) for a in aside})

    remake = partial(step_stage, position, step_name, step, schema, previous)
    return Stage(
        name=name,
        columns=outputs,
        learn=learn or None,
        reads=[learn_name] if learn and applies else [],
        learned=learned,
        remake=partial(
            remake, applies=applies, columns=chosen, names=names, aside=aside
        )
        if learn
        else None,
        step=step_name,
        position=position,
        created=created,
        row=row,
    )


def _row_outputs(
    step: Step,
    step_name: str,
    exprs: Mapping[str, Expression],
    per_column: Mapping[str, Learned],
    previous: str,
    row: dict[str, Expression],
) -> dict[str, list[tuple[tuple[str, str], Expression]]]:
    """Call a whole-row step's `apply_row`; place each output by its owner.

    The step's row values go into `row` under internal names no column
    reaching the step has, and `apply_row` reads them as columns of
    `previous` (the row projection is read under that name). An output named
    after a selected column belongs to it; any other to the last selected
    column. Each is planned as ``(name, label)``: the label is ``""``, or the
    suffix (or step name) with `keep` when names are labels.
    """
    if not step.rowwise or not per_column:
        return {}
    xs = {c: exprs[c] for c in per_column}
    used = {c.lower() for c in exprs}
    internal: list[str] = []

    def refer(i: int, _: str) -> Expression:
        name = f"__row_{i}"
        while name.lower() in used:
            name = f"_{name}"
        used.add(name.lower())
        internal.append(name)
        return duckdb.ColumnExpression(previous, name)

    values, result = apply_rows(step, xs, per_column, refer)
    row.update(zip(internal, values.values(), strict=True))
    label = (step.suffix or step_name) if step.keep and step.names_are_labels else ""
    owners = row_owners(list(per_column), [key for key, _ in result])
    placed: dict[str, list[tuple[tuple[str, str], Expression]]] = {}
    for owner, (key, e) in zip(owners, result, strict=True):
        placed.setdefault(owner, []).append(((key, label), e))
    return placed


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


def _inner(step: Step) -> str:
    """Name the inner-fold column of a step learning from the target."""
    return inner_name(getattr(step, "cv"), getattr(step, "seed"))  # noqa: B009


def _cross_fitted(
    step: Step,
    step_name: str,
    position: int,
    x: Expression,
    everything: Learned,
    per_fold: Mapping[str, Learned],
    fold: Expression,
    held: Expression | None,
) -> Expression:
    """Return a target step's output with each row's own inner fold's values.

    ``CASE WHEN <fold> = 0 THEN apply(x, learned_0) ... END``, inside
    ``CASE WHEN <held> THEN apply(x, everything) ELSE ... END`` when some
    rows (a search's held-out rows) take the values learned on all rows.
    """

    def one(learned: Learned) -> Expression:
        result = step.apply(x, learned)
        if not isinstance(result, Expression):
            msg = (
                f"{step_name} (step {position}) is cross-fitted, so its apply "
                "must return one expression per column, but it returned "
                f"{type(result).__name__}. Fix: return one expression."
            )
            raise StepError(msg, step=step_name, position=position)
        return result

    keys = sorted(per_fold, key=int)
    case = duckdb.CaseExpression(fold == const(int(keys[0])), one(per_fold[keys[0]]))
    for key in keys[1:]:
        case = case.when(fold == const(int(key)), one(per_fold[key]))
    if held is None:
        return case
    return duckdb.CaseExpression(held, one(everything)).otherwise(case)


def _derived(
    stage: str, column: str, values: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    """Pick one column's derived values, refusing a column with none."""
    mine = {k: v[column] for k, v in values.items() if column in v}
    if not mine:
        msg = (
            f"stage {stage!r} has no learned value for column {column!r}; the "
            "values do not match what the step learned."
        )
        raise SqlearnError(msg)
    return mine


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
    if stage.row:
        return f"SELECT {_items(stage.columns)} FROM (SELECT *, {_items(stage.row)})"
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


_TOKEN = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|[()\[\]{},]""")
"""A quoted literal or identifier (doubled quotes inside), a bracket or a comma."""

_MARKER = re.compile(
    r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|(?<![A-Za-z0-9_])("""
    + "|".join(re.escape(k) for k in (QUANTILE, MODE, STD, VAR, TARGET_STATS))
    + r")\("
)
"""A quoted literal or identifier, or a marker's name and its ``(``."""


def _scan(text: str, start: int) -> tuple[int, list[str]]:
    """Read a call's arguments from the ``(`` at `start` to its matching ``)``.

    Returns the index after the ``)`` and the arguments' texts, or ``-1``
    when the brackets do not close. Brackets inside quotes do not count; a
    doubled quote inside a literal closes and reopens it, still inside. The
    text is read once, by a regular expression jumping from token to token.
    """
    depth = 0
    args: list[str] = []
    begin = start + 1
    for token in _TOKEN.finditer(text, start):
        ch = token.group()
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                args.append(text[begin : token.start()].strip())
                return token.end(), args
        elif ch == "," and depth == 1:
            args.append(text[begin : token.start()].strip())
            begin = token.end()
    return -1, args


def _markers(text: str) -> list[_Marker]:
    """Find every staged marker (quantile, mode, std, target statistics), in order.

    A marker's name is matched only outside quotes and not as the end of a
    longer name, so a column named after one is not taken for it. The text
    is read once from start to end: the search resumes after each marker.
    """
    found: list[_Marker] = []
    i = 0
    while (match := _MARKER.search(text, i)) is not None:
        kind = match.group(1)
        if kind is None:  # a quoted literal or identifier: skip it whole
            i = match.end()
            continue
        end, args = _scan(text, match.end() - 1)
        if end < 0:
            break
        found.append(_Marker(kind, match.start(), end, tuple(args)))
        i = end
    return found


_CALL = re.compile(
    r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|([A-Za-z_][A-Za-z0-9_]*)\s*\(|[()]"""
)
"""A quoted literal or identifier, a function's name and its ``(``, or a bracket."""


@cache
def _aggregate_names() -> frozenset[str]:
    """Return the names of DuckDB's aggregate functions, lower case.

    ``filter`` is not among them: as a function it is DuckDB's scalar
    ``list_filter``, and an aggregate's ``FILTER (WHERE ...)`` clause is
    read with that aggregate (`_calls`).
    """
    rows = duckdb.connect().sql(
        "SELECT DISTINCT lower(function_name) FROM duckdb_functions() "
        "WHERE function_type = 'aggregate'"
    )
    return frozenset(str(name) for (name,) in rows.fetchall()) - {"filter"}


def _in_aggregates(text: str) -> list[tuple[int, int]]:
    """Return the spans of `text` inside an aggregate call's brackets.

    The text is read once; an aggregate call inside another adds no span of
    its own.
    """
    names = _aggregate_names()
    spans: list[tuple[int, int]] = []
    opened: list[bool] = []  # per open bracket: does it open an aggregate?
    start = 0
    for token in _CALL.finditer(text):
        piece = token.group()
        if piece[0] in "'\"":
            continue
        name = token.group(1)
        if name is not None or piece == "(":
            aggregate = name is not None and name.lower() in names
            if aggregate and not any(opened):
                start = token.end()
            opened.append(aggregate)
        elif opened:
            if opened.pop() and not any(opened):
                spans.append((start, token.start()))
    return spans


def _refuse(stage: Stage, text: str, why: str, fix: str) -> StepError:
    msg = f"{stage.step} (step {stage.position}) learns {text}, {why} Fix: {fix}"
    return StepError(msg, step=stage.step, position=stage.position)


def _refuse_plain_aggregate(stage: Stage, whole: str, values: str) -> None:
    """Refuse `values` (a staged marker's argument) holding a plain aggregate.

    The marker's stage reads its argument per row of the stage's input,
    where one value of a whole column (``mean(x)``) has no row.
    """
    if _in_aggregates(values):
        raise _refuse(
            stage,
            whole,
            "a plain aggregate inside a staged one, which is computed per "
            "row of the stage's input, where one value of a whole column "
            "has no row.",
            "learn the aggregates side by side (such as median(x) - mean(x)), "
            "or compute the inner aggregate in an earlier step.",
        )


def _read(column: str, nested: bool) -> str:
    """Read a one-row stage's column: plain inside an aggregate, else any_value."""
    return column if nested else f"any_value({column})"


@dataclass
class _Staged:
    """The staged aggregates of one learn stage, and how to reference them.

    `quantiles` maps ``(values, q, method)`` (SQL texts; `values` is the
    expression sorted) to its place (from 0) in the quantile stage's list;
    `modes` maps the expression counted to its column (``m0``, ``m1``, ...)
    of the mode stage; `stds` maps the expression whose standard deviation
    or variance is learned to its column (``v0``, ...) of the variance stage
    (the standard deviation reads its root);
    `stats` maps ``(x, y, fold)`` to its column (``l0``, ...) of the target
    statistics stage. `std_reads` names the one-row stages the standard
    deviations' expressions read.
    """

    name: str
    quantiles: dict[tuple[str, str, str], int] = field(default_factory=dict)
    modes: dict[str, int] = field(default_factory=dict)
    stds: dict[str, int] = field(default_factory=dict)
    stats: dict[tuple[str, str, str], int] = field(default_factory=dict)
    std_reads: set[str] = field(default_factory=set)

    def table(self, marker: _Marker) -> str:
        """Return the name of the one-row stage `marker` reads."""
        suffix = {
            QUANTILE: "_quantile",
            MODE: "_modes",
            STD: "_std",
            VAR: "_std",
            TARGET_STATS: "_stats",
        }[marker.kind]
        return self.name + suffix

    def reference(
        self, stage: Stage, text: str, marker: _Marker, *, nested: bool
    ) -> str:
        """Return the expression standing for `marker` in `text`.

        It reads the one row the marker's stage computed, beside the scan in
        the learn stage's outer select. Inside another aggregate (`nested`)
        it is a plain column of that row, read per row as the aggregate's
        argument; else ``any_value`` of it, as a bare column beside
        aggregates must be (one value, computed once per stage, as DuckDB
        folds equal aggregates into one).
        """
        whole = text[marker.start : marker.end]
        if marker.kind in (STD, VAR) and len(marker.args) == 1:
            return self._std(stage, whole, marker, nested=nested)
        # The planner has placed every aggregate inside in a level below;
        # what is left is a window function, read per row as today.
        for arg in marker.args:
            _refuse_plain_aggregate(stage, whole, arg)
        if marker.kind == TARGET_STATS and len(marker.args) == 3:
            x, y, fold = marker.args
            index = self.stats.setdefault((x, y, fold), len(self.stats))
            return _read(f"{quote(self.name + '_stats')}.{quote(f'l{index}')}", nested)
        if marker.kind == MODE and len(marker.args) == 1:
            (values,) = marker.args
            index = self.modes.setdefault(values, len(self.modes))
            return _read(f"{quote(self.name + '_modes')}.{quote(f'm{index}')}", nested)
        method = marker.args[-1] if len(marker.args) == 3 else ""
        if marker.kind == QUANTILE and method in (
            "'linear'",
            "'averaged_inverted_cdf'",
        ):
            values, q, _ = marker.args
            key = (values, q, method.strip("'"))
            index = self.quantiles.setdefault(key, len(self.quantiles))
            table = quote(self.name + "_quantile")
            column = f"{table}.{quote('qs')}"
            return f"{_read(column, nested)}[{index + 1}]"
        raise _refuse(
            stage,
            whole,
            "a marker sq.agg did not build.",
            "build quantiles and modes with sq.agg, such as sq.agg.median(x).",
        )

    def _std(self, stage: Stage, whole: str, marker: _Marker, *, nested: bool) -> str:
        """Return the expression standing for the std or variance in `marker`.

        The planner has replaced the aggregates inside `values` by plain
        columns of the levels below (ADR 0051), which the passes cross-join;
        a staged marker still found here is one the planner did not reach
        and is read from this stage's own one-row stages, which come before
        the passes. A variance is the stage's column; a standard deviation
        its square root.
        """
        values = marker.args[0]
        pieces: list[str] = []
        last = 0
        for inner in _markers(values):
            pieces += [
                values[last : inner.start],
                self.reference(stage, values, inner, nested=True),
            ]
            self.std_reads.add(self.table(inner))
            last = inner.end
        pieces.append(values[last:])
        _refuse_plain_aggregate(stage, whole, "".join(pieces))
        index = self.stds.setdefault("".join(pieces), len(self.stds))
        column = _read(f"{quote(self.name + '_std')}.{quote(f'v{index}')}", nested)
        return f"sqrt({column})" if marker.kind == STD else column


def _ranks(n: str, q: str, m: str) -> tuple[str, str, str]:
    """Return the SQL of the low rank, high rank and weight of a quantile.

    In terms of the SQL of `n` (the number of present values, ranked from 1
    in ascending order), `q` and `m` (the method: 0 for linear, 1 for
    averaged_inverted_cdf). The positions are computed in DOUBLE as numpy
    computes them, so a position numpy finds whole is whole here too.
    """
    # linear: numpy's virtual index (n - 1) * q, counted from 0; ranks from 1.
    index = f"(({n} - 1) * {q})"
    linear_low = f"(floor({index}) + 1)"
    linear_high = f"least({linear_low} + 1, {n})"
    linear_weight = f"({index} - floor({index}))"
    # averaged_inverted_cdf: g = n * q; a whole g averages ranks g and g + 1,
    # else rank ceil(g); each rank held within [1, n].
    g = f"({n} * {q})"
    whole = f"({g} = floor({g}))"
    cdf_low = f"greatest(least(ceil({g}), {n}), 1)"
    cdf_high = (
        f"CASE WHEN {whole} THEN greatest(least({g} + 1, {n}), 1) ELSE {cdf_low} END"
    )
    cdf_weight = f"CASE WHEN {whole} THEN 0.5 ELSE 0.0 END"

    def either(linear: str, cdf: str) -> str:
        return f"CASE WHEN {m} = 0 THEN {linear} ELSE {cdf} END"

    return (
        either(linear_low, cdf_low),
        either(linear_high, cdf_high),
        either(linear_weight, cdf_weight),
    )


_METHOD_CODES = {"linear": 0, "averaged_inverted_cdf": 1}


def _quantile_ctes(
    name: str,
    quantiles: dict[tuple[str, str, str], int],
    previous: str,
    rows: Sequence[str] = (),
) -> list[str]:
    """Return the stages computing a learn stage's quantiles, as one list.

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

    The SQL grows linearly with the number of quantiles, which are data, not
    expressions: the quantiles asked for are one constant list per tag
    (number, q, method), turned into ranks beside the counts; each sorted row
    keeps the quantiles it is a rank of, and the result is one list, in the
    quantiles' order. Nothing but the join to the counts (as the core had)
    and one aggregate reads the sorted rows. A column and a filter per
    quantile made DuckDB's planning grow faster than the number of quantiles
    (seconds for 50 columns). The values stay one ``UNION ALL`` branch per
    expression sorted: unnesting each row's values instead, which reads the
    previous stage once, ran out of memory under 64 MB where the branches
    spill.

    `rows` are the one-row stages of the levels below (ADR 0051) that the
    expressions sorted read; they are cross-joined into the read of the
    previous stage.
    """
    joins = "".join(f" CROSS JOIN {quote(r)}" for r in rows)
    values, counts = (quote(f"{name}_quantile_{part}") for part in ("values", "counts"))
    t, x, r, n, start, k = (quote(c) for c in ("t", "x", "r", "n", "start", "k"))
    i, q, m, lo, hi, w = (quote(c) for c in ("i", "q", "m", "lo", "hi", "w"))
    g, u, f = quote("g"), quote("u"), quote("f")
    tags: dict[str, int] = {}
    for inner, _, _ in quantiles:
        tags.setdefault(inner, len(tags))
    tagged = " UNION ALL ".join(
        f"SELECT {tag} AS {t}, CAST({inner} AS DOUBLE) AS {x} FROM {quote(previous)}"
        f"{joins}"
        for inner, tag in tags.items()
    )
    # The quantiles asked for, as one constant: per tag, a list of
    # (number, q, method). Each tag's counts turn its list into ranks.
    per_tag: list[list[str]] = [[] for _ in tags]
    for (inner, qq, method), index in quantiles.items():
        per_tag[tags[inner]].append(
            f"{{'i': {index}, 'q': CAST({qq} AS DOUBLE), 'm': {_METHOD_CODES[method]}}}"
        )
    asked = "[" + ", ".join("[" + ", ".join(one) + "]" for one in per_tag) + "]"
    low, high, weight = _ranks(n, f"s.{q}", f"s.{m}")
    ranked = (
        f"list_transform({asked}[{t} + 1], lambda s: {{'i': s.{i}, "
        f"'lo': CAST({low} AS BIGINT), 'hi': CAST({high} AS BIGINT), "
        f"'w': {weight}}})"
    )
    # Each sorted row is joined to its tag's counts and ranks (the small side,
    # as at the core) and keeps the quantiles it is a rank of; the rows kept
    # stream into one aggregate, and the quantiles are found from that one
    # list. No other join, group or stage reads the sorted rows: each one
    # added made DuckDB set memory aside beside the sort, and two chained
    # quantile stages then failed under 64 MB where the core's spilled.
    pick = f"list_filter({g}, lambda s: s.{lo} = {k} OR s.{hi} = {k})"

    def of(field: str) -> str:
        """Return the low or high entry (`field`) of quantile ``j``; NULL if none."""
        return f"list_filter({f}, lambda e: e.{i} = j AND e.{field})[1]"

    lo_x, hi_x = f"{of(quote('a'))}.{x}", f"{of(quote('b'))}.{x}"
    weight_j = f"coalesce({of(quote('a'))}.{w}, {of(quote('b'))}.{w})"
    value = (
        f"CASE WHEN {weight_j} = 0 THEN {lo_x} WHEN {weight_j} >= 0.5 "
        f"THEN {hi_x} - ({hi_x} - {lo_x}) * (1 - {weight_j}) "
        f"ELSE {lo_x} + ({hi_x} - {lo_x}) * {weight_j} END"
    )
    return [
        f"{values} AS (SELECT {t}, {x} FROM ({tagged}) "
        f"WHERE {x} IS NOT NULL AND NOT isnan({x}))",
        f"{counts} AS (SELECT {t}, "
        f"CAST(sum({n}) OVER (ORDER BY {t}) - {n} AS BIGINT) AS {start}, "
        f"{ranked} AS {g} "
        f"FROM (SELECT {t}, count(*) AS {n} FROM {values} GROUP BY {t}))",
        f"{quote(name + '_quantile')} AS MATERIALIZED (SELECT "
        f"list_transform(range({len(quantiles)}), lambda j: {value}) "
        f"AS {quote('qs')} FROM (SELECT list({{'i': {u}.{i}, "
        f"'a': {k} = {u}.{lo}, 'b': {k} = {u}.{hi}, 'w': {u}.{w}, 'x': {x}}}) "
        f"AS {f} FROM (SELECT {k}, {x}, unnest({pick}) AS {u} FROM "
        f"(SELECT {x}, {r} - {start} AS {k}, {g} "
        f"FROM (SELECT {t}, {x}, row_number() OVER (ORDER BY {t}, {x}) AS {r} "
        f"FROM {values}) JOIN {counts} USING ({t})))))",
    ]


def _one_row(table: str, branches: list[tuple[str, str]]) -> str:
    """Return one stage holding one row: each branch's one value as a column.

    Each branch is ``(column, select)``, a select of one row and one column.
    They are stacked with ``UNION ALL BY NAME``, each column NULL outside its
    own branch, and read back with ``any_value``: the SQL grows linearly with
    the branches, the stage is one, and each column keeps its own type. A
    stage per branch, cross-joined, made DuckDB's planning grow faster than
    the number of stages (4 s for 200 modes).
    """
    stacked = " UNION ALL BY NAME ".join(select for _, select in branches)
    picks = ", ".join(
        f"any_value({quote(column)}) AS {quote(column)}" for column, _ in branches
    )
    return f"{quote(table)} AS MATERIALIZED (SELECT {picks} FROM ({stacked}))"


def _mode_ctes(
    table: str, modes: dict[str, int], previous: str, rows: Sequence[str] = ()
) -> list[str]:
    """Return the stage computing a learn stage's modes, as one row.

    Each mode counts each value in a ``GROUP BY``, which spills to disk; of
    the values counted most often, the smallest is kept (``min_by`` over
    count descending, then value). NULL when there is no value. `rows` are
    the one-row stages of the levels below that the expressions read.
    """
    joins = "".join(f" CROSS JOIN {quote(r)}" for r in rows)
    x, c = quote("x"), quote("c")
    branches = [
        (
            f"m{index}",
            f"SELECT min_by({x}, row(-{c}, {x})) AS {quote(f'm{index}')} FROM "
            f"(SELECT {x}, count(*) AS {c} FROM "
            f"(SELECT {inner} AS {x} FROM {quote(previous)}{joins}) "
            f"WHERE {x} IS NOT NULL GROUP BY {x})",
        )
        for inner, index in modes.items()
    ]
    return [_one_row(table, branches)]


def _std_ctes(
    name: str, stds: dict[str, int], previous: str, rows: list[str]
) -> list[str]:
    """Return the two stages computing a learn stage's variances.

    The population variance in two passes over the previous stage (issues
    #28, #42; a standard deviation is the root of its column): one stage of
    every column's mean, compensated (``favg``, as ``sq.agg.mean``), then one
    row of ``favg((x - mean) ^ 2)`` per column, over the rows cross-joined
    with that one row of means. Each pass is one streaming aggregate, so
    nothing waits in memory but a few numbers per column.
    Every value the same (or one value) gives exactly 0, by ``min = max``:
    the rounded mean may differ from the value itself
    (100,000 copies of 1/3), and Scale's zero-spread rule needs 0 there. NULL
    when there is no value; NaN, as the mean, beside an infinity, and NaN
    where the sum overflows: on ``[1e300, -1e300, 1e300]`` ``favg``
    overflows to NaN, where ``stddev_pop`` gave infinity. `rows` are the
    one-row stages (quantiles, modes, target statistics) the expressions
    may read; they are cross-joined into both passes.
    """
    means, table = quote(name + "_std_means"), quote(name + "_std")
    xs = {index: quote(f"x{index}") for index in stds.values()}
    mus = {index: quote(f"u{index}") for index in stds.values()}
    columns = ", ".join(f"{inner} AS {xs[index]}" for inner, index in stds.items())
    joins = "".join(f" CROSS JOIN {quote(r)}" for r in rows)
    present = f"(SELECT {columns} FROM {quote(previous)}{joins})"
    averages = ", ".join(f"favg({xs[i]}) AS {mus[i]}" for i in stds.values())
    spreads = ", ".join(
        f"CASE WHEN min({xs[i]}) = max({xs[i]}) AND isfinite(min({xs[i]})) "
        f"THEN 0.0 ELSE favg(({xs[i]} - {mus[i]}) ^ 2) END "
        f"AS {quote(f'v{i}')}"
        for i in stds.values()
    )
    return [
        f"{means} AS MATERIALIZED (SELECT {averages} FROM {present})",
        f"{table} AS MATERIALIZED (SELECT {spreads} FROM {present} CROSS JOIN {means})",
    ]


def _stats_ctes(
    table: str, stats: dict[tuple[str, str, str], int], previous: str
) -> list[str]:
    """Return the stage of the target's statistics by fold and category, as one row.

    Each is a ``GROUP BY``, which spills to disk; NULL (and NaN) is a
    category; the groups are gathered in one list per column, sorted by fold
    and category. The target is shifted by its minimum first (one more scan,
    of one value), so the sums hold ``y - min(y)``: whole values stay whole
    and small, and the sum of squares loses no digits to a large offset. The
    sums are compensated (``fsum``), as the mean is (ADR 0033).
    """
    f, c, v, n, total, squares = (quote(k) for k in ("f", "x", "y", "n", "s", "ss"))
    branches = []
    for (x, y, fold), index in stats.items():
        low = f"(SELECT min(CAST({y} AS DOUBLE)) FROM {quote(previous)})"
        branches.append(
            (
                f"l{index}",
                f"SELECT list(row({f}, {c}, {n}, {total}, {squares}) "
                f"ORDER BY {f}, {c}) AS {quote(f'l{index}')} FROM "
                f"(SELECT {f}, {c}, count(*) AS {n}, "
                f"fsum({v}) AS {total}, fsum({v} * {v}) AS {squares} FROM "
                f"(SELECT {x} AS {c}, CAST({y} AS DOUBLE) - {low} AS {v}, "
                f"{fold} AS {f} FROM {quote(previous)}) GROUP BY {f}, {c})",
            )
        )
    return [_one_row(table, branches)]


@dataclass(frozen=True)
class _Call:
    """One aggregate call found in a learned value's SQL text.

    `name` is the function's name as written, `start` and `end` delimit the
    whole call (its ``FILTER (WHERE ...)`` included), `open` and `close` are
    the indices of its own brackets, so ``text[open + 1 : close]`` is its
    argument list.
    """

    name: str
    start: int
    open: int
    close: int
    end: int

    @property
    def staged(self) -> bool:
        """Whether it is one of sq.agg's staged markers."""
        return self.name in _STAGED

    def rebuilt(self, text: str, inner: str, clause: str) -> str:
        """Return the call's text with its arguments and its clause replaced."""
        return text[self.start : self.open + 1] + inner + ")" + clause


_STAGED = frozenset({QUANTILE, MODE, STD, VAR, TARGET_STATS})
"""The names of sq.agg's staged markers."""

_FILTER = re.compile(r"\s*FILTER\s*\(", re.IGNORECASE)
"""An aggregate's ``FILTER (WHERE ...)``, which belongs to its call."""

_OVER = re.compile(r"\s*OVER\b", re.IGNORECASE)
"""A window's ``OVER``: an aggregate followed by it is a window function."""

_SUBQUERY = re.compile(r"\s*(?:SELECT|WITH|FROM)\b", re.IGNORECASE)
"""A bracket opening a subquery, whose aggregates read its own tables."""


def _calls(text: str) -> list[_Call]:
    """Find the outermost aggregate calls of `text`, staged or plain, in order.

    An aggregate is one of sq.agg's staged markers or one of DuckDB's
    aggregate functions; a name is matched only outside quotes and as a
    whole name. A call followed by ``OVER`` is a window function, not an
    aggregate: the search goes on inside it, as inside any other function.
    A subquery (a bracket opening with ``SELECT``, ``WITH`` or ``FROM``) is
    skipped whole: its aggregates read its own tables. ``filter`` is not
    taken for an aggregate: as a function it is DuckDB's ``list_filter``, and
    as an aggregate's clause it is read with that aggregate. The text is
    read once from start to end.
    """
    names = _aggregate_names()
    found: list[_Call] = []
    i = 0
    while (match := _CALL.search(text, i)) is not None:
        piece = match.group()
        if piece[-1] == "(" and _SUBQUERY.match(text, match.end()):
            after, _ = _scan(text, match.end() - 1)  # a subquery: skip it
            if after < 0:
                break
            i = after
            continue
        name = match.group(1)
        if name is None or (name not in _STAGED and name.lower() not in names):
            i = match.end()  # a quote, a bracket, or another function: go on
            continue
        opened = match.end() - 1
        after, _ = _scan(text, opened)
        if after < 0:
            break
        end = after
        clause = _FILTER.match(text, after)
        if clause is not None:
            end, _ = _scan(text, clause.end() - 1)
            if end < 0:
                break
        if _OVER.match(text, end):
            i = match.end()
            continue
        found.append(_Call(name, match.start(), opened, after - 1, end))
        i = end
    return found


@dataclass
class _Level:
    """One level of a learn stage (ADR 0051): the aggregates of one height.

    `staged` holds its quantiles, modes, statistics and variances; `plain`
    maps each plain aggregate's text to its column (``p0``, ...) of the
    level's plain stage; `reads` names the one-row stages of the levels below
    its expressions read, in the order first read.
    """

    staged: _Staged
    plain: dict[str, int] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)

    @property
    def plain_table(self) -> str:
        """Return the name of the level's stage of plain aggregates."""
        return self.staged.name + "_plain"


class _Planner:
    """Place each aggregate of a learn stage in the level of its height.

    An aggregate's height is 1 when its argument holds none, else one more
    than the highest inside it; it is computed in level `height`, over the
    stage's input cross-joined with the one-row stages of the levels below it
    reads, and stands in the text above it as the plain column of its row.
    Level 1 keeps the learn stage's own name, so a learned value without
    nesting is computed as before.
    """

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.levels: dict[int, _Level] = {}

    def level(self, k: int) -> _Level:
        """Return level `k`, made when first asked for."""
        if k not in self.levels:
            base = self.stage.learn_name
            self.levels[k] = _Level(_Staged(base if k == 1 else f"{base}_l{k}"))
        return self.levels[k]

    def inside(self, text: str) -> tuple[str, int, list[str]]:
        """Replace each aggregate in `text` by a reference to its level's row.

        Returns the text, the highest level placed (0 when none) and the
        one-row stages the references read, in order.
        """
        pieces: list[str] = []
        last = 0
        height = 0
        reads: list[str] = []
        for call in _calls(text):
            reference, k, table = self.place(text, call, nested=True)
            pieces += [text[last : call.start], reference]
            last = call.end
            height = max(height, k)
            if table not in reads:
                reads.append(table)
        pieces.append(text[last:])
        return "".join(pieces), height, reads

    def rewritten(self, text: str, call: _Call) -> tuple[str, int, list[str]]:
        """Return `call` with the aggregates in its arguments and clause placed.

        Its ``FILTER (WHERE ...)`` is read per row, as its arguments are, so
        an aggregate there is placed in a level below too. Returns the text,
        the highest level placed inside (0 when none) and the stages read.
        """
        inner, below, reads = self.inside(text[call.open + 1 : call.close])
        clause, also, more = self.inside(text[call.close + 1 : call.end])
        return (
            call.rebuilt(text, inner, clause),
            max(below, also),
            [*reads, *(r for r in more if r not in reads)],
        )

    def place(self, text: str, call: _Call, *, nested: bool) -> tuple[str, int, str]:
        """Place `call` (found in `text`) in its level.

        Its argument's aggregates are placed first, in the levels below.
        Returns the reference standing for it, its level and the one-row
        stage the reference reads. `nested` tells a staged result read inside
        another aggregate (a plain column) from one read beside the scan
        (``any_value``).
        """
        if call.staged and call.end > call.close + 1:
            raise _refuse(
                self.stage,
                text[call.start : call.end],
                "a FILTER clause on one of sq.agg's aggregates, which take "
                "none: it would be left out, not applied.",
                "filter inside the aggregate's argument instead, such as "
                "sq.agg.median(CASE WHEN x > 3 THEN x END).",
            )
        rebuilt, below, reads = self.rewritten(text, call)
        k = below + 1
        level = self.level(k)
        for table in reads:
            if table not in level.reads:
                level.reads.append(table)
        if not call.staged:
            index = level.plain.setdefault(rebuilt, len(level.plain))
            column = f"{quote(level.plain_table)}.{quote(f'p{index}')}"
            return column, k, level.plain_table
        (marker,) = _markers(rebuilt)
        if marker.kind == TARGET_STATS and below:
            raise _refuse(
                self.stage,
                rebuilt,
                "an aggregate inside the target's statistics, which are "
                "learned per fold and category from the rows themselves.",
                "learn the inner aggregate in an earlier step.",
            )
        reference = level.staged.reference(self.stage, rebuilt, marker, nested=nested)
        return reference, k, level.staged.table(marker)

    def ctes(self, previous: str) -> tuple[list[str], list[str]]:
        """Return every level's stages, lowest first, and their one-row stages."""
        ctes: list[str] = []
        rows: list[str] = []
        for k in sorted(self.levels):
            level = self.levels[k]
            staged, below = level.staged, level.reads
            mine: list[str] = []
            if staged.quantiles:
                ctes.extend(
                    _quantile_ctes(staged.name, staged.quantiles, previous, below)
                )
                mine.append(staged.name + "_quantile")
            if staged.modes:
                ctes.extend(
                    _mode_ctes(staged.name + "_modes", staged.modes, previous, below)
                )
                mine.append(staged.name + "_modes")
            if staged.stats:
                ctes.extend(_stats_ctes(staged.name + "_stats", staged.stats, previous))
                mine.append(staged.name + "_stats")
            if staged.stds:  # last: its passes may read the stages above
                read = [*below, *(r for r in mine if r in staged.std_reads)]
                ctes.extend(_std_ctes(staged.name, staged.stds, previous, read))
                mine.append(staged.name + "_std")
            if level.plain:
                joins = "".join(f" CROSS JOIN {quote(r)}" for r in below)
                picks = ", ".join(
                    f"{sql} AS {quote(f'p{index}')}"
                    for sql, index in level.plain.items()
                )
                ctes.append(
                    f"{quote(level.plain_table)} AS MATERIALIZED "
                    f"(SELECT {picks} FROM {quote(previous)}{joins})"
                )
                mine.append(level.plain_table)
            rows.extend(mine)
        return ctes, rows


def _learn_ctes(stage: Stage, learn: dict[str, Expression], previous: str) -> list[str]:
    """Return a learn stage, after the levels of the aggregates nested in it.

    Each aggregate inside another, and each staged marker anywhere, is
    placed in the level of its height (ADR 0051) and replaced by a reference
    to the one row its level computed, so an aggregate may sit inside any
    other, at any depth (``median(abs(x - median(x)))``). The plain
    aggregates not inside another are computed in the learn stage's scan of
    the previous stage, which cross-joins the rows its references read and
    reads a staged result with ``any_value`` (inside an aggregate, as a plain
    column); a scalar subquery per reference instead made DuckDB plan one
    join per reference (4.6 s for 600 references, and past its expression
    depth at 1,000). A learned value that is one whole staged marker (the
    target encoder's statistics, a bare median) is not computed in the scan:
    it is read once, as the plain column of its row, cross-joined with the
    scan's one row (issue #41: the scan carried the 50,000-element
    statistics list on every source row). The stage's columns keep the
    learned values' order, then the row count.
    """
    planner = _Planner(stage)
    items: dict[str, str] = {}  # computed in the scan
    whole: dict[str, str] = {}  # one whole marker each, read beside the scan
    scan_reads: set[str] = set()  # the one-row stages each part reads
    whole_reads: set[str] = set()
    for key, expression in learn.items():
        text = str(expression)
        calls = _calls(text)
        if (
            len(calls) == 1
            and calls[0].staged
            and not text[: calls[0].start].strip()
            and not text[calls[0].end :].strip()
        ):
            reference, _, table = planner.place(text, calls[0], nested=True)
            whole[key] = reference
            whole_reads.add(table)
            continue
        pieces: list[str] = []
        last = 0
        for call in calls:
            if call.staged:
                reference, _, table = planner.place(text, call, nested=False)
                scan_reads.add(table)
            else:  # computed in the scan itself, over the levels it reads
                reference, _, reads = planner.rewritten(text, call)
                scan_reads.update(reads)
            pieces += [text[last : call.start], reference]
            last = call.end
        pieces.append(text[last:])
        items[key] = "".join(pieces)
    ctes, rows = planner.ctes(previous)
    joins = "".join(f" CROSS JOIN {quote(r)}" for r in rows if r in scan_reads)
    # The row count beside the values tells "no rows" from NULL values.
    scan = ", ".join(
        [
            *(f"{v} AS {quote(k)}" for k, v in items.items()),
            f"count(*) AS {quote(_ROWS)}",
        ]
    )
    select = f"SELECT {scan} FROM {quote(previous)}{joins}"
    if whole:
        alias = quote(stage.learn_name + "_scan")
        picks = ", ".join(
            f"{whole[k] if k in whole else f'{alias}.{quote(k)}'} AS {quote(k)}"
            for k in [*learn, _ROWS]
        )
        beside = "".join(f" CROSS JOIN {quote(r)}" for r in rows if r in whole_reads)
        select = f"SELECT {picks} FROM ({select}) AS {alias}{beside}"
    # MATERIALIZED, never NOT MATERIALIZED: the one row is computed once.
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
        reads = quote(previous)
        if stage.row:
            # The row values, computed once per row, then read under the
            # previous stage's name, so the outputs' references still hold.
            ctes.append(
                f"{quote(stage.row_name)} AS (SELECT {quote(previous)}.*, "
                f"{_items(stage.row)} FROM {quote(previous)}{joins})",
            )
            reads = f"{quote(stage.row_name)} AS {quote(previous)}"
        ctes.append(
            f"{quote(stage.name)} AS "
            f"(SELECT {_items(stage.columns)} FROM {reads}{joins})",
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


_ZONED = "timestamp with time zone"


def _has_zone(kind: DuckDBPyType) -> bool:
    """Say whether a type holds a ``TIMESTAMP WITH TIME ZONE`` anywhere."""
    if kind.id == _ZONED:
        return True
    if kind.id in {"list", "array", "struct", "map"}:
        return any(_has_zone(child) for _, child in _children(kind))
    return False


def _children(kind: DuckDBPyType) -> list[tuple[str, DuckDBPyType]]:
    """Return a nested type's typed children (an array's size left out)."""
    return [
        (name, child)
        for name, child in kind.children
        if isinstance(child, DuckDBPyType)
    ]


def _in_utc(sql: str, kind: DuckDBPyType) -> str:
    """Return SQL giving the value with each zoned timestamp as UTC, unzoned.

    DuckDB hands a zoned timestamp to Python only through pytz, which
    sqlearn does not depend on (#56); its UTC wall time needs nothing.
    """
    if not _has_zone(kind):
        return sql
    if kind.id == _ZONED:
        return f"timezone('UTC', {sql})"
    if kind.id in {"list", "array"}:
        ((_, child),) = _children(kind)
        return f"list_transform({sql}, lambda v: {_in_utc('v', child)})"
    if kind.id == "map":
        (_, key), (_, value) = _children(kind)
        pair = (
            f"{{'key': {_in_utc('e.key', key)}, 'value': {_in_utc('e.value', value)}}}"
        )
        return f"map_from_entries(list_transform(map_entries({sql}), lambda e: {pair}))"
    fields = ", ".join(
        f"{quote(name)} := {_in_utc(f'({sql}).{quote(name)}', child)}"
        for name, child in _children(kind)
    )
    return f"CASE WHEN {sql} IS NULL THEN NULL ELSE struct_pack({fields}) END"


def _zoned(value: object, kind: DuckDBPyType) -> object:
    """Mark each UTC wall time read by `_in_utc` as UTC again."""
    if value is None or not _has_zone(kind):
        return value
    if kind.id == _ZONED:
        assert isinstance(value, datetime.datetime)
        return value.replace(tzinfo=datetime.UTC)
    if kind.id in {"list", "array"}:
        ((_, child),) = _children(kind)
        assert isinstance(value, list)
        return [_zoned(v, child) for v in value]
    if kind.id == "map":
        (_, key), (_, child) = _children(kind)
        assert isinstance(value, dict)
        return {_zoned(k, key): _zoned(v, child) for k, v in value.items()}
    assert isinstance(value, dict)
    return {name: _zoned(value[name], child) for name, child in _children(kind)}


def _fetch_learned(
    con: duckdb.DuckDBPyConnection, sql: str
) -> tuple[str, Sequence[tuple[object, ...]]]:
    """Fetch the learn statement's rows, zoned timestamps as UTC.

    Returns the statement run and its rows. A statement learning no zoned
    timestamp runs as it is.
    """
    rel = con.sql(sql)
    kinds = rel.types
    if not any(_has_zone(kind) for kind in kinds):
        return sql, rel.fetchall()
    picks = ", ".join(
        f"{_in_utc(quote(name), kind)} AS {quote(name)}"
        for name, kind in zip(rel.columns, kinds, strict=True)
    )
    sql = f"SELECT {picks} FROM ({sql})"
    rows = con.sql(sql).fetchall()
    return sql, [
        tuple(_zoned(v, kind) for v, kind in zip(row, kinds, strict=True))
        for row in rows
    ]


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
        sql, rows = _fetch_learned(con, _learn_sql(source_sql, stages))
        run.statements.append(sql)
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
