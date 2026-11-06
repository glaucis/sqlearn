"""The one rule naming the columns steps create (ADR 0035)."""

from collections.abc import Sequence

__all__ = ["name_columns"]


def name_columns(planned: Sequence[tuple[str, str]], taken: Sequence[str]) -> list[str]:
    """Name created columns from their labels, numbering names that clash.

    Each output is named ``<column>_<label>``, or ``<column>`` for the label
    ``""``. Names equal without regard to case (as DuckDB compares them),
    including those in `taken`, are numbered: the first in sorted order of
    label keeps its name, the others get ``_2``, ``_3`` in that order, skipping
    a number already in use. Equal labels keep their planned order. A name in
    `taken` is never renamed.

    Parameters
    ----------
    planned : sequence of (str, str)
        ``(column, label)`` per output, in output order.
    taken : sequence of str
        The names of the columns passing through, which keep their names.

    Returns
    -------
    list of str
        The final name of each planned output, in the order given.

    Examples
    --------
    >>> from sqlearn._names import name_columns
    >>> name_columns([("city", "oslo"), ("city", "Oslo"), ("city", "NULL")], [])
    ['city_oslo_2', 'city_Oslo', 'city_NULL']
    >>> name_columns([("city", "Oslo")], ["city_oslo"])
    ['city_Oslo_2']
    """
    wanted = [f"{column}_{label}" if label else column for column, label in planned]
    used = {name.lower() for name in taken}
    order = sorted(range(len(planned)), key=lambda i: planned[i][1])
    final: list[str | None] = [None] * len(planned)
    clashing: list[int] = []
    for i in order:
        key = wanted[i].lower()
        if key in used:
            clashing.append(i)
        else:
            used.add(key)
            final[i] = wanted[i]
    for i in clashing:
        number = 2
        while f"{wanted[i]}_{number}".lower() in used:
            number += 1
        name = f"{wanted[i]}_{number}"
        used.add(name.lower())
        final[i] = name
    return [name for name in final if name is not None]
