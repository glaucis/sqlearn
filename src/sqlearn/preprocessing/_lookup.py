"""Find a value among the learned categories: by list or by a perfect hash.

The ordinal and target encoders write a value's position among the learned
categories as one expression. ``lookup="list"`` writes ``list_position``,
which compares the value with the categories one by one, so its cost grows
with their number; ``lookup="hash"`` writes an MD5 perfect hash built in
Python when the step is applied, whose cost barely grows
(`docs/benchmarks/category-lookup.md`, issue #31). Both give the same
position from 1, NULL when the value is absent or NULL.
"""

import functools
import hashlib
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb
from duckdb import Expression
from duckdb.sqltypes import HUGEINT, INTEGER, VARCHAR, DuckDBPyType

from sqlearn._errors import SqlearnError, SqlearnWarning, StepError
from sqlearn._expr import const

__all__ = [
    "LOOKUPS",
    "WARN_ABOVE",
    "check_lookup",
    "check_text",
    "perfect_hash",
    "position",
    "warn_many",
]

LOOKUPS = ("list", "hash")
"""The lookups an encoder takes; None, the default, behaves as ``"list"``."""

WARN_ABOVE = 20_000
"""Above this many categories a left-out lookup warns.

Set from the benchmark's encoders from Parquet, 1,000,000 rows, at 10,000,
15,000, 20,000, 30,000, 50,000 and 100,000 categories: the smallest count
at which ``lookup="hash"`` applied faster than ``lookup="list"``, for both
encoders (ordinal 1.9 s against 2.4 s, target 2.9 s against 3.5 s; at
15,000 the list was faster for both, 0.6 s against 1.5 s and 1.5 s against
2.3 s). See ``docs/benchmarks/category-lookup.md``.
"""

_PACKAGE = (str(Path(__file__).parents[1]),)
"""sqlearn's own files: a warning is placed at the first frame outside them."""

_warned: set[tuple[str, str, int]] = set()
"""The (step, column, count) already warned about: once per process each."""

_TEXT = ("varchar", "enum")
"""The type ids the hash reads: text, as ``sq.cols.string()`` chooses it."""


def _md5_halves(value: str) -> tuple[int, int]:
    """Return DuckDB's ``md5_number_upper`` and ``md5_number_lower`` of a text."""
    number = int.from_bytes(hashlib.md5(value.encode()).digest(), "little")
    return number & (2**64 - 1), number >> 64


def _prime_from(n: int) -> int:
    def prime(p: int) -> bool:
        return p > 1 and all(p % q for q in range(2, int(p**0.5) + 1))

    return next(p for p in range(n, 2 * n + 3) if prime(p))


def perfect_hash(categories: list[str]) -> tuple[int, int, list[int], list[int]]:
    """Build a perfect hash of the categories by hash and displace.

    Each category's MD5 gives two numbers, ``a`` and ``b``. Its bucket is
    ``a % r``; its slot is ``(b + d * step) % m``, where ``step = (a >> 32)
    % (m - 1) + 1`` and ``d`` is the bucket's displacement, chosen (largest
    bucket first) so that no two categories share a slot. ``m`` is a prime
    above twice the count, ``r`` half the count.

    Parameters
    ----------
    categories : list of str
        Distinct texts.

    Returns
    -------
    tuple
        ``m``, ``r``, the displacements and, per slot, the category's
        position from 1 (0 for an empty slot).

    Raises
    ------
    RuntimeError
        If no displacement separates a bucket (not met in practice).

    Examples
    --------
    >>> from sqlearn.preprocessing._lookup import perfect_hash
    >>> m, r, displacements, table = perfect_hash(["a", "b", "c"])
    >>> m, r, sorted(p for p in table if p)
    (7, 1, [1, 2, 3])
    """
    m, r, displacements, table = _perfect_hash(tuple(categories))
    return m, r, list(displacements), list(table)


