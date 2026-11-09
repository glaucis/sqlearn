"""Measure ways of looking a category up in one expression (issue #31).

The ordinal and target encoders find a value's category with
``list_position(<learned categories>, x)``, which compares the value with
the categories one by one. This script times that lookup and the other
forms a step can write as one DuckDB expression (no join), on 1,000,000
rows at 100, 1,000 and 10,000 categories, checks that each gives the same
codes, and times the two encoders as they are. It prints Markdown tables. It
measures; it decides nothing.

Run it with ``uv run python -m validation.benchmarks.category_lookup``. The
data is generated from a fixed seed, in memory and in a temporary directory
removed after.
"""

import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import duckdb

import sqlearn as sq
from sqlearn._store import STORE

SEED = 0
"""Every dataset comes from this seed: generated, never downloaded."""

ROWS = 1_000_000
"""The rows of every dataset."""

COUNTS = (100, 1_000, 10_000)
"""The numbers of categories."""

REPETITIONS = 5
"""Each measurement is repeated this many times; the median is reported."""

SLOW_S = 5.0
"""A form whose median passes this at one count is timed once, without a
warm-up, at the next: its time there is long enough not to need either."""

CHECK_ROWS = 20_000
"""The codes of each form are compared with ``list_position``'s on this
many rows (all of them would take minutes for the slowest forms)."""

UNSEEN_ROWS = 20_000
"""The rows of the table of only unseen values."""

DATA = """
    SELECT
        i,
        CASE WHEN hash(i, {s}) % 100 = 0 THEN NULL
             WHEN hash(i, {s} + 1) % 100 = 0 THEN 'unseen' || i
             ELSE 'c' || lpad((hash(i, {s} + 2) % {k})::VARCHAR, 5, '0') END AS c,
        (hash(i, {s} + 3) % 2)::INTEGER AS y
    FROM range({n}) t(i)
"""
"""A text column: a hundredth NULL, a hundredth unseen, the rest drawn
uniformly from ``k`` categories ``c00000``, ``c00001``, ...; a binary
target for the target encoder."""


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _listed(categories: list[str]) -> str:
    return "[" + ", ".join(_text(c) for c in categories) + "]"


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

    Returns
    -------
    tuple
        ``m``, ``r``, the displacements and, per slot, the category's
        position from 1 (0 for an empty slot).
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
    return m, r, displacements, table


def _perfect_hash_form(categories: list[str]) -> str:
    m, r, displacements, table = perfect_hash(categories)
    a, b = "md5_number_upper(c)::HUGEINT", "md5_number_lower(c)::HUGEINT"
    shifts = "[" + ", ".join(map(str, displacements)) + "]::UBIGINT[]"
    slots = "[" + ", ".join(map(str, table)) + "]::INTEGER[]"
    d = f"list_extract({shifts}, ({a} % {r})::INTEGER + 1)::HUGEINT"
    slot = f"(({b} + {d} * (({a} >> 32) % {m - 1} + 1)) % {m})::INTEGER"
    at = f"list_extract({slots}, {slot} + 1)"
    return f"CASE WHEN list_extract({_listed(categories)}, {at}) = c THEN {at} - 1 END"


def _forms(categories: list[str]) -> dict[str, str]:
    """Return each form's expression: the code from 0, NULL if not found."""
    listed = _listed(categories)
    pairs = ", ".join(f"{_text(c)}: {i}" for i, c in enumerate(categories))
    enum = "ENUM(" + ", ".join(_text(c) for c in categories) + ")"
    json_object = json.dumps({c: i for i, c in enumerate(categories)})
    whens = " ".join(f"WHEN c = {_text(c)} THEN {i}" for i, c in enumerate(categories))
    return {
        "list_position (today)": f"list_position({listed}, c) - 1",
        "map_extract_value(MAP {...}, x)": f"map_extract_value(MAP {{{pairs}}}, c)",
        "MAP {...}[x]": f"(MAP {{{pairs}}})[c]",
        "CASE chain": f"CASE {whens} END",
        "TRY_CAST(x AS ENUM(...))": f"enum_code(TRY_CAST(c AS {enum}))",
        "json_extract": (
            f"json_extract({_text(json_object)}::JSON, '$.\"' || c || '\"')::INTEGER"
        ),
        "MD5 perfect hash": _perfect_hash_form(categories),
    }


def _time(con: duckdb.DuckDBPyConnection, statement: str, warm: bool) -> float:
    """Return the median wall clock of the statement, or one run's if not warm."""
    if not warm:
        start = time.perf_counter()
        con.execute(statement).fetchall()
        return time.perf_counter() - start
    con.execute(statement).fetchall()  # the discarded warm-up
    times = []
    for _ in range(REPETITIONS):
        start = time.perf_counter()
        con.execute(statement).fetchall()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def lookups(con: duckdb.DuckDBPyConnection) -> list[tuple[int, str, str, str]]:
    """Time every form at every count; return (count, form, seconds, same codes)."""
    rows = []
    slow: set[str] = set()
    for k in COUNTS:
        categories = [f"c{i:05d}" for i in range(k)]
        con.execute(f"CREATE OR REPLACE TABLE d AS {DATA.format(s=SEED, k=k, n=ROWS)}")
        forms = _forms(categories)
        today = forms["list_position (today)"]
        for name, form in forms.items():
            differ = con.execute(
                f"SELECT count(*) FROM d WHERE i < {CHECK_ROWS} "
                f"AND ({form}) IS DISTINCT FROM ({today})"
            ).fetchall()[0][0]
            warm = name not in slow
            seconds = _time(con, f"SELECT sum({form}) FROM d", warm)
            if seconds > SLOW_S:
                slow.add(name)
            label = f"{seconds:.3f}" if warm else f"{seconds:.3f} (one run)"
            rows.append((k, name, label, "yes" if differ == 0 else f"no ({differ})"))
            print(f"| {k:,} | {name} | {label} | {rows[-1][3]} |", flush=True)  # noqa: T201
    return rows


