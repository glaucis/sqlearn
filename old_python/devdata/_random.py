"""Repeatable random numbers: SplitMix64 in SQL, and its Python reference.

Every value is a pure function of ``(seed, row, stream)``, so rows can be
computed in any order on any thread and give the same numbers (ADR 0045).
The SQL and the Python give the same values bit for bit; Python draws only a
handful of constants, at rows from ``CONSTANT_ROW`` on.

Examples
--------
>>> from devdata._random import uniform
>>> uniform(0, 0, 0) == uniform(0, 0, 0)
True
>>> 0.0 <= uniform(0, 0, 0) < 1.0
True
"""

import math
from collections.abc import Callable, Mapping

MASK = 2**64 - 1
GOLDEN = 0x9E3779B97F4A7C15
MIX1 = 0xBF58476D1CE4E5B9
MIX2 = 0x94D049BB133111EB
CONSTANT_ROW = 2**63
"""The first row of the constants drawn in Python, never a data row's."""

_LOW_BITS = f"{MASK}::UHUGEINT"


def splitmix64(x: int) -> int:
    """Return one SplitMix64 output for the state `x`, modulo ``2**64``.

    Parameters
    ----------
    x : int
        The state, in ``[0, 2**64)``.

    Returns
    -------
    int
        The mixed output, in ``[0, 2**64)``.

    Examples
    --------
    >>> hex(splitmix64(0))
    '0xe220a8397b1dcdaf'
    """
    z = (x + GOLDEN) & MASK
    z = ((z ^ (z >> 30)) * MIX1) & MASK
    z = ((z ^ (z >> 27)) * MIX2) & MASK
    return z ^ (z >> 31)


def key(seed: int, row: int, stream: int) -> int:
    """Return the 64-bit random key of one value.

    Parameters
    ----------
    seed : int
        Any integer; taken modulo ``2**64``.
    row : int
        The row, in ``[0, 2**64)``.
    stream : int
        The stream, in ``[0, 2**64)``: one per random column.

    Returns
    -------
    int
        ``splitmix64(splitmix64(splitmix64(seed mod 2**64) ^ row) ^ stream)``.

    Examples
    --------
    >>> key(-1, 0, 0) == key(2**64 - 1, 0, 0)
    True
    """
    return splitmix64(splitmix64(splitmix64(seed & MASK) ^ row) ^ stream)


def uniform(seed: int, row: int, stream: int) -> float:
    """Return a uniform value in ``[0, 1)``: the key's top 53 bits.

    Parameters
    ----------
    seed, row, stream : int
        As for `key`.

    Returns
    -------
    float
        ``(key >> 11) * 2**-53``.

    Examples
    --------
    >>> 0.0 <= uniform(1, 2, 3) < 1.0
    True
    """
    return (key(seed, row, stream) >> 11) * 2.0**-53


def normal(seed: int, row: int, stream: int) -> float:
    """Return a standard normal value, by Box-Muller over two uniforms.

    Parameters
    ----------
    seed, row : int
        As for `key`.
    stream : int
        In ``[0, 2**63)``: the uniforms use streams ``2 * stream`` and
        ``2 * stream + 1``, which must stay below ``2**64``.

    Returns
    -------
    float
        ``sqrt(-2 ln(1 - u1)) * cos(2 pi u2)``.

    Examples
    --------
    >>> isinstance(normal(0, 0, 0), float)
    True
    """
    u1 = uniform(seed, row, 2 * stream)
    u2 = uniform(seed, row, 2 * stream + 1)
    return math.sqrt(-2.0 * math.log(1.0 - u1)) * math.cos(2.0 * math.pi * u2)


def _modular(expression: str) -> str:
    """Return `expression`, a UHUGEINT, modulo ``2**64`` as a UBIGINT.

    The low 64 bits by a mask: the same value as ``% 2**64``, about twelve
    times faster than DuckDB's 128-bit division.
    """
    return f"(({expression}) & {_LOW_BITS})::UBIGINT"


def _mixed(source: str, columns: list[str]) -> str:
    """Return the SQL of `source` with SplitMix64 applied to `columns`.

    One subquery per step, each reading the previous step's columns once, so
    the text grows linearly with the columns; the other columns pass through.
    """
    if not columns:
        return source
    steps: list[Callable[[str], str]] = [
        lambda c: _modular(f"{c}::UHUGEINT + {GOLDEN}::UHUGEINT"),
        lambda c: _modular(f"xor({c}, {c} >> 30)::UHUGEINT * {MIX1}::UHUGEINT"),
        lambda c: _modular(f"xor({c}, {c} >> 27)::UHUGEINT * {MIX2}::UHUGEINT"),
        lambda c: f"xor({c}, {c} >> 31)",
    ]
    for step in steps:
        replaced = ", ".join(f"{step(c)} AS {c}" for c in columns)
        source = f"SELECT * REPLACE ({replaced}) FROM ({source})"
    return source


