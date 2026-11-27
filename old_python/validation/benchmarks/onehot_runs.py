"""Measure what OneHot's second run costs (issue #22).

The core's slice preparation (``impute.median → onehot(city) → scale.standard``)
learns in two runs, because OneHot's new columns cannot be named before its
categories are learned. The same preparation without OneHot learns in one.
This script times both on generated data at 1,000, 100,000 and 10,000,000
rows, and once on the largest under a memory limit smaller than the data, and
prints the numbers as Markdown tables. It measures; it decides nothing.

Run it with ``uv run python -m validation.benchmarks.onehot_runs``. The data
is written to a temporary directory, from a fixed seed, and removed after.
"""

import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import duckdb

import sqlearn as sq
from sqlearn._errors import SqlearnError
from sqlearn._store import STORE

PAGE = "docs/benchmarks/onehot-second-run.md"
"""The page of ``docs/benchmarks`` this script's numbers feed."""
GROUPS: tuple[str, ...] | None = None
"""The C++ groups it measures; None for every group (ADR 0072)."""

SEED = 0
"""Every dataset comes from this seed: generated, never downloaded."""

SIZES = (1_000, 100_000, 10_000_000)
"""The row counts, the sizes ADR 0016 uses."""

REPETITIONS = 5
"""Each measurement is repeated this many times; the median is reported."""

LIMITS = ("512MB", "256MB", "128MB", "96MB", "64MB")
"""Memory limits tried, largest first, on the largest size (the data takes
about 400 MB in memory, so 512 MB is above it); every outcome is recorded."""

DATA = """
    SELECT
        CASE WHEN hash(i, {s}) % 10 = 0 THEN NULL
             ELSE 20 + hash(i, {s} + 1) % 50 END::DOUBLE AS age,
        CASE WHEN hash(i, {s} + 2) % 10 = 0 THEN NULL
             ELSE 1000 + hash(i, {s} + 3) % 4000 END::DOUBLE AS income,
        ['kyiv', 'oslo', 'rome'][1 + (hash(i, {s} + 4) % 3)::BIGINT] AS city,
        ['basic', 'pro', 'team'][1 + (hash(i, {s} + 5) % 3)::BIGINT] AS plan
    FROM range({n}) t(i)
"""
"""The slice's customers: two numbers with gaps, a city and a plan."""

VARIANTS = {
    "with OneHot": lambda: sq.Pipeline(
        [sq.impute.median(), sq.encode.onehot("city"), sq.scale.standard()]
    ),
    "without OneHot": lambda: sq.Pipeline([sq.impute.median(), sq.scale.standard()]),
}


def _bytes_read(con: duckdb.DuckDBPyConnection, statement: str, profile: Path) -> int:
    """Run a statement under DuckDB's JSON profiling and return the bytes it read."""
    con.execute("PRAGMA enable_profiling='json'")
    con.execute(f"PRAGMA profiling_output='{profile}'")
    con.execute(statement).fetchall()
    con.execute("PRAGMA disable_profiling")
    return int(json.loads(profile.read_text())["io"]["total_bytes_read"])


def _once(path: Path, make, out: Path) -> dict:
    """Learn and apply once, timing each; return the times and the pipeline."""
    STORE.clear()  # learn from scratch: no earlier repetition's answer is reused
    pipe = make()
    start = time.perf_counter()
    pipe.learn(str(path))
    learned = time.perf_counter()
    learn_runs = len(pipe.runs_)
    learn_statements = [s for run in pipe.runs_ for s in run.statements]
    pipe.apply(str(path), out=sq.out.parquet(out))
    end = time.perf_counter()
    return {
        "learn_s": learned - start,
        "apply_s": end - learned,
        "total_s": end - start,
        "runs": learn_runs,
        "apply_runs": len(pipe.runs_),
        "learn_statements": learn_statements,
        "apply_statements": [s for run in pipe.runs_ for s in run.statements],
    }


