"""The pipeline: named steps that learn from data, then apply what they learned."""

import weakref
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE, DuckDBPyType

from sqlearn._compose import (
    POSITION,
    SOURCE,
    TARGET,
    Run,
    Stage,
    _learn_sql,
    apply_sql,
    build,
    describe,
    execute,
    inner_fold,
    inner_name,
    number_rows,
    stage_name,
    step_stage,
)
from sqlearn._config import connection, get_config
from sqlearn._diagnose import diagnose
from sqlearn._errors import SqlearnError, StepError
from sqlearn._inputs import Source, read
from sqlearn._model import (
    Model,
    as_model,
    check_feed,
    is_model,
    received,
    take,
    target_values,
)
from sqlearn._output import Output, to_output
from sqlearn._plan import Plan, plan
from sqlearn._selectors import Schema, _Cols, _is_numeric, to_selector
from sqlearn._step import Step
from sqlearn._store import STORE, Entry, FoldKey, StepKey, step_key

__all__ = ["Pipeline"]

_ROW = "__sqlearn_row"
"""The column numbering the rows that feed `predict`; never handed back."""


def _default_name(step: Step | object) -> str:
    """Return the name a plain item gets: "model" for a model, else the step's."""
    if isinstance(step, Step) and not is_model(step):
        return step.default_name()
    return "model"


def _name_steps(
    items: Sequence[Step | object | tuple[str, Step | object]],
) -> list[tuple[str, Step | object]]:
    """Name the plain items of a list, leaving given names as they are.

    A plain item is named by its `default_name()`, or "model" for a model. A
    default name used twice, or already given, is numbered from 1 in order,
    skipping any name taken.
    """
    pairs: list[tuple[str | None, Step | object]] = []
    for item in items:
        if isinstance(item, tuple):
            pairs.append((item[0], item[1]))
        else:
            pairs.append((None, item))
    given = {n for n, _ in pairs if n is not None}
    defaults = [None if n is not None else _default_name(s) for n, s in pairs]
    counts = Counter(d for d in defaults if d is not None)
    taken = set(given)
    seen: Counter[str] = Counter()
    named: list[tuple[str, Step | object]] = []
    for (n, step), base in zip(pairs, defaults, strict=True):
        if n is None:
            assert base is not None
            if counts[base] > 1 or base in given:
                while True:
                    seen[base] += 1
                    n = f"{base}-{seen[base]}"
                    if n not in taken:
                        break
            else:
                n = base
            taken.add(n)
        named.append((n, step))
    return named


def _kind(dtype: DuckDBPyType) -> str:
    """Name a type's kind: every number is alike, any other type is itself."""
    return "numeric" if _is_numeric(dtype) else str(dtype)


def _source_sql(con: duckdb.DuckDBPyConnection, source: Source) -> str:
    """Return the source's SQL once it binds, so no step is blamed for it."""
    source_sql = source.relation.sql_query()
    try:
        describe(con, source_sql, [])
    except duckdb.Error as exc:
        msg = (
            f"DuckDB cannot read the input: {exc}\n"
            "Fix: check that the data passed still exists and can be read."
        )
        raise SqlearnError(msg) from exc
    return source_sql


def _bind(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    stages: list[Stage],
    steps: list[tuple[str, Step]],
    position: int,
) -> Schema:
    """Return the columns after the last stage, naming its step if it fails."""
    try:
        return describe(con, source_sql, stages)
    except duckdb.Error as exc:
        sql = build(source_sql, stages)
        raise diagnose(exc, steps, lambda _: position, sql=sql) from exc


def _stage_of(steps: list[tuple[str, Step]]) -> Callable[[str], int | None]:
    """Return a function finding the first stage of a step named in a message."""

    def find(message: str) -> int | None:
        hits = [
            (at, i + 1)
            for i, (name, _) in enumerate(steps)
            for learn in (False, True)
            if (at := message.find(stage_name(i + 1, name, learn))) >= 0
        ]
        return min(hits)[1] if hits else None

    return find


def _make_stage(
    steps: list[tuple[str, Step]],
    position: int,
    *args: Any,  # noqa: ANN401  (the rest of step_stage's arguments)
    **kwargs: Any,  # noqa: ANN401
) -> Stage:
    """Build a step's stage; a failure of the user's code is explained."""
    name, step = steps[position - 1]
    try:
        return step_stage(position, name, step, *args, **kwargs)
    except StepError as exc:
        placed = _placed(exc, name, position)
        if placed is exc:
            raise
        raise placed from exc
    except Exception as exc:
        err = diagnose(exc, steps, lambda _: position)
        if err is exc:
            raise
        raise err from exc


def _placed(exc: StepError, name: str, position: int) -> StepError:
    """Give a step's own refusal (raised with position 0) its name and place."""
    if exc.position != 0:
        return exc
    return StepError(f"{name} (step {position}) {exc}", step=name, position=position)


