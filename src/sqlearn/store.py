"""The store of learned values, shared by every pipeline in the process."""

from sqlearn._store import STORE

__all__ = ["clear"]


def clear() -> None:
    """Forget every learned value, so the next ``learn`` learns again.

    The store notices a changed file, frame or table by its name, size and
    modification time, but not a DuckDB table changed in place with the same
    row count. Clear the store after such a change.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.store.clear()
    """
    STORE.clear()
