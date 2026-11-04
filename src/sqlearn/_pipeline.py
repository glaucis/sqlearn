"""The pipeline: named steps that learn from data, then apply what they learned."""

import weakref
from collections import Counter
from collections.abc import Sequence
from typing import Any

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._compose import (
    SOURCE,
    Run,
    Stage,
    apply_sql,
    build,
    describe,
    execute,
    stage_name,
    step_stage,
)
from sqlearn._config import connection, get_config
from sqlearn._errors import SqlearnError, StepError
from sqlearn._inputs import Source, read
from sqlearn._output import Output, to_output
from sqlearn._plan import Plan, plan
from sqlearn._selectors import Schema, _is_numeric
from sqlearn._step import Step
from sqlearn._store import STORE, Entry, StepKey, step_key

__all__ = ["Pipeline", "make_pipeline"]


def _kind(dtype: DuckDBPyType) -> str:
    """Name a type's kind: every number is alike, any other type is itself."""
    return "numeric" if _is_numeric(dtype) else str(dtype)


def _bind(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    stages: list[Stage],
    name: str,
    position: int,
) -> Schema:
    """Return the columns after the last stage, naming its step if it fails."""
    try:
        return describe(con, source_sql, stages)
    except duckdb.Error as exc:
        msg = (
            f"{name} (step {position}) builds SQL that DuckDB refuses: {exc}\n"
            "Fix: check that the step's learn and apply suit the columns it "
            "is given."
        )
        raise StepError(msg, step=name, position=position) from exc


