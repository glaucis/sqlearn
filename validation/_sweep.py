"""Every check in full, compared with what the selection chose (``just sweep``).

``run`` takes ``validation._affected.report`` and the tree first, then runs
each task of ``validation._checks.TASKS`` in full (``just full <task>``), in
the table's order, every one even when another fails. A task the report
called unchanged that fails in full is a missed rerun: the selection would
have skipped a failure. ``test`` is compared unit by unit: when it fails in
full, ``validation._ctest.due`` and ``validation._pytest_sets.due`` are asked
again, and a ``test: <label>`` or ``test: <set>`` the report called unchanged
that is now due failed in full (``run`` forgets a failed unit), a missed
rerun named as such. When no unit is named but the report called every unit
unchanged, ``test`` itself is the missed rerun; with no ``test: ...``
verdict, ``test`` counts as running. A pass is remembered in ``sweep.json``
in ``_checks.record_dir``, with the tree swept and the date; ``stale`` warns
when that is older than ``CADENCE_DAYS`` or missing, and ``just done`` prints
the warning.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from validation import _affected, _checks, _ctest, _pytest_sets

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
    """Return, for each task but ``test``, whether the report called it unchanged.

    A task with no verdict counts as running. ``test`` is compared unit by
    unit, by ``_missed_units``.
    """
    called = {v.check: not v.runs for v in verdicts}
    return {name: called.get(name, False) for name in _checks.TASKS if name != "test"}


def _due_units(root: Path) -> set[str]:
    """Return each test unit now due, as ``test: <label>`` or ``test: <set>``."""
    found = _ctest.due(_affected.PRESET, root) | _pytest_sets.due(root)
    return {f"test: {unit}" for unit, reasons in found.items() if reasons}


def _missed_units(verdicts: Sequence[_affected.Verdict], root: Path) -> list[str]:
    """Return the missed reruns among the test units, after ``test`` failed.

    A unit the report called unchanged that is due after the full run failed
    in it: ``run`` forgets a failed unit's identity. When none is, but the
    report called every unit unchanged, the failure is ``test``'s own.
    """
    units = [v for v in verdicts if v.check.startswith("test: ")]
    still = [v.check for v in units if not v.runs]
    due = _due_units(root)
    named = [unit for unit in still if unit in due]
    if named:
        return named
    return ["test"] if units and len(still) == len(units) else []


def _save(directory: Path, saved: dict[str, str]) -> None:
    """Write `saved` as ``sweep.json`` in `directory`, never half a file."""
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(saved) + "\n")
        os.replace(temporary, directory / SWEEP)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


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
    verdicts = _affected.report(root)
    unchanged = _unchanged(verdicts)
    tree, checkable = _tree(root)
    first = 0
    missed = []
    for name in _checks.TASKS:
        code = _full(name, root)
        if code == 0:
            continue
        first = first or code
        if name == "test":
            missed += _missed_units(verdicts, root)
        elif unchanged[name]:
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
    today = datetime.date.today().isoformat()
    _save(_checks.record_dir(root), {"tree": tree, "date": today})
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