@functools.lru_cache(maxsize=16)
def _perfect_hash(
    categories: tuple[str, ...],
) -> tuple[int, int, tuple[int, ...], tuple[int, ...]]:
    """Build `perfect_hash` once per categories: the step's SQL is written often.

    A learn or an apply writes a step's SQL some twenty times, each needing
    the hash of the same categories; at 30,000 categories building it took
    about 0.17 s, and a second time from the cache about 0.002 s.
    """
    k = len(categories)
    m, r = _prime_from(2 * k + 1), max(1, k // 2)
    halves = [_md5_halves(c) for c in categories]
    buckets: dict[int, list[int]] = {}
    for i, (a, _) in enumerate(halves):
        buckets.setdefault(a % r, []).append(i)
    displacements, table = [0] * r, [0] * m
    for bucket, members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        for d in range(10 * m):
            slots = [
                (halves[i][1] + d * ((halves[i][0] >> 32) % (m - 1) + 1)) % m
                for i in members
            ]
            if len(set(slots)) == len(slots) and not any(table[s] for s in slots):
                break
        else:
            msg = "no displacement found"
            raise RuntimeError(msg)
        displacements[bucket] = d
        for i, s in zip(members, slots, strict=True):
            table[s] = i + 1
    return m, r, tuple(displacements), tuple(table)


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


_MD5 = "_sqlearn_md5"
_AT = "_sqlearn_at"
"""The lambdas' parameters, named so as not to hide a column."""


def _bound(value: Expression, name: str, body: Expression) -> Expression:
    """Return `body` with `name` bound to `value`, which is computed once.

    ``list_transform([value], lambda name: body)[1]``: DuckDB shares no
    repeated subexpression inside a ``CASE`` (an encoder's NULL handling,
    the target encoder's folds), so the MD5 and the slot are bound once each
    rather than written out wherever they are used. Measured from Parquet at
    1,000 categories inside a ``CASE``: 0.28 s against 1.83 s written out.
    """
    each = duckdb.LambdaExpression(name, body)
    listed = _fn("list_value", value)
    return _fn("list_extract", _fn("list_transform", listed, each), const(1))


def _ints(values: list[int], kind: str) -> Expression:
    """Return a constant list of whole numbers, written as SQL text.

    A constant expression renders its list element by element, each time
    the step's SQL is written (some twenty times in a learn or an apply);
    the perfect hash's lists hold about 2.5 numbers per category, so at
    10,000 categories that took about 0.07 s a time. Whole numbers written
    as text need no escaping.
    """
    return duckdb.SQLExpression(f"[{', '.join(map(str, values))}]::{kind}[]")


def _hashed(x: Expression, categories: list[str]) -> Expression:
    """Return the MD5 perfect hash's position of `x`, NULL when absent.

    DuckDB's ``md5_number`` holds ``md5_number_upper`` in its low 64 bits
    and ``md5_number_lower`` in its high ones, which `_md5_halves` mirrors.
    """
    m, r, displacements, table = perfect_hash(categories)
    text = x.cast(VARCHAR)
    h = duckdb.ColumnExpression(_MD5)
    a = _fn("&", h, const(2**64 - 1).cast("UHUGEINT")).cast(HUGEINT)
    b = _fn(">>", h, const(64)).cast(HUGEINT)
    shifts = _ints(displacements, "UBIGINT")
    slots = _ints(table, "INTEGER")
    bucket = (a % const(r)).cast(INTEGER) + const(1)
    d = _fn("list_extract", shifts, bucket).cast(HUGEINT)
    step = _fn(">>", a, const(32)) % const(m - 1) + const(1)
    slot = ((b + d * step) % const(m)).cast(INTEGER)
    at = duckdb.ColumnExpression(_AT)
    found = _fn("list_extract", const(categories), at) == text
    checked = duckdb.CaseExpression(found, at)
    located = _bound(_fn("list_extract", slots, slot + const(1)), _AT, checked)
    return _bound(_fn("md5_number", text), _MD5, located)


def position(x: Expression, categories: Sequence[object], lookup: str) -> Expression:
    """Return the position of `x` among `categories` from 1, NULL when absent.

    Parameters
    ----------
    x : duckdb.Expression
        The column.
    categories : sequence
        The learned categories, distinct and without NULL; texts for
        ``"hash"``.
    lookup : {"list", "hash"}
        ``"list"``: ``list_position``, the categories compared one by one
        (and by the column's collation). ``"hash"``: the MD5 perfect hash,
        which compares the bytes exactly and ignores a collation.

    Returns
    -------
    duckdb.Expression
        The position as ``list_position`` gives it.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn.preprocessing._lookup import position
    >>> rel = duckdb.sql("SELECT * FROM (VALUES ('b'), ('z'), (NULL)) t(x)")
    >>> x = duckdb.ColumnExpression("x")
    >>> rel.select(position(x, ["a", "b"], "hash")).fetchall()
    [(2,), (None,), (None,)]
    """
    if lookup == "hash":
        return _hashed(x, [str(c) for c in categories])
    return _fn("list_position", const(list(categories)), x)


def check_lookup(step: str, lookup: object) -> None:
    """Refuse a lookup that is neither None, ``"list"`` nor ``"hash"``.

    Parameters
    ----------
    step : str
        The step's constructor, such as ``sq.encode.ordinal``.
    lookup : object
        What was passed.

    Raises
    ------
    SqlearnError
        If `lookup` is not a lookup.

    Examples
    --------
    >>> from sqlearn.preprocessing._lookup import check_lookup
    >>> check_lookup("sq.encode.ordinal", "hash") is None
    True
    """
    if lookup is None or (isinstance(lookup, str) and lookup in LOOKUPS):
        return
    msg = (
        f"{step} got lookup={lookup!r}. Why: the lookups are 'list' (compare "
        "with each category in turn) and 'hash' (an MD5 perfect hash, for "
        'thousands of categories). Fix: pass lookup="list" or lookup="hash", '
        "or leave it out."
    )
    raise SqlearnError(msg)


def check_text(
    step: str, lookup: str | None, chosen: list[str], schema: Mapping[str, DuckDBPyType]
) -> None:
    """Refuse ``lookup="hash"`` on a chosen column that is not text.

    Parameters
    ----------
    step : str
        The step's constructor, such as ``sq.encode.ordinal``.
    lookup : str or None
        The step's lookup.
    chosen : list of str
        The columns the step encodes.
    schema : mapping of str to DuckDBPyType
        Their types.

    Raises
    ------
    StepError
        If the lookup is ``"hash"`` and a chosen column is not VARCHAR nor
        ENUM.

    Examples
    --------
    >>> from duckdb.sqltypes import VARCHAR
    >>> from sqlearn.preprocessing._lookup import check_text
    >>> check_text("sq.encode.ordinal", "hash", ["c"], {"c": VARCHAR}) is None
    True
    """
    if lookup != "hash":
        return
    for column in chosen:
        dtype = schema[column]
        if dtype.id in _TEXT:
            continue
        msg = (
            f'{step} with lookup="hash" cannot encode column {column!r}, '
            f"which is {dtype}. Why: the hash reads a value's text (its MD5), "
            'so it takes text columns alone. Fix: pass lookup="list" for this '
            "column, or cast it to VARCHAR first."
        )
        raise StepError(msg, step="", position=0)


def warn_many(
    step: object, lookup: str | None, values: Mapping[str, Mapping[str, object]]
) -> None:
    """Warn once when a left-out lookup meets more than `WARN_ABOVE` categories.

    The warning is kept to one per step's repr, column and count in the
    process, whatever the warning filters, so a search's folds and a
    repeated learn of the same step say it once.

    Parameters
    ----------
    step : object
        The step, named in the warning by its repr.
    lookup : str or None
        The step's lookup: only None, left out, warns.
    values : mapping of str to mapping of str to object
        What the step learned, per column; ``categories`` is counted.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn.preprocessing._lookup import warn_many
    >>> warn_many(sq.encode.ordinal(), None, {"c": {"categories": ["a"]}}) is None
    True
    """
    if lookup is not None:
        return
    for column, learned in values.items():
        categories = learned.get("categories")
        if not isinstance(categories, list) or len(categories) <= WARN_ABOVE:
            continue
        count = len(categories)
        key = (repr(step), column, count)
        if key in _warned:
            continue
        _warned.add(key)
        text = (
            f"{step!r} learned {count:,} categories in column {column!r} and "
            "looks each value up among them one by one (list_position). Why: "
            f"above {WARN_ABOVE:,} categories the MD5 perfect hash finds a "
            "value faster, and its cost barely grows with their number. Fix: "
            'pass lookup="hash" (it compares the bytes exactly, ignoring a '
            'collation), or lookup="list" to keep this lookup without the '
            "warning."
        )
        warnings.warn(text, SqlearnWarning, skip_file_prefixes=_PACKAGE)