def _matched(step: Step, schema: Schema, name: str, position: int) -> list[str]:
    """Return the columns a step works on, refusing a selector matching none."""
    chosen = step.inputs(schema)
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
    steps : sequence of (str, Step)
        The named steps, in order. Names must be unique.

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
    ...         return {"mean": sq.avg(x)}
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

    def __init__(self, steps: Sequence[tuple[str, Step | object]]) -> None:
        self.steps = list(steps)
        clash = [
            n for n, count in Counter(n for n, _ in self.steps).items() if count > 1
        ]
        if clash:
            msg = (
                f"two steps are named {clash[0]!r}; each step needs its own "
                "name. Fix: rename one, or build the pipeline with make_pipeline."
            )
            raise SqlearnError(msg)
        self.runs_: list[Run] = []
        self._entries: list[Entry] | None = None
        self._types: list[dict[str, DuckDBPyType]] = []
        self._columns_out: list[str] = []

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

    def _checked(self) -> list[tuple[str, Step]]:
        steps: list[tuple[str, Step]] = []
        for i, (name, step) in enumerate(self.steps):
            if not isinstance(step, Step):
                msg = (
                    f"{name} (step {i + 1}) is a {type(step).__name__}, not a "
                    "step: learn and apply take steps only. Fix: make it a "
                    "subclass of sq.Step."
                )
                raise SqlearnError(msg)
            steps.append((name, step))
        return steps

    def learn(self, data: object) -> "Pipeline":
        """Learn every step from data, finding unchanged steps in the store.

        The data is read once. Steps go in the earliest run their inputs
        allow; a run whose steps are all in the store runs nothing.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.

        Returns
        -------
        Pipeline
            This pipeline, learned.

        Raises
        ------
        StepError
            If a step's selector matches no column, an output takes a name in
            use, or a step learns from no rows.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sqlearn._config import connection
        >>> data = connection().sql("SELECT 1 AS a")
        >>> sq.Pipeline([("copy", sq.Step())]).learn(data).runs_
        []
        """
        steps = self._checked()
        source = read(data)
        con = connection()
        source_sql = source.relation.sql_query()
        the_plan = plan(steps, source.schema)
        keys = [
            step_key(source.key, None, steps, i, the_plan.depends_on[i])
            for i in range(len(steps))
        ]
        entries: list[Entry | None] = [STORE.get(k) for k in keys]
        runs: list[Run] = []
        for r in sorted(
            {the_plan.learn_run[i] for i, e in enumerate(entries) if e is None}
        ):
            run = self._learn_run(con, source, steps, the_plan, r, entries, keys)
            if run.statements:
                runs.append(run)
        known = [e for e in entries if e is not None]
        _, schema, types = self._stages(con, source_sql, source.schema, steps, known)
        for (_, step), entry in zip(steps, known, strict=True):
            step._set_learned(_by_column(entry.values))
        self._entries = known
        self._types = types
        self._columns_out = [c for c, _ in schema]
        self.runs_ = runs
        return self

    def _learn_run(
        self,
        con: duckdb.DuckDBPyConnection,
        source: Source,
        steps: list[tuple[str, Step]],
        the_plan: Plan,
        run: int,
        entries: list[Entry | None],
        keys: list[StepKey],
    ) -> Run:
        """Learn the steps of one run missing from the store, and store them."""
        source_sql = source.relation.sql_query()
        misses = [
            i
            for i, e in enumerate(entries)
            if e is None and the_plan.learn_run[i] == run
        ]
        schema = source.schema
        previous = SOURCE
        stages: list[Stage] = []
        built: dict[int, tuple[Schema, str, list[str]]] = {}
        for i in range(max(misses) + 1):
            name, step = steps[i]
            position = i + 1
            dynamic = the_plan.apply_run[i] > the_plan.learn_run[i]
            if the_plan.learn_run[i] > run:
                # Not reached yet: a dynamic step's inputs are gone once it
                # applies, so the steps learning now must not see them.
                if dynamic and not step.keep:
                    gone = set(step.inputs(schema))
                    schema = [c for c in schema if c[0] not in gone]
                continue
            entry = entries[i]
            if entry is not None:
                stage = step_stage(
                    position, name, step, schema, previous, entry.values,
                    columns=entry.columns,
                )  # fmt: skip
            else:
                matched = _matched(step, schema, name, position)
                built[i] = (schema, previous, matched)
                stage = step_stage(
                    position, name, step, schema, previous,
                    columns=matched, applies=not dynamic,
                )  # fmt: skip
            stages.append(stage)
            previous = stage.name
            if entry is None and dynamic:
                if not step.keep:
                    schema = [c for c in schema if c[0] not in built[i][2]]
            else:
                schema = _bind(con, source_sql, stages, name, position)
        values, _, done = execute(con, source_sql, stages, produce=False)
        for i in misses:
            name, step = steps[i]
            before, prev, matched = built[i]
            learned = values.get(stage_name(i + 1, name), {})
            applied = step_stage(
                i + 1, name, step, before, prev, learned, columns=matched
            )
            entry = Entry(learned, matched, apply_sql(applied))
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
    ) -> tuple[list[Stage], Schema, list[dict[str, DuckDBPyType]]]:
        """Build every step's stage with its learned values as constants.

        Checks each step's learned columns reach it, with the kind of type
        they had at learn when `check` holds those types.
        """
        stages: list[Stage] = []
        types: list[dict[str, DuckDBPyType]] = []
        previous = SOURCE
        for i, ((name, step), entry) in enumerate(zip(steps, entries, strict=True)):
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
            stage = step_stage(
                position, name, step, schema, previous, entry.values,
                columns=entry.columns,
            )  # fmt: skip
            stages.append(stage)
            previous = stage.name
            schema = _bind(con, source_sql, stages, name, position)
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
            If the pipeline has not learned yet.
        StepError
            If the data lacks a column a step learned from, or holds it with
            another kind of type.

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
        source_sql = source.relation.sql_query()
        stages, _, _ = self._stages(
            con, source_sql, source.schema, steps, self._entries, self._types
        )
        sql = build(source_sql, stages)
        rel = con.sql(sql)
        # The relation reads the source's view (for a frame): keep the
        # source, and so the view, alive for as long as the relation is.
        weakref.finalize(rel, _hold, source)
        self.runs_ = [Run([sql])]
        return to_output(rel, out if out is not None else get_config().out)


def make_pipeline(*steps: Step | object) -> Pipeline:
    """Build a pipeline naming each step after its class, lowercased.

    Names that clash are numbered from 1 in order (``scale-1``, ``scale-2``),
    as scikit-learn's ``make_pipeline`` does.

    Parameters
    ----------
    *steps : Step
        The steps, in order.

    Returns
    -------
    Pipeline
        The pipeline.

    Examples
    --------
    >>> import sqlearn as sq
    >>> [name for name, _ in sq.make_pipeline(sq.Step(), sq.Step()).steps]
    ['step-1', 'step-2']
    """
    names = [type(s).__name__.lower() for s in steps]
    counts = Counter(names)
    seen: Counter[str] = Counter()
    named: list[tuple[str, Step | object]] = []
    for name, step in zip(names, steps, strict=True):
        if counts[name] > 1:
            seen[name] += 1
            name = f"{name}-{seen[name]}"
        named.append((name, step))
    return Pipeline(named)
