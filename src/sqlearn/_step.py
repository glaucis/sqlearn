"""The step contract: what a step learns, what it applies, and how it is classed."""

import functools
import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from typing import ClassVar, Literal

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn._selectors import Schema, Selector, to_selector

__all__ = [
    "KINDS",
    "Learned",
    "Output",
    "RowOutput",
    "Step",
    "apply_rows",
    "classify",
    "output_labels",
    "row_outputs",
    "row_owners",
]

KINDS: dict[tuple[type, tuple[tuple[str, object], ...]], str] = {}
"""Session cache of ``classify`` answers, keyed by class and settings."""

Output = Expression | Mapping[str, Expression] | Sequence[tuple[str, Expression]]
"""What ``apply`` returns: one expression, or new columns keyed by label."""

RowOutput = Mapping[str, Expression] | Sequence[tuple[str, Expression]]
"""What ``apply_row`` returns: the output columns, keyed by name."""


class Learned:
    """The values a step learned for one column, read by attribute.

    Build one with `Learned.placeholders` (to inspect a step) or
    `Learned.values` (to apply it). The names read are recorded in order.

    Parameters
    ----------
    items : mapping of str to object
        The value to serve for each learned name.

    Attributes
    ----------
    accessed : list of str
        The names read so far, in order.

    Examples
    --------
    >>> from sqlearn._step import Learned
    >>> learned = Learned.values({"mean": 2.0, "cities": ["a", "b"]})
    >>> learned.cities
    ['a', 'b']
    >>> learned.accessed
    ['cities']
    """

    def __init__(self, items: Mapping[str, object]) -> None:
        self._items = dict(items)
        self._raw: dict[str, object] = {}
        self.accessed: list[str] = []

    @classmethod
    def placeholders(cls, stage: str, names: Mapping[str, str]) -> "Learned":
        """Build a `Learned` whose values are references into a learn stage.

        Parameters
        ----------
        stage : str
            The name of the stage that holds the learned values.
        names : mapping of str to str
            Each learned name and the internal column that stores it.

        Returns
        -------
        Learned
            Each name reads as ``ColumnExpression(stage, internal_name)``.

        Examples
        --------
        >>> from sqlearn._step import Learned
        >>> learned = Learned.placeholders("l03_scale", {"mean": "v0"})
        >>> str(learned.mean)
        '"l03_scale"."v0"'
        """
        return cls(
            {k: duckdb.ColumnExpression(stage, v) for k, v in names.items()},
        )

    @classmethod
    def values(cls, values: Mapping[str, object]) -> "Learned":
        """Build a `Learned` from concrete values.

        Parameters
        ----------
        values : mapping of str to object
            The learned values; lists stay lists, scalars become constants.

        Returns
        -------
        Learned
            Scalars read as ``ConstantExpression``, lists as Python lists.

        Examples
        --------
        >>> from sqlearn._step import Learned
        >>> str(Learned.values({"mean": 2}).mean)
        '2'
        """
        learned = cls(
            {
                k: v if isinstance(v, list) else duckdb.ConstantExpression(v)
                for k, v in values.items()
            },
        )
        learned._raw = dict(values)
        return learned

    def raw(self, name: str) -> object:
        """Return a learned value as the Python object it was fetched as.

        Reading it is not recorded in `accessed`. Use it to check a value
        (None, NaN, infinity) without depending on how DuckDB prints it.

        Parameters
        ----------
        name : str
            The learned name.

        Returns
        -------
        object
            The Python value when built with `Learned.values`; else the
            expression (a placeholder), which is not yet a number.

        Examples
        --------
        >>> from sqlearn._step import Learned
        >>> Learned.values({"mean": None}).raw("mean") is None
        True
        >>> Learned.placeholders("l01_s", {"mean": "v0"}).raw("mean") is None
        False
        """
        if name in self._raw:
            return self._raw[name]
        return self._items[name]

    def __getattr__(self, name: str) -> object:
        if name.startswith("_") or name not in self._items:
            raise AttributeError(f"nothing named {name!r} was learned")
        self.accessed.append(name)
        return self._items[name]