def measure(
    path: Path, scratch: Path, limit: str | None, threads: int | None = None
) -> dict[str, dict]:
    """Return, per variant, the median times, the runs and the bytes read.

    Each variant first runs once, discarded, to warm the file cache and the
    connection. The measured repetitions then alternate the variants' order,
    so neither always takes the first read of a file. The runs are checked:
    learning takes the variant's runs, and applying is one run.
    """
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{scratch / 'spill'}'")
    if threads:
        con.execute(f"SET threads = {threads}")
    if limit:
        con.execute(f"SET memory_limit = '{limit}'")
    sq.set_config(connection=con)
    out = scratch / "prepared.parquet"
    profile = scratch / "profile.json"
    names = list(VARIANTS)
    reps: dict[str, list[dict]] = {name: [] for name in names}
    results: dict[str, dict] = {}
    try:
        for name in names:  # the discarded warm-up
            try:
                _once(path, VARIANTS[name], out)
            except (duckdb.Error, SqlearnError) as error:
                results[name] = {
                    "result": "fail",
                    "error": str(error).splitlines()[0][:160],
                }
        live = [name for name in names if name not in results]
        for i in range(REPETITIONS):
            for name in live if i % 2 == 0 else live[::-1]:
                reps[name].append(_once(path, VARIANTS[name], out))
        for name in live:
            last = reps[name][-1]
            assert last["apply_runs"] == 1, "apply was not one run"
            read = sum(_bytes_read(con, s, profile) for s in last["learn_statements"])
            read_apply = sum(
                _bytes_read(con, f"COPY ({s}) TO '{out}' (FORMAT parquet)", profile)
                for s in last["apply_statements"]
            )
            results[name] = {
                "result": "pass",
                "runs": last["runs"],
                "learn_s": statistics.median(r["learn_s"] for r in reps[name]),
                "apply_s": statistics.median(r["apply_s"] for r in reps[name]),
                "total_s": statistics.median(r["total_s"] for r in reps[name]),
                "bytes_learn": read,
                "bytes_apply": read_apply,
            }
    finally:
        con.close()
        sq.set_config(connection=None)
    return results


def _show(rows: int, limit: str, results: dict[str, dict]) -> None:
    """Print a pair's rows; two out-of-memory failures print as one row."""
    if all(
        m["result"] == "fail" and "Out of Memory" in m["error"]
        for m in results.values()
    ):
        print(f"| {rows:,} | {limit} | both | out of memory | | | | | |")  # noqa: T201
    else:
        for name, m in results.items():
            print(_row(rows, limit, name, m))  # noqa: T201
    sys.stdout.flush()


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
        "duckdb": duckdb.__version__,
        "sqlearn": version("sqlearn"),
    }


def _row(rows: int, limit: str, name: str, m: dict) -> str:
    if m["result"] != "pass":
        return f"| {rows:,} | {limit} | {name} | failed: {m['error']} | | | | | |"
    return (
        f"| {rows:,} | {limit} | {name} | {m['runs']} | {m['learn_s']:.3f} | "
        f"{m['apply_s']:.3f} | {m['total_s']:.3f} | "
        f"{m['bytes_learn'] / 1e6:,.2f} | {m['bytes_apply'] / 1e6:,.2f} |"
    )


def main() -> None:
    """Generate the data, measure every size and the limit, print the tables."""
    print(json.dumps(_machine(), indent=2))  # noqa: T201
    print(  # noqa: T201
        "\n| rows | memory limit | pipeline | learn runs | learn s | apply s "
        "| total s | learn MB read | apply MB read |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    with tempfile.TemporaryDirectory(prefix="onehot_runs_") as tmp:
        root = Path(tmp)
        for n in SIZES:
            path = root / f"data_{n}.parquet"
            duckdb.execute(
                f"COPY ({DATA.format(s=SEED * 10, n=n)}) TO '{path}' (FORMAT parquet)"
            )
            _show(n, "none", measure(path, root, None))
        print(f"\nlarge file: {path.stat().st_size / 1e6:.1f} MB as Parquet")  # noqa: T201
        for threads in (None, 1):
            for limit in LIMITS:
                label = f"{limit}, {threads} thread" if threads else limit
                _show(SIZES[-1], label, measure(path, root, limit, threads))


if __name__ == "__main__":
    main()
