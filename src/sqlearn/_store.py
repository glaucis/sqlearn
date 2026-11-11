"""The learning store: what each step learned, kept so nothing is learned twice."""

import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlearn._inputs import DataKey
from sqlearn._step import Step, _by_identity, _setting_key

__all__ = ["STORE", "Entry", "FoldKey", "StepKey", "Store", "step_key"]

FoldKey = tuple[tuple[object, ...], int]
"""A fold as ``(scheme key, k)``: the scheme's settings, the fold index."""

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
    if _by_identity(value):
        module = getattr(value, "__module__", None)
        name = getattr(value, "__qualname__", type(value).__qualname__)
        return (_setting_key(value), f"{module}.{name}")
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
    lists as tuples; functions and objects with the default ``repr`` (an
    address, reusable once they are collected) by themselves.

    Parameters
    ----------
    data : tuple
        The data key of the input.
    fold : tuple, optional
        ``(scheme key, k)`` for a fold of a cross-validation, else None.
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
        The SQL text of the step's apply stage, as built when it learned. It
        is informational: kept to read, and counted in the store's size, but
        nothing runs it; `apply` builds every stage again from `values`.
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
        # Entries from a saved file, by the key of the data's stable key
        # (`Source.stable`): the live key holds what only one process knows.
        self._stable: dict[StepKey, Entry] = {}
        # Each saved source's stable key and file, by its `Source.origin`,
        # until the next learn from it.
        self._saved: dict[tuple[str, ...], tuple[DataKey, str]] = {}

    def get(self, key: StepKey, stable: DataKey | None = None) -> Entry | None:
        """Return the entry stored under a key, or None.

        On a miss, and when `stable` is given, the entry a saved file put
        under the same key with the data's stable key is returned, and filed
        under `key` as well (no learn is counted).

        Parameters
        ----------
        key : tuple
            A key from `step_key`.
        stable : tuple, optional
            The data's stable key (`Source.stable`), to find an entry loaded
            from a file. Never given for a fold of a search.

        Returns
        -------
        Entry or None
            The entry, if present.

        Examples
        --------
        >>> from sqlearn._store import Entry, Store
        >>> store = Store()
        >>> store.get((("t",), None, (), ())) is None
        True
        >>> store.put_stable((("s",), None, (), ()), Entry({}, [], ""))
        >>> store.get((("t",), None, (), ()), stable=("s",)) is not None
        True
        """
        entry = self._entries.get(key)
        if entry is None and stable is not None:
            entry = self._stable.get((stable, *key[1:]))
            if entry is not None:
                self._entries[key] = entry
        return entry

    def put_stable(self, key: StepKey, entry: Entry) -> None:
        """Store an entry from a saved file under the data's stable key.

        Nothing is learned, so no learn is counted.

        Parameters
        ----------
        key : tuple
            A key from `step_key`, made with the data's stable key.
        entry : Entry
            What the step learned, as the file holds it.

        Examples
        --------
        >>> from sqlearn._store import Entry, Store
        >>> store = Store()
        >>> store.put_stable((("s",), None, (), ()), Entry({}, [], ""))
        >>> len(store), store.learns
        (0, Counter())
        """
        self._stable[key] = entry

    def remember_saved(
        self, origin: tuple[str, ...], stable: DataKey, file: str
    ) -> None:
        """Remember the data a loaded file's values were learned from.

        Parameters
        ----------
        origin : tuple
            The source's `Source.origin`.
        stable : tuple
            Its stable key when the values were learned.
        file : str
            The saved file, as `load` was given it.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> store = Store()
        >>> store.remember_saved(("file", "/d", "c.csv"), ("k", 1), "p.json")
        >>> store.changed_since_saved(("file", "/d", "c.csv"), ("k", 2))
        ('p.json', ('k', 1))
        """
        self._saved[origin] = (stable, file)

    def changed_since_saved(
        self, origin: tuple[str, ...] | None, stable: DataKey | None
    ) -> tuple[str, DataKey] | None:
        """Say whether a source learned from changed since a file was saved.

        Only the first learn from a remembered source is compared (said
        once): the source is forgotten then, changed or not, and later
        learns are new data as in any process.

        Parameters
        ----------
        origin : tuple, optional
            The source's `Source.origin`.
        stable : tuple, optional
            Its stable key now.

        Returns
        -------
        tuple of (str, tuple) or None
            The saved file and the stable key it holds, when the source is
            remembered and its key differs; else None.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> Store().changed_since_saved(None, None) is None
        True
        """
        if origin is None:
            return None
        saved = self._saved.pop(origin, None)
        if saved is None or saved[0] == stable:
            return None
        return saved[1], saved[0]

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
        """Forget every entry, count and saved source.

        Examples
        --------
        >>> from sqlearn._store import Store
        >>> Store().clear()
        """
        self._entries.clear()
        self._stable.clear()
        self._saved.clear()
        self.learns.clear()


STORE = Store()
"""The process-wide store."""
