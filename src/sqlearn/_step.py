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

__all__ = ["KINDS", "Learned", "Output", "Step", "classify", "output_labels"]

KINDS: dict[tuple[type, tuple[tuple[str, object], ...]], str] = {}
"""Session cache of ``classify`` answers, keyed by class and settings."""

Output = Expression | Mapping[str, Expression] | Sequence[tuple[str, Expression]]
"""What ``apply`` returns: one expression, or new columns keyed by label."""


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
    changes_rows : bool
        True for a step that changes the rows (a filter, sampling); every
        later step then depends on it. No step does yet.
    names_are_labels : bool
        True (the default) when the keys of a mapping `apply` returns are
        labels, each creating the column ``<column>_<label>``; False when they
        are the full names of the new columns.

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
    changes_rows: ClassVar[bool] = False
    names_are_labels: ClassVar[bool] = True

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


def _key(step: Step) -> tuple[type, tuple[tuple[str, object], ...]]:
    # A function is keyed by the object itself: its repr holds an address that
    # can be reused once the function is collected.
    return type(step), tuple(
        (k, v if isinstance(v, _FUNCTIONS) else repr(v))
        for k, v in step.settings().items()
    )


def classify(step: Step, schema: Schema) -> Literal["static", "dynamic"]:
    """Say whether a step is static or dynamic.

    The declared ``static`` or ``dynamic`` is trusted. Otherwise ``apply`` is
    called on the first input column with placeholders for what ``learn``
    returns: getting one expression back means static; a failure (DuckDB
    raises ``TypeError`` when a placeholder is looped over or tested)
    or named columns back means the output depends on learned values, so
    dynamic. Answers are cached per class and settings in `KINDS`.

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


def _inspect(step: Step, schema: Schema) -> Literal["static", "dynamic"]:
    chosen = step.inputs(schema)
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
