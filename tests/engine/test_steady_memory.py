"""Calls into the C++ hold no memory once they return (spec §3.9).

A process of its own makes 100,000 calls of ``count_rows`` and
``build_identity``, in 10 rounds, and reads its resident set from ``ps``
after each round, twice: a leak a call deep grows it round after round. The
peak (``ru_maxrss``) would hide memory handed back, so the set is read as
it is now (HANDOFF's trap).
"""

import json
import subprocess
import sys

import pytest

ROUNDS = 10
CALLS = 10_000
"""Each round's calls, half of each function: 100,000 calls in all."""

TOLERANCE = 0.05
"""How far round 10's resident set may lie from round 2's."""

PROGRAM = f"""
import json, os, subprocess
import duckdb
from sqlearn._native import build_identity, count_rows

def rss():
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())

con = duckdb.connect()
con.execute("CREATE TABLE t AS SELECT * FROM range(5)")
rounds = []
for _ in range({ROUNDS}):
    for _ in range({CALLS // 2}):
        assert count_rows(con, "t") == 5
        assert build_identity()
    rounds.append([rss(), rss()])
print(json.dumps(rounds))
"""


@pytest.mark.slow
def test_memory_levels_off() -> None:
    """After a first round that fills the caches, the resident set stays put:
    round 10's within 5 % of round 2's, each read twice."""
    done = subprocess.run(
        [sys.executable, "-c", PROGRAM], capture_output=True, text=True, check=True
    )
    rounds = json.loads(done.stdout.strip().splitlines()[-1])
    assert len(rounds) == ROUNDS
    second = max(rounds[1])
    last = max(rounds[-1])
    assert abs(last - second) <= TOLERANCE * second, rounds
