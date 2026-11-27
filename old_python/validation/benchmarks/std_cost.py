"""Measure the cost of the two-pass standard deviation (issue #28).

``sq.agg.std`` is computed in two passes (the mean with ``favg``, then
``sqrt(favg((x - mean) ^ 2))``) where it was DuckDB's one-pass
``stddev_pop``. This script times both on 20,000,000 rows read from Parquet,
under a 64 MB memory limit on one thread (the core's larger-than-memory
setting) and with no limit on DuckDB's default threads: DuckDB's SQL alone,
then through sqlearn, learning one column's standard deviation and learning
``sq.scale.standard``. Each value's distance in ULPs from the exact
population standard deviation is shown beside its time. It prints Markdown
tables. It measures; it decides nothing.

Run it with ``uv run python -m validation.benchmarks.std_cost``. The data is
generated from a fixed seed into a temporary directory removed after.
"""

import json
import statistics
import tempfile
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import duckdb
import mpmath
import numpy as np

import sqlearn as sq
from sqlearn._errors import SqlearnError
from sqlearn._store import STORE
from sqlearn.agg.aggregates import present
from validation import _cases
from validation.benchmarks.category_lookup import _machine

PAGE = "docs/benchmarks/standard-deviation.md"
"""The page of ``docs/benchmarks`` this script's numbers feed."""
GROUPS: tuple[str, ...] | None = None
"""The C++ groups it measures; None for every group (ADR 0072)."""

SEED = 0
"""Every dataset comes from this seed: generated, never downloaded."""

ROWS = 20_000_000
"""The rows of the dataset."""

REPETITIONS = 3
"""Each measurement is repeated this many times after one discarded run."""

SETTINGS = (("64MB", 1), (None, None))
"""The memory limits and threads measured: ``None`` keeps DuckDB's default."""

DATA = """
    SELECT CASE WHEN hash(i, {s}) % 10 = 0 THEN NULL
                ELSE 1000 + ((hash(i, {s} + 1) % 2000001)::DOUBLE - 1000000) / 10000
           END AS x
    FROM range({n}) t(i)
"""
"""One DOUBLE column: a tenth NULL, the rest spread evenly over 900 to 1,100,
far from zero, as the validation's values are."""

one_pass = sq.agg.Aggregate(
    "one_pass_std", lambda x: duckdb.FunctionExpression("stddev_pop", present(x))
)
"""``sq.agg.std`` as it was: DuckDB's ``stddev_pop`` of the present values."""


class Learn(sq.Step):
    """Learn one aggregate of each column; apply leaves the column."""

    def __init__(self, cols=None, value=sq.agg.std, keep=False, suffix=None):
        """Set the settings."""
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.value = value

    def learn(self, x):
        """Learn the aggregate."""
        return {"v": self.value(x)}

    def apply(self, x, learned):
        """Leave the column."""
        return x


def exact_std(path: Path) -> float:
    """Return the double nearest the exact population standard deviation.

    Every value lies in [512, 2048), so each is a whole multiple of 2**-43:
    times 2**43 it is an integer, and Python's integers sum the values and
    their squares exactly. The root is taken at 50 digits with mpmath.
    """
    column = duckdb.sql(f"SELECT x FROM read_parquet('{path}')").fetchnumpy()["x"]
    x = np.asarray(column.compressed(), dtype=float)
    assert x.min() >= 512 and x.max() < 2048
    scaled = (x * 2.0**43).astype(np.int64)
    assert np.array_equal(scaled.astype(float), x * 2.0**43)
    n = len(scaled)
    total = sum(int(v) for v in scaled)
    squares = sum(int(v) * int(v) for v in scaled)
    variance = Fraction(n * squares - total * total, n * n) / 2**86
    with mpmath.workdps(_cases.DIGITS):
        return float(mpmath.sqrt(mpmath.mpf(variance.numerator) / variance.denominator))


def _connect(spill: Path, limit: str | None, threads: int | None):
    con = duckdb.connect()
    if limit is not None:
        con.execute(f"SET memory_limit = '{limit}'")
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    con.execute(f"SET temp_directory = '{spill}'")
    return con


def _forms(path: Path) -> dict[str, Callable[[duckdb.DuckDBPyConnection], object]]:
    data = f"read_parquet('{path}')"
    two_pass = (
        f"WITH m AS MATERIALIZED (SELECT favg(x) AS u FROM {data}) "
        f"SELECT CASE WHEN min(x) = max(x) AND isfinite(min(x)) THEN 0.0 "
        f"ELSE sqrt(favg((x - u) ^ 2)) END FROM {data} CROSS JOIN m"
    )

    def sql(statement: str) -> Callable[[duckdb.DuckDBPyConnection], object]:
        return lambda con: con.sql(statement).fetchall()[0][0]

    def learn(step: Callable[[], sq.Step], read: Callable[[sq.Step], object]):
        def run(con: duckdb.DuckDBPyConnection) -> object:
            STORE.clear()  # learn from scratch every time
            return read(sq.Pipeline([step()]).learn(str(path))[0])

        return run

    return {
        "stddev_pop (DuckDB SQL)": sql(f"SELECT stddev_pop(x) FROM {data}"),
        "two passes (DuckDB SQL)": sql(two_pass),
        "one pass, learned by sqlearn": learn(
            lambda: Learn(value=one_pass), lambda s: s.v_["x"]
        ),
        "sq.agg.std, learned by sqlearn": learn(Learn, lambda s: s.v_["x"]),
        "sq.scale.standard, learned": learn(sq.scale.standard, lambda s: s.scale_["x"]),
    }


def _time(run: Callable[[], object]) -> tuple[str, object]:
    """Return the median wall clock of the repetitions, or why it failed."""
    try:
        value = run()  # discarded: warms the file cache and the connection
        times = []
        for _ in range(REPETITIONS):
            start = time.perf_counter()
            value = run()
            times.append(time.perf_counter() - start)
    except (duckdb.Error, SqlearnError) as error:
        return "failed: " + str(error).splitlines()[0][:80], None
    return f"{statistics.median(times):.3f}", value


def main() -> None:
    """Generate the data, time every form under each setting, print the table."""
    print(json.dumps(_machine(), indent=2))  # noqa: T201
    with tempfile.TemporaryDirectory(prefix="std_cost_") as tmp:
        path = Path(tmp) / "data.parquet"
        duckdb.execute(
            f"COPY ({DATA.format(s=SEED, n=ROWS)}) TO '{path}' (FORMAT parquet)"
        )
        size = path.stat().st_size / 2**20
        exact = exact_std(path)
        print(f"\n{ROWS:,} rows, {size:.1f} MB as Parquet; exact {exact!r}")  # noqa: T201
        print(  # noqa: T201
            "\n| memory limit | threads | form | s | value | ULPs from exact |"
            "\n|---|---|---|---|---|---|",
            flush=True,
        )
        for limit, threads in SETTINGS:
            con = _connect(Path(tmp) / "spill", limit, threads)
            sq.set_config(connection=con)
            try:
                for name, form in _forms(path).items():
                    seconds, value = _time(lambda form=form, con=con: form(con))
                    shown = "" if value is None else repr(value)
                    ulps = "" if value is None else _cases.ulps(value, exact)
                    print(  # noqa: T201
                        f"| {limit or 'none'} | {threads or 'default'} | {name} "
                        f"| {seconds} | {shown} | {ulps} |",
                        flush=True,
                    )
            finally:
                sq.set_config(connection=None)
                con.close()


if __name__ == "__main__":
    main()