def costs(con: duckdb.DuckDBPyConnection) -> None:
    """Time the two costs that grow with the count in the forms that avoid a scan."""
    con.execute(
        f"CREATE OR REPLACE TABLE p AS SELECT (hash(i, {SEED} + 4) % 100)::INTEGER + 1 "
        f"AS j FROM range({ROWS}) t(i)"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE u AS SELECT 'unseen' || i AS c "
        f"FROM range({UNSEEN_ROWS}) t(i)"
    )
    for k in COUNTS:
        ints = "[" + ", ".join(map(str, range(k))) + "]::INTEGER[]"
        listed = _listed([f"c{i:05d}" for i in range(k)])
        enum = "ENUM(" + ", ".join(_text(f"c{i:05d}") for i in range(k)) + ")"
        reading = _time(con, f"SELECT sum(list_extract({ints}, j)) FROM p", warm=True)
        failing = _time(
            con, f"SELECT count(enum_code(TRY_CAST(c AS {enum}))) FROM u", warm=False
        )
        scanning = _time(con, f"SELECT count(list_position({listed}, c)) FROM u", True)
        print(  # noqa: T201
            f"| {k:,} | {reading:.3f} | {failing:.3f} | {scanning:.3f} |", flush=True
        )


def encoders(root: Path) -> None:
    """Time the two encoders as they are: learn, then apply to Parquet.

    Beside them, the lookup alone (``list_position`` summed) over the same
    Parquet file, to set against the in-memory table of `lookups`.
    """
    con = duckdb.connect()
    sq.set_config(connection=con)
    out = root / "encoded.parquet"
    makers: dict[str, Callable[[], sq.Pipeline]] = {
        "ordinal": lambda: sq.Pipeline([sq.encode.ordinal("c")]),
        "target": lambda: sq.Pipeline([sq.encode.target("c")]),
    }
    try:
        for k in COUNTS:
            path = root / f"data_{k}.parquet"
            data = DATA.format(s=SEED, k=k, n=ROWS)
            con.execute(
                f"COPY (SELECT c, y FROM ({data})) TO '{path}' (FORMAT parquet)"
            )
            listed = _listed([f"c{i:05d}" for i in range(k)])
            alone = _time(
                con, f"SELECT sum(list_position({listed}, c)) FROM '{path}'", True
            )
            for name, make in makers.items():
                learns, applies = [], []
                for rep in range(REPETITIONS + 1):  # the first is the warm-up
                    STORE.clear()  # learn from scratch every time
                    pipe = make()
                    start = time.perf_counter()
                    pipe.learn(str(path), target="y")
                    learned = time.perf_counter()
                    pipe.apply(str(path), out=sq.out.parquet(out))
                    end = time.perf_counter()
                    if rep:
                        learns.append(learned - start)
                        applies.append(end - learned)
                print(  # noqa: T201
                    f"| {k:,} | {name} | {statistics.median(learns):.3f} | "
                    f"{statistics.median(applies):.3f} | {alone:.3f} |",
                    flush=True,
                )
    finally:
        con.close()
        sq.set_config(connection=None)


def _machine() -> dict:
    """Return the machine and versions; the sysctl details are macOS-only."""

    def sysctl(key: str) -> str:
        try:
            return subprocess.run(
                ["sysctl", "-n", key],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    return {
        "cpu": sysctl("machdep.cpu.brand_string"),
        "cores": sysctl("hw.ncpu"),
        "ram_bytes": sysctl("hw.memsize"),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "duckdb": version("duckdb"),
        "sqlearn": version("sqlearn"),
    }


def main() -> None:
    """Generate the data, time every form and the encoders, print the tables."""
    print(json.dumps(_machine(), indent=2))  # noqa: T201
    con = duckdb.connect()
    print(  # noqa: T201
        "\n| categories | form | s | same codes |\n|---|---|---|---|", flush=True
    )
    lookups(con)
    print(  # noqa: T201
        f"\n| categories | read a constant list, {ROWS:,} rows | "
        f"failing ENUM cast, {UNSEEN_ROWS:,} rows | "
        f"list_position, the same {UNSEEN_ROWS:,} rows |\n|---|---|---|---|",
        flush=True,
    )
    costs(con)
    con.close()
    print(  # noqa: T201
        "\n| categories | encoder | learn s | apply s "
        "| list_position alone, from Parquet s |\n|---|---|---|---|---|",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="category_lookup_") as tmp:
        encoders(Path(tmp))


if __name__ == "__main__":
    main()
