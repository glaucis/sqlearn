"""Measure what one level of nesting costs a learn (issue #49, ADR 0051).

An aggregate inside another is learned one level later: the inner one's
row first, then the outer one over the stage's input cross-joined with it.
This script times, through sqlearn on 20,000,000 rows read from Parquet,
each nested value beside the same outer aggregate without the inner one:

- ``median(abs(x - median(x)))`` against ``median(abs(x))``: a second sort;
- ``std(x - mean(x))`` against ``std(x)``: a plain pass before the two;
- ``sum(x - mean(x))`` against ``sum(x)``: a plain pass before the scan.

The pairs alternate, three runs each on one thread with no memory limit,
and the median run is kept; the machine's load is printed before and
after, as other jobs share it. It prints a Markdown table. It measures; it
decides nothing.

Run it with ``uv run python -m validation.benchmarks.nested_cost``. The
data is generated from a fixed seed into a temporary directory removed
after.
"""

import json
import os
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import duckdb

import sqlearn as sq
from sqlearn._store import STORE
from validation.benchmarks.category_lookup import _machine

PAGE = "docs/benchmarks/median-reach.md"
"""The page of ``docs/benchmarks`` this script's numbers feed."""
GROUPS: tuple[str, ...] | None = None
"""The C++ groups it measures; None for every group (ADR 0072)."""

ROWS = 20_000_000
"""Rows read from Parquet in each learn."""

RUNS = 3
"""Runs of each value; the median is kept."""

DATA = """
    SELECT 1000 + ((hash(i, 0) % 2000001)::DOUBLE - 1000000) / 10000 AS x
    FROM range({n}) t(i)
"""
"""One DOUBLE column spread evenly over 900 to 1,100, from a fixed seed."""


def _duck(name: str, *args: duckdb.Expression) -> duckdb.Expression:
    return duckdb.FunctionExpression(name, *args)


PAIRS: dict[str, tuple[Callable, Callable]] = {
    "median(abs(x - median(x))) / median(abs(x))": (
        lambda x: sq.agg.median(sq.fn.abs(x - sq.agg.median(x))),
        lambda x: sq.agg.median(sq.fn.abs(x)),
    ),
    "std(x - mean(x)) / std(x)": (
        lambda x: sq.agg.std(x - sq.agg.mean(x)),
        sq.agg.std,
    ),
    "sum(x - mean(x)) / sum(x)": (
        lambda x: _duck("sum", x - sq.agg.mean(x)),
        lambda x: _duck("sum", x),
    ),
}
"""Each nested value and the same outer aggregate without the inner one."""


class _Learns(sq.Step):
    """Learn the one value `build` makes of each column."""

    def __init__(self, build: Callable, cols: list[str] | None = None) -> None:
        super().__init__(cols=cols)
        self.build = build

    def learn(self, x: duckdb.Expression) -> dict[str, duckdb.Expression]:
        """Learn the value."""
        return {"v": self.build(x)}

    def apply(self, x: duckdb.Expression, learned: object) -> duckdb.Expression:
        """Leave the column."""
        return x


def _seconds(build: Callable, path: Path) -> float:
    """Return the seconds one learn of `build` from `path` takes, store cleared."""
    STORE.clear()
    start = time.perf_counter()
    sq.Pipeline([_Learns(build, cols=["x"])]).learn(str(path))
    return time.perf_counter() - start


def main() -> None:
    """Time each pair and print the table."""
    print(json.dumps(_machine(), indent=2))  # noqa: T201
    print(f"load before: {os.getloadavg()}")  # noqa: T201
    con = duckdb.connect()
    con.execute("SET threads = 1")
    sq.set_config(connection=con)
    rows = []
    with tempfile.TemporaryDirectory(prefix="nested_cost_") as tmp:
        path = Path(tmp) / "x.parquet"
        con.execute(f"COPY ({DATA.format(n=ROWS)}) TO '{path}' (FORMAT parquet)")
        for name, (nested, plain) in PAIRS.items():
            outer: list[float] = []
            inner: list[float] = []
            for _ in range(RUNS):  # alternating, so load hits both alike
                inner.append(_seconds(nested, path))
                outer.append(_seconds(plain, path))
            a, b = statistics.median(inner), statistics.median(outer)
            rows.append((name, a, b, a / b))
    print(f"load after: {os.getloadavg()}")  # noqa: T201
    print("\n| pair | nested s | without the inner s | ratio |\n|---|---|---|---|")  # noqa: T201
    for name, a, b, ratio in rows:
        print(f"| `{name}` | {a:.2f} | {b:.2f} | {ratio:.2f} |")  # noqa: T201


if __name__ == "__main__":
    main()
