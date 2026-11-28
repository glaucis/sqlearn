"""Every check in full, compared with what the selection chose (``just sweep``).

``run`` takes ``validation._affected.report`` and the tree first, then runs
each task of ``validation._checks.TASKS`` in full (``just full <task>``), in
the table's order, every one even when another fails. A task the report
called unchanged that fails in full is a missed rerun: the selection would
have skipped a failure. ``test`` counts as unchanged only when the report has
a ``test: <label>`` or ``test: <set>`` verdict and every one is unchanged.
A pass is remembered in ``sweep.json`` in ``_checks.record_dir``, with the
tree swept and the date; ``stale`` warns when that is older than
``CADENCE_DAYS`` or missing, and ``just done`` prints the warning.
"""

import argparse
import datetime
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from validation import _affected, _checks

CADENCE_DAYS: int = 7
"""How many days a sweep counts as recent. Set by Tomas on 2026-11-28."""

SWEEP = "sweep.json"
"""The file in the records' directory holding the last passed sweep."""

FIX = (
    "Fix: run just affected, find the input the check reads but does not "
    "declare, and add it"
)
"""The fix of a missed rerun."""


def _just(root: Path, *args: str) -> list[str]:
    """Return the command running ``just <args>`` on `root`'s justfile."""
    return ["just", "--justfile", str(root / "justfile"), *args]


def _full(task: str, root: Path) -> int:
    """Run ``just full <task>`` in `root` and return its exit code."""
    return subprocess.run(_just(root, "full", task), cwd=root, check=False).returncode


def _tree(root: Path) -> tuple[str, bool]:
    """Return the tree to remember, and whether it is the checkable tree.

    Read before the checks run, so the tree saved is the one swept.

    The checkable tree (``just checkable-tree``) when only the checks' own
    outputs differ from HEAD, else HEAD's tree.
    """
    checkable = subprocess.run(
        _just(root, "checkable-tree"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if checkable:
        return checkable, True
    head = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return head, False


def _unchanged(verdicts: Sequence[_affected.Verdict]) -> dict[str, bool]:
    """Return, for each task, whether the report called it unchanged."""
    called = {v.check: not v.runs for v in verdicts}
    tests = [not v.runs for v in verdicts if v.check.startswith("test: ")]
    return {
        name: bool(tests) and all(tests) if name == "test" else called.get(name, False)
        for name in _checks.TASKS
    }


def run(root: Path) -> int:
    """Run every check in full and compare with what the selection chose.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    int
        1 when a check the report called unchanged fails (a missed rerun),
        else the first failing check's code, else 0, the pass then saved.
    """
    unchanged = _unchanged(_affected.report(root))
    tree, checkable = _tree(root)
    first = 0
    missed = []
    for name in _checks.TASKS:
        code = _full(name, root)
        if code == 0:
            continue
        first = first or code
        if unchanged[name]:
            missed.append(name)
    for name in missed:
        print(  # noqa: T201
            f"\n{name}: a missed rerun: the selection called it unchanged, "
            f"but it fails in full.\n{FIX}",
            flush=True,
        )
    if missed:
        return 1
    if first:
        print(  # noqa: T201
            "\nSweep failed: only checks the selection would run failed. "
            "Not remembered.",
            flush=True,
        )
        return first
    directory = _checks.record_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    (directory / SWEEP).write_text(
        json.dumps({"tree": tree, "date": today}) + "\n", encoding="utf-8"
    )
    if not checkable:
        print(  # noqa: T201
            f"\nThe tree is uncommitted: remembered HEAD's tree {tree} instead.",
            flush=True,
        )
    print(f"\nSweep passed on tree {tree}: no missed rerun.", flush=True)  # noqa: T201
    return 0


def _last(root: Path) -> datetime.date | None:
    """Return the date of the last passed sweep, None when none is readable."""
    path = _checks.record_dir(root) / SWEEP
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        return datetime.date.fromisoformat(saved["date"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def stale(root: Path, today: datetime.date) -> str | None:
    """Return the warning when the last sweep is old or missing, else None.

    Parameters
    ----------
    root : Path
        The repository's working tree.
    today : datetime.date
        The day to measure the sweep's age from.

    Returns
    -------
    str or None
        The warning, ending with its ``Fix:`` line, when no sweep passed
        here or the last is older than ``CADENCE_DAYS``; None otherwise.
    """
    last = _last(root)
    if last is None:
        return "No sweep has passed here.\nFix: run just sweep"
    age = (today - last).days
    if age <= CADENCE_DAYS:
        return None
    return (
        f"The last sweep passed {age} days ago ({last.isoformat()}), more than "
        f"{CADENCE_DAYS}.\nFix: run just sweep"
    )


def cli(argv: Sequence[str]) -> int:
    """Run the sweep, or with ``--stale`` print its warning if any.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name.

    Returns
    -------
    int
        The sweep's exit code; 0 with ``--stale``, which runs nothing.
    """
    parser = argparse.ArgumentParser(
        prog="python -m validation._sweep",
        description="Run every check in full and compare with the selection.",
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="print the warning when the last sweep is old, and run nothing",
    )
    args = parser.parse_args(argv)
    root = _checks._root()
    if args.stale:
        warning = stale(root, datetime.date.today())
        if warning is not None:
            print(warning, flush=True)  # noqa: T201
        return 0
    return run(root)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