class Step:
    """Base class of every step: learn from the data, then apply.

    Override `learn` to compute values (SQL aggregates, per column) and `apply`
    to build the output (an expression per column, using what was learned). A
    step whose output columns do not depend on learned values is static;
    otherwise it is dynamic. Leave `static` and `dynamic` as None to have
    sqlearn find out.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns the step works on; None means every column.
    keep : bool, default False
        Keep the input column and add the output beside it.
    suffix : str, optional
        Suffix for the output column when `keep` is True.
    learn : callable, optional
        ``learn(x)`` returning a mapping of learned name to aggregate; it
        replaces the `learn` method for this step.
    apply : callable, optional
        ``apply(x, learned)`` (or ``apply(x)`` when nothing is learned)
        returning an expression or a mapping; it replaces the `apply` method
        for this step.

    Attributes
    ----------
    static : bool or None
        Declared class; None means classify by trying `apply`. Set on the
        class, or on the instance in ``__init__`` when the settings decide.
    dynamic : bool or None
        Declared dynamic when True, trusted as `static` is; declaring both
        `static` and `dynamic` as True is refused.
    creates : DuckDBPyType or None
        The type of the columns a dynamic step creates.
    copies_inputs : bool
        True for a dynamic step with ``keep`` that also creates a copy of each
        input, of the input's own type (``creates`` then types only the
        other columns it creates): ``sq.impute`` with a fill value, ``keep``
        and the indicator creates the filled copy beside the flag.
    keeps_inputs : bool
        True for a dynamic step whose outputs include each input under its
        own name (the label ``""``), of the same kind (numbers stay numbers,
        text stays text), as ``sq.impute.indicator`` passes its inputs
        through: they are not taken away, and a later step reading them
        waits for the run after it learns. False (the default) for a dynamic
        step that replaces its inputs, as a one-hot encoder does.
    changes_rows : bool
        True for a step that changes the rows (a filter, sampling); every
        later step then depends on it. No step does yet.
    names_are_labels : bool
        True (the default) when the keys of a mapping `apply` returns are
        labels, each creating the column ``<column>_<label>``; False when they
        are the full names of the new columns.
    rowwise : bool
        True for a step whose outputs read the whole row: it defines
        `apply_row`, called once with every selected column, instead of
        `apply`. `learn` stays per column.
    uses_target : bool
        True for a step that learns from the target: its `learn` is
        ``learn(x, y)``, given the target as `y`; it has the settings ``cv``
        (the number of inner folds) and ``seed``, and turns what it fetched
        into the values for all rows and for each inner fold's complement in
        `derive`. Such a step ends its run, and its `apply` returns one
        expression, a DOUBLE.

    Examples
    --------
    >>> import sqlearn as sq
    >>> class Double(sq.Step):
    ...     def apply(self, x, learned):
    ...         return x * 2
    >>> Double(cols="a").settings()
    {'cols': 'a', 'keep': False, 'suffix': None, 'learn': None, 'apply': None}

    A step without a subclass, from callables:

    >>> ln = sq.Step(apply=lambda x: x + 1, cols="a")
    >>> str(ln.apply(sq._step.duckdb.ColumnExpression("a"), None))
    '("a" + 1)'
    """

    # Not ClassVar: a step whose class depends on its settings sets these on
    # the instance in `__init__` (sq.impute with indicator=True is dynamic).
    static: bool | None = None
    dynamic: bool | None = None
    creates: DuckDBPyType | None = None
    copies_inputs: bool = False
    keeps_inputs: bool = False
    changes_rows: ClassVar[bool] = False
    names_are_labels: ClassVar[bool] = True
    rowwise: ClassVar[bool] = False
    uses_target: ClassVar[bool] = False

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
        *,
        learn: Callable[[Expression], Mapping[str, Expression]] | None = None,
        apply: Callable[..., Output] | None = None,
    ) -> None:
        self.cols = cols
        self.keep = keep
        self.suffix = suffix
        self._callables = {"learn": learn, "apply": apply}
        if learn is not None:
            self.__dict__["learn"] = learn
        if apply is not None:
            self.__dict__["apply"] = _with_learned(apply)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Say what to learn from a column, as SQL aggregates.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            Learned name to aggregate. The default learns nothing.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> sq.Step().learn(duckdb.ColumnExpression("a"))
        {}
        """
        empty: dict[str, Expression] = {}
        return empty

    def apply(
        self,
        x: Expression,
        learned: Learned,
    ) -> Output:
        """Say what to produce from a column, using what was learned.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for this column.

        Returns
        -------
        duckdb.Expression or mapping of str to duckdb.Expression
            One expression replacing the column, or new columns keyed by
            label: ``"low"`` creates ``<column>_low`` and ``""`` is the
            column itself. Names that clash are numbered (ADR 0035). When
            two outputs share a label, return a sequence of
            ``(label, expression)`` pairs instead of a mapping.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> x = duckdb.ColumnExpression("a")
        >>> str(sq.Step().apply(x, sq._step.Learned.values({})))
        '"a"'
        """
        return x

    def row_values(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
    ) -> Mapping[str, Expression]:
        """Say what a whole-row step computes once per row, before `apply_row`.

        A value several outputs share (a row's norm, say) is computed once
        here, in a projection before the outputs, instead of being written
        into each output: the SQL then grows with the number of columns, not
        its square.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            Every selected column, by name, in order.
        learned : mapping of str to Learned
            The values learned for each column, by name.

        Returns
        -------
        mapping of str to duckdb.Expression
            Name to value. The default computes nothing. `apply_row` gets a
            reference to each in its ``values``.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> sq.Step().row_values({"a": duckdb.ColumnExpression("a")}, {})
        {}
        """
        empty: dict[str, Expression] = {}
        return empty

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
        values: Mapping[str, Expression],
    ) -> RowOutput:
        """Say what to produce from the whole row, for a step with ``rowwise``.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            Every selected column, by name, in order.
        learned : mapping of str to Learned
            The values learned for each column, by name.
        values : mapping of str to duckdb.Expression
            A reference to each value `row_values` returned, by its name
            (empty when it returns none).

        Returns
        -------
        mapping of str to duckdb.Expression or sequence of (str, duckdb.Expression)
            The output columns, replacing the selected ones. The first key
            that names a selected column takes its place
            (``<column>_<suffix>`` beside it with `keep`); any other key
            follows the last selected column. Each key is named as a column
            with the label ``""`` (or the suffix with `keep`) unless
            `names_are_labels` is False, when it is the full name. Names that
            clash are numbered (ADR 0035). When two outputs share a name,
            return a sequence of ``(name, expression)`` pairs instead of a
            mapping.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> xs = {"a": duckdb.ColumnExpression("a")}
        >>> {k: str(e) for k, e in sq.Step().apply_row(xs, {}, {}).items()}
        {'a': '"a"'}
        """
        return dict(xs)

    def derive(
        self, values: Mapping[str, object], k: int
    ) -> dict[str, dict[str, object]]:
        """Turn what a target step fetched for one column into its learned values.

        Called once per column after the learn statement, for a step with
        `uses_target`: `values` holds what its `learn` aggregates returned
        (learned name to value). The step returns its learned values for all
        rows, under ``"all"``, and for each inner fold's complement, under
        ``"0"`` to ``str(k - 1)``: `apply` is given the first for new data,
        and each training row the values of its own fold.

        Parameters
        ----------
        values : mapping of str to object
            Learned name to the value fetched.
        k : int
            The number of inner folds (the step's ``cv``).

        Returns
        -------
        dict of str to dict of str to object
            ``"all"``, ``"0"``, ... to learned name to value. The default
            learns no folds apart: every key holds `values` (no
            cross-fitting); a step cross-fits by learning grouped statistics
            (`sqlearn._expr.target_stats`) and overriding this.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.Step().derive({"mean": 1.0}, 2)
        {'all': {'mean': 1.0}, '0': {'mean': 1.0}, '1': {'mean': 1.0}}
        """
        keys = ["all", *(str(i) for i in range(k))]
        return {key: dict(values) for key in keys}

    def default_name(self) -> str:
        """Return the name this step gets in a pipeline built from a plain list.

        A group's step returns the shortcut its settings match, else the
        group's name; the base step returns "step".

        Returns
        -------
        str
            The name.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.Step().default_name()
        'step'
        """
        return "step"

    def learned(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Hear what the step learned, once per ``learn`` or ``train``.

        The pipeline calls it once for each ``learn`` or ``train`` (and for a
        search's final training, not for each fold), after the values are
        known and kept on the step, whether computed or found in the store.
        Override it to say something about them, such as a warning; it
        changes nothing. The default does nothing.

        Parameters
        ----------
        values : mapping of str to mapping of str to object
            Column, then learned name, to the value learned.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.Step().learned({"a": {"mean": 2.0}}) is None
        True
        """

    def settings(self) -> dict[str, object]:
        """Return the ``__init__`` parameters with their current values.

        Returns
        -------
        dict of str to object
            Each parameter (except ``self``) with the value of the attribute
            of the same name.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.Step(keep=True).settings()
        {'cols': None, 'keep': True, 'suffix': None, 'learn': None, 'apply': None}
        """
        params = inspect.signature(type(self).__init__).parameters
        given = self.__dict__.get("_callables", {})
        return {
            name: given.get(name) if name in given else getattr(self, name)
            for name, p in params.items()
            if name != "self" and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        }

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns this step works on, in schema order.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The columns chosen by ``cols``; every column when it is None.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import INTEGER, VARCHAR
        >>> schema = [("a", INTEGER), ("b", VARCHAR)]
        >>> sq.Step(cols=sq.cols.numeric()).inputs(schema)
        ['a']
        """
        if self.cols is None:
            return [name for name, _ in schema]
        return to_selector(self.cols).resolve(schema)

    def _set_learned(self, values: dict[str, dict[str, object]]) -> None:
        self.__dict__["_learned"] = values

    def __getattr__(self, name: str) -> object:
        if name.endswith("_") and not name.startswith("_"):
            learned = self.__dict__.get("_learned")
            if learned is None:
                raise AttributeError(
                    f"{name!r} is read after the step has learned; "
                    "run learn on data first",
                )
            key = name[:-1]
            found = {col: vals[key] for col, vals in learned.items() if key in vals}
            if not found:
                known = sorted({f"{k}_" for vals in learned.values() for k in vals})
                raise AttributeError(
                    f"{type(self).__name__} learned no value called {key!r}, so "
                    f"it has no {name!r}; it learned {', '.join(known) or 'nothing'}. "
                    "Fix: check the spelling.",
                )
            return found
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}",
        )


_FUNCTIONS = (
    types.FunctionType,
    types.MethodType,
    types.BuiltinFunctionType,
    functools.partial,
)


class _DropLearned:
    """An ``apply`` of one argument, called with ``(x, learned)``."""

    def __init__(self, fn: Callable[..., Output]) -> None:
        self.fn = fn

    def __call__(
        self,
        x: Expression,
        learned: Learned,
    ) -> Output:
        return self.fn(x)


def _with_learned(
    fn: Callable[..., Output],
) -> Callable[..., Output]:
    """Wrap an ``apply`` callable so it may leave out ``learned``."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return fn
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return fn
    positional = [
        p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return _DropLearned(fn) if len(positional) == 1 else fn


class _Same:
    """A setting compared by identity, keeping the object alive while keyed."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Same) and other.value is self.value

    def __hash__(self) -> int:
        return id(self.value)


def _by_identity(value: object) -> bool:
    """Whether a setting must be keyed by itself, not by its repr.

    A function's repr, and the default repr of any object, hold an address
    that can be reused once the object is collected: a later object could
    share the repr. Aggregates and selectors have reprs of their own.
    """
    return isinstance(value, _FUNCTIONS) or type(value).__repr__ is object.__repr__


def _setting_key(value: object) -> object:
    """Return a setting's key: itself when keyed by identity, else its repr."""
    if isinstance(value, _FUNCTIONS):
        return value
    return _Same(value) if _by_identity(value) else repr(value)


def _key(step: Step) -> tuple[type, tuple[tuple[str, object], ...]]:
    return type(step), tuple((k, _setting_key(v)) for k, v in step.settings().items())


def classify(step: Step, schema: Schema) -> Literal["static", "dynamic"]:
    """Say whether a step is static or dynamic.

    The declared ``static`` or ``dynamic`` is trusted. Otherwise ``apply`` is
    called on the first input column with placeholders for what ``learn``
    returns: getting one expression back means static; a failure (DuckDB
    raises ``TypeError`` when a placeholder is looped over or tested)
    or named columns back means the output depends on learned values, so
    dynamic. A whole-row step's ``apply_row`` is called on every input: it
    is static unless it fails. Answers are cached per class and settings in `KINDS`.

    Parameters
    ----------
    step : Step
        The step to classify.
    schema : list of (str, DuckDBPyType)
        The columns reaching the step.

    Returns
    -------
    {"static", "dynamic"}
        The step's class.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._step import classify
    >>> from duckdb.sqltypes import INTEGER
    >>> classify(sq.Step(), [("a", INTEGER)])
    'static'
    """
    if step.dynamic:
        return "dynamic"
    if step.static is not None:
        return "static" if step.static else "dynamic"
    key = _key(step)
    if key not in KINDS:
        KINDS[key] = _inspect(step, schema)
    return "static" if KINDS[key] == "static" else "dynamic"


def row_outputs(step: Step, names: Sequence[str]) -> list[str]:
    """Return the output keys of a whole-row step, from placeholders.

    Parameters
    ----------
    step : Step
        A step with ``rowwise``.
    names : sequence of str
        The selected columns.

    Returns
    -------
    list of str
        The keys `apply_row` returns, in order.

    Raises
    ------
    Exception
        Whatever `learn` or `apply_row` raises with placeholders: a step whose
        outputs depend on learned values (dynamic) cannot be read this way.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._step import row_outputs
    >>> row_outputs(sq.Step(), ["a", "b"])
    ['a', 'b']
    """
    xs = {name: duckdb.ColumnExpression(name) for name in names}
    learned: dict[str, Learned] = {}
    for name, x in xs.items():
        slots = {key: f"v{i}" for i, key in enumerate(step.learn(x))}
        learned[name] = Learned.placeholders("learn", slots)
    _, outputs = apply_rows(
        step, xs, learned, lambda _, name: duckdb.ColumnExpression(name)
    )
    return [name for name, _ in outputs]


def row_owners(selected: Sequence[str], keys: Sequence[str]) -> list[str]:
    """Return the selected column each output of a whole-row step belongs to.

    The first output named after a selected column takes its place; any
    other, a second output of that name too, follows the last selected
    column.

    Parameters
    ----------
    selected : sequence of str
        The selected columns, in order.
    keys : sequence of str
        The names `apply_row` returned, in order.

    Returns
    -------
    list of str
        The owning column of each output, in the order of `keys`.

    Examples
    --------
    >>> from sqlearn._step import row_owners
    >>> row_owners(["a", "a^2"], ["a", "a^2", "a^2", "a*a^2"])
    ['a', 'a^2', 'a^2', 'a^2']
    >>> row_owners(["a^2", "a"], ["a^2", "a", "a^2"])
    ['a^2', 'a', 'a']
    """
    free = set(selected)
    owners: list[str] = []
    for key in keys:
        if key in free:
            free.discard(key)
            owners.append(key)
        else:
            owners.append(selected[-1])
    return owners


def apply_rows(
    step: Step,
    xs: Mapping[str, Expression],
    learned: Mapping[str, Learned],
    refer: Callable[[int, str], Expression],
) -> tuple[dict[str, Expression], list[tuple[str, Expression]]]:
    """Call a whole-row step's `row_values`, then its `apply_row`.

    Parameters
    ----------
    step : Step
        A step with ``rowwise``.
    xs : mapping of str to duckdb.Expression
        The selected columns, by name.
    learned : mapping of str to Learned
        Each column's learned values.
    refer : callable
        ``refer(i, name)`` returns the reference to the i-th row value.

    Returns
    -------
    tuple of (dict, list of (str, duckdb.Expression))
        The row values by name, and the outputs `apply_row` returned, as
        ``(name, expression)`` pairs in order.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> from sqlearn._step import apply_rows
    >>> xs = {"a": duckdb.ColumnExpression("a")}
    >>> values, outputs = apply_rows(sq.Step(), xs, {}, lambda i, n: xs["a"])
    >>> values, [name for name, _ in outputs]
    ({}, ['a'])
    """
    values = dict(step.row_values(xs, learned))
    refs = {name: refer(i, name) for i, name in enumerate(values)}
    result = step.apply_row(xs, learned, refs)
    pairs: list[tuple[str, Expression]] = (
        list(result.items()) if isinstance(result, Mapping) else list(result)
    )
    return values, pairs


def _inspect(step: Step, schema: Schema) -> Literal["static", "dynamic"]:
    chosen = step.inputs(schema)
    if step.rowwise:
        try:
            row_outputs(step, chosen)
        except Exception:  # noqa: BLE001  (any failure means the output is dynamic)
            return "dynamic"
        return "static"
    x = duckdb.ColumnExpression(chosen[0] if chosen else "x")
    try:
        names = {name: f"v{i}" for i, name in enumerate(step.learn(x))}
        result = step.apply(x, Learned.placeholders("learn", names))
    except Exception:  # noqa: BLE001  (any failure means the output is dynamic)
        return "dynamic"
    return "static" if isinstance(result, Expression) else "dynamic"


def output_labels(
    step_name: str,
    result: Output,
    keep: bool,
    suffix: str | None,
) -> list[tuple[str, Expression]]:
    """Label the output expressions of a step for one input column.

    Parameters
    ----------
    step_name : str
        The step's name, the default label of a kept column's output.
    result : duckdb.Expression, mapping or sequence of (str, duckdb.Expression)
        What ``apply`` returned.
    keep : bool
        Whether the input column is kept, so the output needs a new name.
    suffix : str, optional
        Label replacing `step_name` when `keep` is True.

    Returns
    -------
    list of (str, duckdb.Expression)
        ``(label, expression)`` per output, in order. One expression is
        labelled ``""``, the column itself (or `suffix` or `step_name` with
        `keep`); a mapping or a sequence of pairs keeps its own labels, its
        ``""`` too becoming `suffix` or `step_name` with `keep`, since the
        kept input is then the column itself.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._step import output_labels
    >>> e = duckdb.ColumnExpression("a")
    >>> [label for label, _ in output_labels("scale", e, True, None)]
    ['scale']
    """
    if isinstance(result, Expression):
        return [((suffix or step_name) if keep else "", result)]
    pairs: list[tuple[str, Expression]] = (
        list(result.items()) if isinstance(result, Mapping) else list(result)
    )
    if keep:
        return [(label or suffix or step_name, e) for label, e in pairs]
    return pairs