def _matched(step: Step, schema: Schema, name: str, position: int) -> list[str]:
    """Return the columns a step works on, refusing a selector matching none.

    A name given in ``cols=`` (a string, a list or ``sq.cols``) must be a
    column of the data reaching the step: a misspelt name is refused rather
    than skipped. The planner, which runs before the names are known, does
    not refuse it.
    """
    given = None if step.cols is None else to_selector(step.cols)
    if isinstance(given, _Cols):
        have = {c for c, _ in schema}
        absent = [n for n in given.names if n not in have]
        if absent:
            names = ", ".join(repr(c) for c, _ in schema)
            msg = (
                f"{name} (step {position}) has cols={step.cols!r}, but the data "
                f"reaching it has no column {', '.join(map(repr, absent))} (its "
                f"columns: {names}). A name given in cols= must be a column. "
                "Fix: correct the name (names are matched exactly), or remove "
                "it from cols=."
            )
            raise StepError(msg, step=name, position=position)
    try:
        chosen = step.inputs(schema)
    except StepError as exc:
        placed = _placed(exc, name, position)
        if placed is exc:
            raise
        raise placed from exc
    if step.cols is not None and not chosen:
        names = ", ".join(repr(c) for c, _ in schema)
        msg = (
            f"{name} (step {position}) has cols={step.cols!r}, which matches no "
            f"column of the data reaching it ({names}). A step must work on at "
            "least one column. Fix: change cols=, or remove the step."
        )
        raise StepError(msg, step=name, position=position)
    return chosen


