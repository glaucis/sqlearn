"""Measure how many rows the exact median learns under a memory limit (#27).

``sq.agg.median`` is computed by sorting (ADR 0032), and DuckDB's sort has a
reach. For each memory limit (one thread) this script finds, by doubling and
then bisecting on the row count, the largest count whose ``sq.impute.median``
learns, and the smallest that fails. Each probe is one fresh subprocess, so an
out-of-memory error or a kill cannot take the run down, and learns from a
Parquet file written once per probe by DuckDB (the rows come from ``range()``
and a fixed seed, never from Python). The boundary points are then repeated
three times for their times. It prints Markdown tables; it decides nothing.

With ``mad`` it measures the median absolute deviation instead,
``median(abs(x - median(x)))``: two sorts, one per level (ADR 0051, #49).

Run it with ``uv run python -m validation.benchmarks.median_reach [mad]``. Files go
under ``SQLEARN_BENCH_DIR`` (default: a temporary directory) and are removed.
Not part of ``just test``.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import duckdb

from validation.benchmarks.category_lookup import _machine

PAGE = "docs/benchmarks/median-reach.md"
"""The page of ``docs/benchmarks`` this script's numbers feed."""
GROUPS: tuple[str, ...] | None = None
"""The C++ groups it measures; None for every group (ADR 0072)."""

SEED = 0
"""The data comes from this seed: generated, never downloaded."""

LIMITS = ("32MB", "64MB", "128MB")
"""The memory limits measured, each on one thread."""

START = 5_000_000
"""The first probe; it doubles until a probe fails or the cap is reached."""

CAP = 640_000_000
"""The largest probe: about 4 GB of Parquet. A learn that passes here is
recorded as "at least" this many rows."""

TOLERANCE = 1.1
"""Bisection stops when the failing count is within this factor of the passing."""

REPEATS = 3
"""Runs at each boundary point."""

TIMEOUT = 3 * 3600
"""Seconds before a probe is abandoned and recorded as failed."""

DATA = """
    SELECT CASE WHEN hash(i, {s}) % 10 = 0 THEN NULL
                ELSE 1000 + ((hash(i, {s} + 1) % 2000001)::DOUBLE - 1000000) / 10000
           END AS x
    FROM range({n}) t(i)
"""
"""One DOUBLE column: a tenth NULL, the rest spread evenly over 900 to 1,100."""


class Mad:
    """Make the step learning each column's median absolute deviation."""

    @staticmethod
    def step(column: str) -> object:
        """Return a step learning ``median(abs(x - median(x)))`` of `column`."""
        import sqlearn as sq

        class _Mad(sq.Step):
            def learn(self, x):
                return {"mad": sq.agg.median(sq.fn.abs(x - sq.agg.median(x)))}

            def apply(self, x, learned):
                return x

        return _Mad(cols=[column])


def _worker(path: str, limit: str, spill: str, what: str = "median") -> None:
    """Learn the median (or ``mad``) from ``path``; print the seconds as JSON."""
    import sqlearn as sq
    from sqlearn._store import STORE

    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{limit}'")
    con.execute("SET threads = 1")
    con.execute(f"SET temp_directory = '{spill}'")
    sq.set_config(connection=con)
    STORE.clear()
    start = time.perf_counter()
    step = Mad.step("x") if what == "mad" else sq.impute.median("x")
    sq.Pipeline([step]).learn(path)
    print(json.dumps({"s": time.perf_counter() - start}))  # noqa: T201


WHAT = "median"
"""What is learned: ``median``, or ``mad`` (set from the command line)."""


def _probe(rows: int, limit: str, root: Path) -> tuple[bool, float | None, str]:
    """Learn ``rows`` rows under ``limit`` in a fresh subprocess."""
    path = root / f"x_{rows}.parquet"
    spill = root / "spill"
    spill.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"COPY ({DATA.format(s=SEED, n=rows)}) TO '{path}' (FORMAT parquet)")
    con.close()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "validation.benchmarks.median_reach",
             "--worker", str(path), limit, str(spill), WHAT],
            capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return False, None, "timeout"
    finally:
        path.unlink(missing_ok=True)
        for f in spill.glob("*"):
            f.unlink(missing_ok=True)
    if done.returncode == 0:
        return True, json.loads(done.stdout.strip().splitlines()[-1])["s"], ""
    errors = [x for x in done.stderr.splitlines() if "Exception" in x or "Error" in x]
    last = (errors or done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[
        -1
    ]
    return False, None, last[:120]


def _reach(limit: str, root: Path) -> tuple[int, int | None, list[str]]:
    """Return (largest passing rows, smallest failing rows or None, notes)."""
    notes: list[str] = []
    lo, hi = 0, None
    n = START
    while True:
        ok, _, why = _probe(n, limit, root)
        print(f"  {limit} {n:,} rows: {'ok' if ok else 'failed ' + why}", flush=True)  # noqa: T201
        if ok:
            lo = n
            if n >= CAP:
                return lo, None, notes
            n = min(n * 2, CAP)
        else:
            hi = n
            notes.append(why)
            break
    while hi > lo * TOLERANCE and hi - lo > 1:
        mid = (lo + hi) // 2 if lo else hi // 2
        ok, _, why = _probe(mid, limit, root)
        print(f"  {limit} {mid:,} rows: {'ok' if ok else 'failed ' + why}", flush=True)  # noqa: T201
        if ok:
            lo = mid
        else:
            hi = mid
            notes.append(why)
    return lo, hi, notes


def main() -> None:
    """Measure every limit and print the tables."""
    print(json.dumps(_machine(), indent=2))  # noqa: T201
    base = os.environ.get("SQLEARN_BENCH_DIR")
    with tempfile.TemporaryDirectory(prefix="median_reach_", dir=base) as tmp:
        root = Path(tmp)
        rows = []
        for limit in LIMITS:
            lo, hi, notes = _reach(limit, root)
            times = [_probe(lo, limit, root)[1] for _ in range(REPEATS)]
            fails = [_probe(hi, limit, root)[0] for _ in range(REPEATS)] if hi else []
            rows.append((limit, lo, hi, times, fails, notes[-1:]))
        print(  # noqa: T201
            "\n| limit | largest passing rows | smallest failing rows "
            "| passing runs s | failing probe, 3 runs | failure |\n"
            "|---|---|---|---|---|---|"
        )
        for limit, lo, hi, times, fails, note in rows:
            t = ", ".join(f"{x:.1f}" for x in times if x is not None)
            f = (
                "none"
                if hi is None
                else ("all failed" if not any(fails) else str(fails))
            )
            h = f"{hi:,}" if hi else f"none up to {CAP:,}"
            print(f"| {limit} | {lo:,} | {h} | {t} | {f} | {''.join(note)} |")  # noqa: T201


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _worker(*sys.argv[2:6])
    else:
        WHAT = sys.argv[1] if len(sys.argv) > 1 else "median"
        main()