def _quoted(name: str) -> str:
    """Return `name` as a quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _check_streams(uniforms: Mapping[str, int], normals: Mapping[str, int]) -> None:
    """Raise ValueError when the streams break `random_columns`'s contract."""
    for kind, mapping, limit in (
        ("uniform", uniforms, 2**64),
        ("normal", normals, 2**63),
    ):
        for name, stream in mapping.items():
            if not 0 <= stream < limit:
                msg = f"The {kind} {name!r} has stream {stream}, outside [0, {limit})."
                raise ValueError(msg)
        seen: dict[int, str] = {}
        for name, stream in mapping.items():
            if stream in seen:
                msg = (
                    f"The {kind}s {seen[stream]!r} and {name!r} share stream "
                    f"{stream}: each column needs its own."
                )
                raise ValueError(msg)
            seen[stream] = name
    for name in [*uniforms, *normals]:
        if name == "i":
            msg = "A random column cannot be named 'i': that is the row column."
            raise ValueError(msg)
        if name in uniforms and name in normals:
            msg = f"The name {name!r} is both a uniform and a normal."
            raise ValueError(msg)
    taken = {
        s: n for n, stream in normals.items() for s in (2 * stream, 2 * stream + 1)
    }
    for name, stream in uniforms.items():
        if stream in taken:
            msg = (
                f"The uniform {name!r} has stream {stream}, which the normal "
                f"{taken[stream]!r} draws on (normal n uses streams 2n and 2n + 1)."
            )
            raise ValueError(msg)


def random_columns(
    seed: int,
    rows: int,
    uniforms: Mapping[str, int],
    normals: Mapping[str, int],
    row_source: str | None = None,
) -> str:
    """Return the SQL of `rows` rows of random columns.

    Parameters
    ----------
    seed : int
        Any integer; taken modulo ``2**64``.
    rows : int
        The number of rows.
    uniforms : Mapping[str, int]
        Each uniform column's name and stream, in ``[0, 2**64)``.
    normals : Mapping[str, int]
        Each normal column's name and stream, in ``[0, 2**63)``. Normal
        stream ``n`` draws on uniform streams ``2n`` and ``2n + 1``, so no
        uniform may use either.
    row_source : str or None, default=None
        A query with one ``BIGINT`` column ``range``, holding ``0`` to
        ``rows - 1`` in order, to read instead of ``range(rows)``.

    Returns
    -------
    str
        A query over the row source, by default ``range(rows)``, with column
        ``i`` (the row, BIGINT), then one DOUBLE column per name, uniforms
        first: ``uniform(seed, i, stream)`` or ``normal(seed, i, stream)``,
        equal to the Python ones bit for bit.

    Raises
    ------
    ValueError
        When the streams break the contract: a stream out of range, two
        columns of one kind sharing a stream, a uniform on a normal's stream,
        a name used twice or the name ``i``.

    Examples
    --------
    >>> import duckdb
    >>> sql = random_columns(0, 3, {"u": 0}, {})
    >>> [r[1] for r in duckdb.sql(sql).fetchall()] == [
    ...     uniform(0, i, 0) for i in range(3)
    ... ]
    True
    """
    _check_streams(uniforms, normals)
    streams = sorted(
        {*uniforms.values()} | {s for n in normals.values() for s in (2 * n, 2 * n + 1)}
    )
    seeded = splitmix64(seed & MASK)
    origin = f"({row_source})" if row_source is not None else f"range({rows})"
    source = _mixed(
        f"SELECT range AS i, xor(range::UBIGINT, {seeded}::UBIGINT) AS _row "
        f"FROM {origin}",
        ["_row"],
    )
    keys = ", ".join(f"xor(_row, {s}::UBIGINT) AS _k{s}" for s in streams)
    source = _mixed(
        f"SELECT i, {keys} FROM ({source})" if keys else f"SELECT i FROM ({source})",
        [f"_k{s}" for s in streams],
    )
    scale = f"{2.0**-53!r}::DOUBLE"
    drawn = {s: f"(_k{s} >> 11)::DOUBLE * {scale}" for s in streams}
    columns = ["i"]
    columns += [f"{drawn[s]} AS {_quoted(name)}" for name, s in uniforms.items()]
    columns += [
        f"sqrt(-2.0::DOUBLE * ln(1.0::DOUBLE - {drawn[2 * n]})) "
        f"* cos(2.0::DOUBLE * pi() * {drawn[2 * n + 1]}) AS {_quoted(name)}"
        for name, n in normals.items()
    ]
    return f"SELECT {', '.join(columns)} FROM ({source})"