def _by_column(values: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Turn learned name, then column, into column, then learned name."""
    out: dict[str, dict[str, object]] = {}
    for key, per_column in values.items():
        for column, value in per_column.items():
            out.setdefault(column, {})[key] = value
    return out


def _check_numbering(con: duckdb.DuckDBPyConnection, schema: Schema) -> None:
    """Refuse what would break numbering the rows that feed `predict`."""
    if any(c.lower() == _ROW for c, _ in schema):
        msg = (
            f"the data has a column named {_ROW!r}, a name sqlearn keeps for "
            "numbering rows so predictions line up with the input. Fix: "
            "rename that column before predict."
        )
        raise SqlearnError(msg)
    setting = con.sql("SELECT current_setting('preserve_insertion_order')")
    if not setting.fetchall()[0][0]:
        msg = (
            "the connection has preserve_insertion_order turned off, so DuckDB "
            "may read rows in any order and predictions could not be matched "
            "to the input's rows. Fix: SET preserve_insertion_order = true on "
            "the connection before predict."
        )
        raise SqlearnError(msg)


def _schema(rel: duckdb.DuckDBPyRelation) -> Schema:
    return list(zip(rel.columns, rel.types, strict=True))


_INNER = "__sqlearn_inner_"
"""How the name of every inner-fold column begins (`inner_name`)."""


def _aside_of(source: Source) -> list[str]:
    """Return the columns travelling beside the data: not in its schema."""
    seen = {c for c, _ in source.schema}
    return [c for c in source.relation.columns if c not in seen]


def _positioned(rel: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    """Return the rows numbered from 1 in the order read, as `POSITION`.

    Inner folds are dealt by this number, so each query reading the data
    must number its rows alike: DuckDB keeps insertion order unless the
    connection turns it off, which is refused.
    """
    con = connection()
    setting = con.sql("SELECT current_setting('preserve_insertion_order')")
    if not setting.fetchall()[0][0]:
        msg = (
            "the connection has preserve_insertion_order turned off, so DuckDB "
            "may read rows in any order and a step learning from the target "
            "could not deal each row into the same inner fold every time. "
            "Fix: SET preserve_insertion_order = true on the connection."
        )
        raise SqlearnError(msg)
    return con.sql(number_rows(rel.sql_query(), POSITION))


def _features_only(schema: Schema, aside: Sequence[str]) -> Schema:
    """Return the columns of a stage without those travelling beside them."""
    gone = set(aside)
    return [c for c in schema if c[0] not in gone]


def _without(source: Source, target: str | None) -> Source:
    """Return the data without the target column, when it holds it."""
    if target is None or all(c != target for c, _ in source.schema):
        return source
    kept = [(c, t) for c, t in source.schema if c != target]
    rel = source.relation.project(*(duckdb.ColumnExpression(c) for c, _ in kept))
    return Source(rel, source.key, kept)


def _derive(
    steps: list[tuple[str, Step]],
    position: int,
    learned: Mapping[str, Mapping[str, object]],
    columns: Sequence[str],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, dict[str, object]]]]:
    """Derive a target step's values on all rows and per inner fold, per column.

    Returns the values learned on all rows and, per inner fold, those learned
    on the rows outside it, each as learned name, then column, to value.
    """
    name, step = steps[position - 1]
    every: dict[str, dict[str, object]] = {}
    folds: dict[str, dict[str, dict[str, object]]] = {}
    for c in columns:
        fetched = {key: per[c] for key, per in learned.items() if c in per}
        try:
            derived = step.derive(fetched, getattr(step, "cv"))  # noqa: B009
        except StepError as exc:
            placed = _placed(exc, name, position)
            if placed is exc:
                raise
            raise placed from exc
        except Exception as exc:
            err = diagnose(exc, steps, lambda _: position)
            if err is exc:
                raise
            raise err from exc
        for key, values in derived.items():
            into = every if key == "all" else folds.setdefault(key, {})
            for learned_name, value in values.items():
                into.setdefault(learned_name, {})[c] = value
    return every, folds


def _after_unapplied(
    step: Step, schema: Schema, inputs: Sequence[str], dynamic: bool
) -> Schema:
    """Return the columns later steps of a run see past a step not applied.

    A dynamic step's inputs are gone once it applies, so the steps learning
    now must not see them; a step learning from the target turns its inputs
    into numbers, so they must not be seen as they were (text) either.
    """
    if step.keep:
        return schema
    if step.uses_target:
        return [(c, DOUBLE if c in inputs else t) for c, t in schema]
    if dynamic:
        return [c for c in schema if c[0] not in inputs]
    return schema


def _unread(
    stage: Stage,
    steps: list[tuple[str, Step]],
    built: tuple[Schema, str, list[str]],
    bound: Schema | None,
    aside: Sequence[str],
    *,
    last: bool,
) -> Stage:
    """Return a learning step's stage for a learn statement nothing reads it in.

    Its learn stage stays; its outputs, written with placeholders, are not
    built. The last stage of the statement passes its input through; one
    before a later stage keeps its outputs' names and types, as NULL, so the
    later stages (which read none of them) bind as they did.
    """
    before, previous, matched = built
    if last or bound is None:
        return _make_stage(
            steps, stage.position, before, previous,
            columns=matched, applies=False, aside=aside,
        )  # fmt: skip
    step = steps[stage.position - 1][1]
    passing = {c for c, _ in before if c not in matched or step.keep}
    types = dict(bound)
    columns = {
        name: e if name in passing or name not in types else _null(types[name])
        for name, e in stage.columns.items()
    }
    return replace(stage, columns=columns, reads=[], row={})


def _null(dtype: DuckDBPyType) -> Expression:
    """Return NULL of a type: a column no later stage reads."""
    return duckdb.ConstantExpression(None).cast(dtype)


def _hold(source: Source) -> None:
    """Do nothing: a finaliser's argument stays alive until it is called."""


class Pipeline:
    """Named steps that learn from data together, then apply what they learned.

    `learn` runs the steps on data, in as few runs of SQL as the steps allow,
    and keeps what each step learned (in the learning store, so unchanged
    steps on unchanged data are not learned twice). `apply` then prepares any
    data in one SQL statement, with the learned values written in.

    Parameters
    ----------
    steps : sequence of Step or model or (str, Step or model)
        The steps, in order. A plain item is named by its `default_name()`
        ("model" for a model); names that clash are numbered from 1 in order
        (``step-1``, ``step-2``). Given names must be unique.

    Attributes
    ----------
    steps : list of (str, Step)
        The named steps, as given.
    runs_ : list of Run
        The runs the last call executed, with their SQL statements; empty
        when everything was found in the store.

    Raises
    ------
    SqlearnError
        If two steps share a name.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> class Centre(sq.Step):
    ...     def learn(self, x):
    ...         return {"mean": sq.agg.mean(x)}
    ...
    ...     def apply(self, x, learned):
    ...         return x - learned.mean
    >>> data = connection().sql("SELECT * FROM (VALUES (1.0), (3.0)) t(a)")
    >>> pipe = sq.Pipeline([("centre", Centre())]).learn(data)
    >>> pipe["centre"].mean_
    {'a': 2.0}
    >>> pipe.apply(data).fetchall()
    [(-1.0,), (1.0,)]
    """

    def __init__(
        self, steps: Sequence[Step | object | tuple[str, Step | object]]
    ) -> None:
        self.steps = _name_steps(steps)
        clash = [
            n for n, count in Counter(n for n, _ in self.steps).items() if count > 1
        ]
        if clash:
            msg = (
                f"two steps are named {clash[0]!r}; each step needs its own "
                "name. Fix: rename one."
            )
            raise SqlearnError(msg)
        self.runs_: list[Run] = []
        self._entries: list[Entry] | None = None
        self._types: list[dict[str, DuckDBPyType]] = []
        # Per step, the names of the columns it created, fixed at learn.
        self._names: list[dict[str, list[str]]] = []
        self._columns_out: list[str] = []
        self._feed: str | None = None
        # The target the steps learned with: left out of the data at apply.
        self._target: str | None = None

    @property
    def named_steps(self) -> dict[str, Any]:
        """The steps by name, in order.

        Returns
        -------
        dict of str to Step
            Each step under its name.

        Examples
        --------
        >>> import sqlearn as sq
        >>> list(sq.Pipeline([("a", sq.Step()), ("b", sq.Step())]).named_steps)
        ['a', 'b']
        """
        return dict(self.steps)

    @property
    def columns_out_(self) -> list[str]:
        """The output columns, known after `learn` without running anything.

        Returns
        -------
        list of str
            The columns `apply` returns, in order.

        Raises
        ------
        AttributeError
            If the pipeline has not learned yet.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> data = connection().sql("SELECT 1 AS a, 2 AS b")
        >>> sq.Pipeline([("copy", sq.Step())]).learn(data).columns_out_
        ['a', 'b']
        """
        if self._entries is None:
            msg = (
                "columns_out_ is known after the pipeline has learned; call learn first"
            )
            raise AttributeError(msg)
        return list(self._columns_out)

    def __getitem__(self, key: str | int) -> Any:  # noqa: ANN401  (a step or, later, a model)
        """Return a step by name or by position (counting from 0, as a list).

        Parameters
        ----------
        key : str or int
            The step's name or index.

        Returns
        -------
        Step
            The step.
        """
        if isinstance(key, int):
            return self.steps[key][1]
        return self.named_steps[key]

    def _split(self) -> tuple[list[tuple[str, Step]], Model | None]:
        """Return the steps, and the model when the last element is not a step."""
        steps: list[tuple[str, Step]] = []
        model: Model | None = None
        for i, (name, step) in enumerate(self.steps):
            if isinstance(step, Step):
                steps.append((name, step))
                continue
            last = i == len(self.steps) - 1
            if last and is_model(step):
                model = as_model(step)
                continue
            where = "" if last else "; only the last element may be a model"
            msg = (
                f"{name} (step {i + 1}) is a {type(step).__name__}, not a step "
                f"and not a model (one with fit and predict){where}. Fix: make "
                "it a subclass of sq.Step, or put the model last."
            )
            raise SqlearnError(msg)
        return steps, model

    def _checked(self) -> list[tuple[str, Step]]:
        steps, model = self._split()
        if model is not None:
            name = self.steps[-1][0]
            msg = (
                f"this pipeline ends in a model ({name!r}), so it is trained, "
                "not learned: learn and apply are for steps alone. Fix: call "
                "train(data, target=...) and predict(data), or build a pipeline "
                "of the steps without the model."
            )
            raise SqlearnError(msg)
        return steps

    def _modelled(self) -> tuple[list[tuple[str, Step]], Model]:
        steps, model = self._split()
        if model is None:
            msg = (
                "this pipeline has no model: its last element is a step, so "
                "there is nothing to train. Fix: add a model last, such as "
                "('model', LogisticRegression()), or call learn and apply."
            )
            raise SqlearnError(msg)
        return steps, model

    def learn(self, data: object, target: str | None = None) -> "Pipeline":
        """Learn every step from data, finding unchanged steps in the store.

        The data is read once. Steps go in the earliest run their inputs
        allow; a run whose steps are all in the store runs nothing.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
        target : str, optional
            The target column, needed only by a step that learns from it
            (``sq.encode.target``). It is set aside as in `train`: no other
            step and no selector sees it. Such a step is cross-fitted for
            the steps after it, as in `train`; `apply` then uses what it
            learned on all rows.

        Returns
        -------
        Pipeline
            This pipeline, learned.

        Raises
        ------
        SqlearnError
            If the input cannot be read (see `sqlearn._inputs.read`), the
            pipeline ends in a model (use `train`), or the target is not a
            column.
        StepError
            If a step's selector matches no column, a step learns from no
            rows, or a step learns from the target and `target` is not
            given.

        Notes
        -----
        A change to a DuckDB table or relation in place that keeps its row
        count and columns (an ``UPDATE``, or rows deleted and as many
        inserted) is not noticed: the values learned before are reused. Pass
        the changed data under a new name, or as a file or a pandas frame, to
        have it learned again.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> data = connection().sql("SELECT 1 AS a")
        >>> sq.Pipeline([("copy", sq.Step())]).learn(data).runs_
        []
        """
        steps = self._checked()
        if target is None:
            for i, (name, step) in enumerate(steps):
                if step.uses_target:
                    msg = (
                        f"{name} (step {i + 1}) learns from the target, but "
                        "learn was given none, so there is nothing to learn "
                        "from. Fix: pass the target column, as "
                        "learn(data, target='churned')."
                    )
                    raise StepError(msg, step=name, position=i + 1)
        source = read(data)
        con = connection()
        _source_sql(con, source)
        learn_from = source if target is None else self._features(source, target)
        _, runs, known = self._learn(con, learn_from, steps)
        stages, out, types = self._stages(
            con, learn_from.relation.sql_query(), learn_from.schema, steps, known
        )
        self._commit(steps, known, types, [c for c, _ in out], stages)
        self._target = target
        self.runs_ = [run for _, run in runs]
        return self

    def _learn(
        self,
        con: duckdb.DuckDBPyConnection,
        source: Source,
        steps: list[tuple[str, Step]],
        fold: FoldKey | None = None,
    ) -> tuple[Plan, list[tuple[int, Run]], list[Entry]]:
        """Learn the steps missing from the store, run by run.

        `fold` is the fold whose training rows `source` holds, for the keys.
        A step's key holds the columns it reads, known in its run once the
        runs before have learned. Returns the plan, the runs executed (with
        their numbers) and every step's entry.
        """
        the_plan = plan(steps, source.schema)
        entries: list[Entry | None] = [None] * len(steps)
        runs: list[tuple[int, Run]] = []
        for r in sorted(set(the_plan.learn_run)):
            run = self._learn_run(con, source, steps, the_plan, r, entries, fold)
            if run.statements:
                runs.append((r, run))
        return the_plan, runs, [e for e in entries if e is not None]

    def _commit(
        self,
        steps: list[tuple[str, Step]],
        known: list[Entry],
        types: list[dict[str, DuckDBPyType]],
        columns_out: list[str],
        stages: list[Stage],
    ) -> None:
        """Keep what the steps learned; called last, once everything succeeded.

        Then each step hears what it learned (`Step.learned`), once.
        """
        learned = [_by_column(entry.values) for entry in known]
        for (_, step), values in zip(steps, learned, strict=True):
            step._set_learned(values)
        self._entries = known
        self._types = types
        self._names = [stage.created for stage in stages]
        self._columns_out = columns_out
        for (_, step), values in zip(steps, learned, strict=True):
            step.learned(values)

    def _learn_run(
        self,
        con: duckdb.DuckDBPyConnection,
        source: Source,
        steps: list[tuple[str, Step]],
        the_plan: Plan,
        run: int,
        entries: list[Entry | None],
        fold: FoldKey | None,
    ) -> Run:
        """Find the steps of one run in the store; learn and store the rest.

        Each step learning in this run is keyed with the columns its selector
        matches in the data reaching it, then looked up.
        """
        source_sql = source.relation.sql_query()
        aside = _aside_of(source)
        last = max(i for i, r in enumerate(the_plan.learn_run) if r == run)
        schema = source.schema
        previous = SOURCE
        stages: list[Stage] = []
        built: dict[int, tuple[Schema, str, list[str]]] = {}
        keys: dict[int, StepKey] = {}
        upto: dict[int, int] = {}
        after: dict[int, Schema] = {}  # the columns after each step, bound
        for i in range(last + 1):
            name, step = steps[i]
            position = i + 1
            dynamic = the_plan.apply_run[i] > the_plan.learn_run[i]
            if the_plan.learn_run[i] > run:
                # Not reached yet: a dynamic step's inputs are gone once it
                # applies, so the steps learning now must not see them.
                schema = _after_unapplied(step, schema, step.inputs(schema), dynamic)
                continue
            entry = entries[i]
            if entry is None:
                # It learns in this run (earlier runs filled their entries).
                matched = _matched(step, schema, name, position)
                keys[i] = step_key(
                    source.key, fold, steps, i, the_plan.depends_on[i], matched
                )
                entry = entries[i] = STORE.get(keys[i])
                if entry is None:
                    built[i] = (schema, previous, matched)
            if entry is not None:
                # A target step learned: the rows reaching later steps take
                # their values from their own inner fold (cross-fitting).
                stage = _make_stage(
                    steps, position, schema, previous, entry.values,
                    columns=entry.columns, aside=aside,
                    folds=entry.folds or None,
                )  # fmt: skip
            else:
                # The last step of the run is read by no later one: its
                # outputs are not built with placeholders (see `_unread`).
                stage = _make_stage(
                    steps, position, schema, previous,
                    columns=built[i][2], applies=not dynamic and i < last,
                    aside=aside,
                )  # fmt: skip
            stages.append(stage)
            upto[i] = len(stages)
            previous = stage.name
            if entry is None and dynamic:
                schema = _after_unapplied(step, schema, built[i][2], dynamic)
            elif i < last:
                # Only a later step of this run reads the columns after it.
                bound = _bind(con, source_sql, stages, steps, position)
                schema = after[i] = _features_only(bound, aside)
        misses = sorted(built)
        if not misses:
            return Run()
        stages = stages[: upto[misses[-1]]]
        for i in misses:
            if i == last or the_plan.apply_run[i] > the_plan.learn_run[i]:
                continue  # its output is not in the statement already
            if any(i in the_plan.depends_on[j] for j in range(i + 1, misses[-1] + 1)):
                continue  # a later step of the statement reads its output
            # Nothing later in the statement reads what it writes with
            # placeholders, so the statement holds only its learn stage.
            at = upto[i] - 1
            stages[at] = _unread(
                stages[at], steps, built[i], after.get(i), aside, last=i == misses[-1]
            )
        try:
            values, _, done = execute(con, source_sql, stages, produce=False)
        except duckdb.Error as exc:
            sql = _learn_sql(source_sql, stages)
            raise diagnose(exc, steps, _stage_of(steps), running=True, sql=sql) from exc
        for i in misses:
            name, step = steps[i]
            before, prev, matched = built[i]
            learned = values.get(stage_name(i + 1, name), {})
            folds: dict[str, dict[str, dict[str, object]]] = {}
            if step.uses_target:
                learned, folds = _derive(steps, i + 1, learned, matched)
            applied = _make_stage(steps, i + 1, before, prev, learned, columns=matched)
            entry = Entry(learned, matched, apply_sql(applied), folds)
            STORE.put(keys[i], entry)
            entries[i] = entry
        return done

    def _stages(
        self,
        con: duckdb.DuckDBPyConnection,
        source_sql: str,
        schema: Schema,
        steps: list[tuple[str, Step]],
        entries: list[Entry],
        check: list[dict[str, DuckDBPyType]] | None = None,
        names: list[dict[str, list[str]]] | None = None,
        *,
        aside: Sequence[str] = (),
        cross: bool = False,
        held: Expression | None = None,
    ) -> tuple[list[Stage], Schema, list[dict[str, DuckDBPyType]]]:
        """Build every step's stage with its learned values as constants.

        Checks each step's learned columns reach it, with the kind of type
        they had at learn when `check` holds those types. `names` holds the
        names of the created columns fixed at learn; without it they are
        named afresh, as when learning. The `aside` columns pass through
        every stage and are not in the schema returned. With `cross`, the
        rows are training rows: a step learning from the target encodes
        each with its own inner fold's values, except the rows `held` holds
        out, which take the values learned on all rows.
        """
        stages: list[Stage] = []
        types: list[dict[str, DuckDBPyType]] = []
        previous = SOURCE
        for i, ((name, _), entry) in enumerate(zip(steps, entries, strict=True)):
            position = i + 1
            have = dict(schema)
            for c in entry.columns:
                if c not in have:
                    msg = (
                        f"{name} (step {position}) learned from column {c!r}, but "
                        f"the data reaching it has no column {c!r}; what it learned "
                        "applies to that column. Fix: pass data with that column, "
                        "or learn the pipeline again on this data."
                    )
                    raise StepError(msg, step=name, position=position)
                if check is not None and _kind(have[c]) != _kind(check[i][c]):
                    msg = (
                        f"{name} (step {position}) learned from column {c!r} as "
                        f"{check[i][c]}, but here {c!r} is {have[c]}; what it "
                        f"learned does not apply to that type. Fix: cast {c!r} to "
                        f"{check[i][c]} before apply, or learn again on this data."
                    )
                    raise StepError(msg, step=name, position=position)
            types.append({c: have[c] for c in entry.columns})
            stage = _make_stage(
                steps, position, schema, previous, entry.values,
                columns=entry.columns,
                names=None if names is None else names[i],
                aside=aside, folds=entry.folds or None if cross else None,
                held=held,
            )  # fmt: skip
            stages.append(stage)
            previous = stage.name
            bound = _bind(con, source_sql, stages, steps, position)
            schema = _features_only(bound, aside)
        return stages, schema, types

    def apply(self, data: object, out: str | Output | None = None) -> Any:  # noqa: ANN401  (the form `out` names)
        """Apply what the steps learned to data, as one SQL statement.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
        out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
            What to hand back; by default ``sq.get_config().out``, and when
            that is None too, a lazy relation.

        Returns
        -------
        object
            A `duckdb.DuckDBPyRelation` (lazy, nothing run yet), or the result
            in the form `out` names.

        Raises
        ------
        SqlearnError
            If the pipeline has not learned yet, ends in a model (use
            `predict`), or the input cannot be read.
        StepError
            If the data lacks a column a step learned from, or holds it with
            another kind of type, or has a column taking the name of one a
            step created when it learned (DuckDB names ignore case).

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> data = connection().sql("SELECT 1 AS a")
        >>> pipe = sq.Pipeline([("copy", sq.Step())]).learn(data)
        >>> pipe.apply(data, out="numpy")["a"].tolist()
        [1]
        """
        if self._entries is None:
            msg = (
                "this pipeline has not learned yet, so there is nothing to "
                "apply. Fix: call learn(data) first."
            )
            raise SqlearnError(msg)
        steps = self._checked()
        source = read(data)
        con = connection()
        _source_sql(con, source)
        source = _without(source, self._target)
        source_sql = source.relation.sql_query()
        stages, _, _ = self._stages(
            con, source_sql, source.schema, steps, self._entries, self._types,
            self._names,
        )  # fmt: skip
        sql = build(source_sql, stages)
        rel = con.sql(sql)
        # The relation reads the source's view (for a frame): keep the
        # source, and so the view, alive for as long as the relation is.
        weakref.finalize(rel, _hold, source)
        self.runs_ = [Run([sql])]
        return to_output(rel, out if out is not None else get_config().out)

    def train(self, data: object, target: str, feed: str | None = None) -> "Pipeline":
        """Learn the steps, then train the model on the prepared data.

        The target column is set aside before planning: no selector sees it,
        and only a step that learns from it (``sq.encode.target``) is given
        it. The steps learn (or are found in the store), and one query
        prepares the features with the target beside them, so each row's
        answer stays with its features; a step that learns from the target
        encodes each row with what it learned on the rows outside the row's
        inner fold (cross-fitting). They are handed over in the form `feed`
        names and passed, with the target, to the model's ``fit``.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
        target : str
            The column the model learns to predict.
        feed : str, optional
            The form of the hand-over for this call; by default the model's
            own (``sq.Model(..., feed=...)``, which is ``"numpy"``).

        Returns
        -------
        Pipeline
            This pipeline, with its steps learned and its model trained.

        Raises
        ------
        SqlearnError
            If the pipeline has no model, the target is not a column, the
            target is missing in a row, a feature is not a number, or `feed`
            is not built.
        StepError
            As for `learn`.

        Notes
        -----
        A change to a DuckDB table or relation in place that keeps its row
        count and columns (an ``UPDATE``, or rows deleted and as many
        inserted) is not noticed: the values learned before are reused. Pass
        the changed data under a new name, or as a file or a pandas frame, to
        have it learned again.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> data = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [0, 0, 1, 1]})
        >>> pipe = sq.Pipeline(
        ...     [("scale", sq.scale.standard()), ("model", LogisticRegression())]
        ... )
        >>> pipe.train(data, target="y")["scale"].center_
        {'x': 2.5}
        """
        _, model = self._modelled()
        feed = model.feed if feed is None else feed
        check_feed(feed)
        return self._train(read(data), target, feed)

    def _features(
        self, source: Source, target: str, keep: Sequence[str] = ()
    ) -> Source:
        """Return the data with the target set aside, keyed with its name.

        The steps learn from this: its schema holds the features alone, so a
        selector cannot match the target and sq.cols.numeric() never scales
        it. Beside the features travel, in this order, the `keep` columns
        (a search's fold), the target as `TARGET`, and each row's inner fold
        for every step learning from the target, dealt by a hash of the
        row's position (`inner_fold`). The position is the relation's
        `POSITION` column when it has one (a search numbers every row once,
        before dealing them into outer folds, so a fold's training rows keep
        their numbers), else the rows are numbered here in the order read.
        """
        names = [c for c, _ in source.schema]
        if target not in names:
            msg = (
                f"the target {target!r} is not a column of the data, whose "
                f"columns are {', '.join(repr(c) for c in names)}. Fix: pass "
                "target= one of them, spelled as in the data."
            )
            raise SqlearnError(msg)
        for c in names:
            low = c.lower()
            if low in (TARGET, POSITION) or low.startswith(_INNER):
                msg = (
                    f"the data has a column named {c!r}, a name sqlearn keeps "
                    "for the target and its folds while steps learn. Fix: "
                    "rename that column."
                )
                raise SqlearnError(msg)
        features = [(c, t) for c, t in source.schema if c != target and c not in keep]
        steps, _ = self._split()
        folds = dict.fromkeys(
            (getattr(s, "cv"), getattr(s, "seed"))  # noqa: B009
            for _, s in steps
            if s.uses_target
        )
        rel = source.relation
        if folds and POSITION not in rel.columns:
            rel = _positioned(rel)
        feature_names = [c for c, _ in features]
        beside = [
            *(duckdb.ColumnExpression(c) for c in keep),
            duckdb.ColumnExpression(target).alias(TARGET),
            *(
                inner_fold(POSITION, cv, seed).alias(inner_name(cv, seed))
                for cv, seed in folds
            ),
        ]
        return Source(
            rel.project(*(duckdb.ColumnExpression(c) for c in feature_names), *beside),
            (*source.key, ("target", target)),
            features,
        )

    def _prepare_fold(
        self,
        learn_from: Source,
        fold: FoldKey,
        data: duckdb.DuckDBPyRelation,
        target: str,
        feed: str,
        *,
        keep: Sequence[str],
        held: Expression,
    ) -> tuple[Any, dict[str, Any]]:
        """Learn on one fold's training rows, then prepare all its rows once.

        `learn_from` holds the fold's training rows with the target set
        aside (see `_features`), keyed by the whole data; `fold` completes
        the keys. `data` holds every row with the `keep` columns (the fold
        number), which pass through the steps and come back beside the
        features from the same query, with the target under `TARGET`. The
        training rows are cross-fitted; the rows `held` is true for (those
        the fold holds out) take what was learned on all training rows.
        Nothing is kept on the pipeline.
        """
        steps, _ = self._modelled()
        con = connection()
        _, _, known = self._learn(con, learn_from, steps, fold)
        schema = [c for c in _schema(data) if c[0] != POSITION]
        prepared = self._features(Source(data, (), schema), target, keep)
        data_sql = prepared.relation.sql_query()
        stages, out, _ = self._stages(
            con, data_sql, prepared.schema, steps, known,
            aside=_aside_of(prepared), cross=True, held=held,
        )  # fmt: skip
        columns = [c for c, _ in out]
        sql = build(data_sql, stages)
        return take(con.sql(sql), feed, columns, [TARGET, *keep])

    def _train(self, source: Source, target: str, feed: str) -> "Pipeline":
        """Train on data already read, as `train` describes."""
        steps, model = self._modelled()
        con = connection()
        _source_sql(con, source)
        prepared = self._features(source, target)
        the_plan, runs, known = self._learn(con, prepared, steps)
        # The feeding query reads the data the steps learned from; the target
        # passes through every stage untouched (as `TARGET`, so no created
        # name is numbered against it), so it is fetched with its own row's
        # features, and a target step's rows are cross-fitted.
        data_sql = prepared.relation.sql_query()
        stages, out, types = self._stages(
            con, data_sql, prepared.schema, steps, known,
            aside=_aside_of(prepared), cross=True,
        )  # fmt: skip
        columns = [c for c, _ in out]
        sql = build(data_sql, stages)
        x, aside = take(con.sql(sql), feed, columns, [TARGET])
        y = target_values(aside[TARGET], target)
        # All or nothing: until the model is fitted, the pipeline keeps what
        # it had. A fit that fails may leave the model half changed, so the
        # pipeline then counts as untrained.
        try:
            model.estimator.fit(x, y)
        except BaseException:
            self._feed = None
            raise
        self._commit(steps, known, types, columns, stages)
        self._target = target
        # The model is a reader (ADR 0018): the feeding query belongs to the
        # feed run, after its learn statement when that run learned.
        if runs and runs[-1][0] == the_plan.feed_run:
            runs[-1][1].statements.append(sql)
        else:
            runs.append((the_plan.feed_run, Run([sql])))
        self._feed = feed
        self.runs_ = [run for _, run in runs]
        return self

    def predict(self, data: object, out: str | Output | None = None) -> Any:  # noqa: ANN401  (the form `out` names)
        """Prepare data with the learned values and predict with the model.

        One query prepares the data, its rows numbered in the order they are
        read; the model's predictions are sorted back by that number, so row
        ``i`` of the result is the prediction for row ``i`` of the input.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
            It may hold the target column too; it is not a feature.
        out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
            What to hand back, as for `apply`.

        Returns
        -------
        object
            A `duckdb.DuckDBPyRelation` of one column, ``prediction``, one
            row per input row in the input's order; or that in the form
            `out` names.

        Raises
        ------
        SqlearnError
            If the pipeline has no model or has not been trained, the data
            lacks a column the model was trained on or has a column named
            ``__sqlearn_row``, the connection does not preserve insertion
            order, or the model does not return one value per row.
        StepError
            As for `apply`.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> data = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [0, 0, 1, 1]})
        >>> pipe = sq.Pipeline(
        ...     [("scale", sq.scale.standard()), ("model", LogisticRegression())]
        ... )
        >>> pipe.train(data, target="y").predict(data, out="numpy")[
        ...     "prediction"
        ... ].tolist()
        [0, 0, 1, 1]
        """
        steps, model = self._modelled()
        if self._feed is None or self._entries is None:
            msg = (
                "this pipeline has not been trained yet, so its model cannot "
                "predict. Fix: call train(data, target=...) first."
            )
            raise SqlearnError(msg)
        source = read(data)
        con = connection()
        _source_sql(con, source)
        source = _without(source, self._target)
        _check_numbering(con, source.schema)
        numbered = number_rows(source.relation.sql_query(), _ROW)
        schema = describe(con, numbered, [])
        stages, reaching, _ = self._stages(
            con, numbered, schema, steps, self._entries, self._types,
            self._names,
        )  # fmt: skip
        have = {c for c, _ in reaching}
        missing = [c for c in self._columns_out if c not in have]
        if missing:
            names = ", ".join(repr(c) for c in missing)
            msg = (
                f"the data has no column {names}, which the model was trained "
                "on; a model needs every column it learned from. Fix: pass data "
                "with the same columns as at train."
            )
            raise SqlearnError(msg)
        sql = build(numbered, stages)
        x, aside = take(con.sql(sql), self._feed, self._columns_out, [_ROW])
        rel = received(con, aside[_ROW], model.estimator.predict(x))
        self.runs_ = [Run([sql])]
        return to_output(rel, out if out is not None else get_config().out)
