"""The learning store: what each step learned, kept so nothing is learned twice."""

import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlearn._inputs import DataKey
from sqlearn._step import _FUNCTIONS, Step

__all__ = ["STORE", "Entry", "FoldKey", "StepKey", "Store", "step_key"]

FoldKey = tuple[int, int, int]
"""A fold as ``(n, seed, k)``: the number of folds, the seed, the fold index."""

StepKey = tuple[
    DataKey,
    FoldKey | None,
    tuple[tuple[str, type, str, tuple[object, ...]], ...],
    tuple[str, ...],
]
"""The data, the fold, ``(name, class, dotted path, settings)`` per step, and
the columns the step reads."""

_PLAIN = (str, int, float, bool, bytes, type(None))


def _freeze(value: object) -> object:
    """Return a deterministic, hashable form of a setting value."""
    if isinstance(value, _PLAIN):
        return (type(value).__qualname__, value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, _FUNCTIONS):
        module = getattr(value, "__module__", None)
        name = getattr(value, "__qualname__", type(value).__qualname__)
        return (value, f"{module}.{name}")
    return repr(value)


def step_key(
    data: DataKey,
    fold: FoldKey | None,
    steps: Sequence[tuple[str, Step]],
    index: int,
    depends_on: frozenset[int],
    inputs: Sequence[str] = (),
) -> StepKey:
    """Build the store key of one step (ADR 0024).

    The key holds the data, the fold, the name, class and settings of the
    step and of every step it depends on, in pipeline order, and the columns
    the step's selector resolved to, so a step reading other columns never
    finds another's entry. The class is the
    class object itself (so a redefined class gets a new key) beside its dotted
    path. Settings are sorted by name; plain values are kept with their type
    (so ``True`` and ``1`` differ), selectors and models by their ``repr``,
    lists as tuples.

    Parameters
    ----------
    data : tuple
        The data key of the input.
    fold : tuple of int, optional
        ``(n, seed, k)`` for a fold of a cross-validation, else None.
    steps : sequence of tuple of (str, Step)
        The named steps of the pipeline.
    index : int
        The position of the step the key is for.
    depends_on : frozenset of int
        The positions of the steps whose output it reads.
    inputs : sequence of str, default ()
        The columns the step's selector resolved to, in order.

    Returns
    -------
    tuple
        A hashable key.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn._store import step_key
    >>> steps = [("step", sq.Step(cols="a"))]
    >>> key = step_key(("t",), None, steps, 0, frozenset())
    >>> key[2][0][0], key[2][0][2]
    ('step', 'sqlearn._step.Step')
    """
    chain = tuple(
        (
            steps[i][0],
            type(steps[i][1]),
            f"{type(steps[i][1]).__module__}.{type(steps[i][1]).__qualname__}",
            tuple(
                sorted((k, _freeze(v)) for k, v in steps[i][1].settings().items()),
            ),
        )
        for i in sorted({index, *depends_on})
    )
    return (data, fold, chain, tuple(inputs))


@dataclass(frozen=True)
class Entry:
    """What one step learned (read-only once built).

    Attributes
    ----------
    values : dict of str to dict of str to object
        Learned name, then column, to value: for a step learning from the
        target, what it learned on all rows (``"all"``).
    columns : list of str
        The columns the step's selector matched.
    apply_sql : str
        The SQL text of the step's apply stage.
    folds : dict of str to dict
        For a step learning from the target, per inner fold (``"0"`` to
        ``"k-1"``), what it learned on the rows outside that fold, as
        `values`; empty for any other step.

    Examples
    --------
    >>> from sqlearn._store import Entry
    >>> Entry({"mean": {"a": 1.0}}, ["a"], "SELECT 1").columns
    ['a']
    """

    values: dict[str, dict[str, object]]
    columns: list[str]
    apply_sql: str
    folds: dict[str, dict[str, dict[str, object]]] = field(default_factory=dict)


def _size(obj: object) -> int:
    total = sys.getsizeof(obj)
    if isinstance(obj, dict):
        total += sum(_size(k) + _size(v) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        total += sum(_size(v) for v in obj)
    return total


class Store:
    """Learned values by key. It holds keys, values and SQL text, never data.

    Attributes
    ----------
    learns : collections.Counter of str
        How many times each step name was learned, for tests. `put` is the
        "learned" event: it adds one to the name of the key's last step.

    Examples
    --------
    >>> from sqlearn._store import Entry, Store
    >>> store = Store()
    >>> key = (("t",), None, (("scale", object, "o.Scale", ()),), ("a",))
    >>> store.put(key, Entry({}, [], ""))
    >>> len(store), store.learns["scale"]
    (1, 1)
    """

    def __init__(self) -> None:
        self._entries: dict[StepKey, Entry] = {}
        self.learns: Counter[str] = Counter()

    def get(self, key: StepKey) -> Entry | None:
        """Return the entry stored under a key, or None.

        Parameters
        ----------
        key : tuple
            A key from `step_key`.

        Returns
        -------
        Entry or None
            The entry, if present.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> Store().get((("t",), None, (), ())) is None
        True
        """
        return self._entries.get(key)

    def put(self, key: StepKey, entry: Entry) -> None:
        """Store an entry and count one learn for the key's step.

        Parameters
        ----------
        key : tuple
            A key from `step_key`; its last chain item is the step itself
            (dependencies always have lower indices) and names it.
        entry : Entry
            What was learned.

        Examples
        --------
        >>> from sqlearn._store import Entry, Store
        >>> store = Store()
        >>> key = (("t",), None, (("s", object, "o.S", ()),), ())
        >>> store.put(key, Entry({}, [], ""))
        >>> store.learns
        Counter({'s': 1})
        """
        self._entries[key] = entry
        if key[2]:
            self.learns[key[2][-1][0]] += 1

    def size_bytes(self) -> int:
        """Estimate the memory held, in bytes.

        An estimate: the sum of ``sys.getsizeof`` over the keys and entries,
        followed through dicts, lists and tuples.

        Returns
        -------
        int
            The estimated size.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> Store().size_bytes() >= 0
        True
        """
        return sum(
            _size(k)
            + _size(e.values)
            + _size(e.columns)
            + _size(e.apply_sql)
            + _size(e.folds)
            for k, e in self._entries.items()
        )

    def __len__(self) -> int:
        """Return the number of entries.

        Returns
        -------
        int
            The entry count.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> len(Store())
        0
        """
        return len(self._entries)

    def clear(self) -> None:
        """Forget every entry and count.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> Store().clear()
        """
        self._entries.clear()
        self.learns.clear()


STORE = Store()
"""The process-wide store."""
