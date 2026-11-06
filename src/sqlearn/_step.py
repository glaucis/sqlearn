"""The step contract: what a step learns, what it applies, and how it is classed."""

import inspect
from collections.abc import Mapping
from typing import ClassVar, Literal

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DuckDBPyType

from sqlearn._selectors import Schema, Selector, to_selector

__all__ = ["KINDS", "Learned", "Step", "classify", "output_names"]

KINDS: dict[tuple[type, tuple[tuple[str, str], ...]], str] = {}
"""Session cache of ``classify`` answers, keyed by class and settings."""


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

    Attributes
    ----------
    static : bool or None
        Declared class; None means classify by trying `apply`.
    dynamic : bool or None
        Declared dynamic when True, trusted as `static` is; declaring both
        `static` and `dynamic` as True is refused.
    creates : DuckDBPyType or None
        The type of the columns a dynamic step creates.
    changes_rows : bool
        True for a step that changes the rows (a filter, sampling); every
        later step then depends on it. No step does yet.

    Examples
    --------
    >>> import sqlearn as sq
    >>> class Double(sq.Step):
    ...     def apply(self, x, learned):
    ...         return x * 2
    >>> Double(cols="a").settings()
    {'cols': 'a', 'keep': False, 'suffix': None}
    """

    static: ClassVar[bool | None] = None
    dynamic: ClassVar[bool | None] = None
    creates: ClassVar[DuckDBPyType | None] = None
    changes_rows: ClassVar[bool] = False

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        self.cols = cols
        self.keep = keep
        self.suffix = suffix

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
    ) -> Expression | Mapping[str, Expression]:
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
            One expression replacing the column, or named new columns.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> x = duckdb.ColumnExpression("a")
        >>> str(sq.Step().apply(x, sq._step.Learned.values({})))
        '"a"'
        """
        return x

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
        {'cols': None, 'keep': True, 'suffix': None}
        """
        params = inspect.signature(type(self).__init__).parameters
        return {
            name: getattr(self, name)
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


def _key(step: Step) -> tuple[type, tuple[tuple[str, str], ...]]:
    return type(step), tuple((k, repr(v)) for k, v in step.settings().items())


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


def output_names(
    step_name: str,
    column: str,
    result: Expression | Mapping[str, Expression],
    keep: bool,
    suffix: str | None,
) -> dict[str, Expression]:
    """Name the output expressions of a step for one input column.

    Parameters
    ----------
    step_name : str
        The step's name, used as the default suffix.
    column : str
        The input column.
    result : duckdb.Expression or mapping of str to duckdb.Expression
        What ``apply`` returned.
    keep : bool
        Whether the input column is kept, so the output needs a new name.
    suffix : str, optional
        Suffix replacing `step_name` when `keep` is True.

    Returns
    -------
    dict of str to duckdb.Expression
        One expression is named ``column`` (or ``column_suffix`` with
        `keep`); a mapping keeps its own names.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._step import output_names
    >>> e = duckdb.ColumnExpression("a")
    >>> list(output_names("scale", "a", e, True, None))
    ['a_scale']
    """
    if isinstance(result, Expression):
        name = f"{column}_{suffix or step_name}" if keep else column
        return {name: result}
    return dict(result)
