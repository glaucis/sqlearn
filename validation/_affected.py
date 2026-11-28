"""For each check, whether ``just done`` would run it and why; runs no check.

Each task of ``validation._checks.TASKS`` answers through ``_checks.why``,
except ``test``, whose steps keep records of their own: it answers as one
verdict per C++ label (``validation._ctest.due`` on ``dev``, which builds the
preset) and per Python test set (``validation._pytest_sets.due``), named
``test: <label>`` and ``test: <set>``. No step runs and no record is written.
``validate``'s runners keep records of their own and are not covered.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from validation import _checks, _ctest, _pytest_sets

PRESET = "dev"
"""The preset ``just test`` runs the C++ groups on."""


@dataclass(frozen=True)
class Verdict:
    """Whether one check would run, and why.

    Attributes
    ----------
    check : str
        The check: a task's name, or ``test: <label>`` and ``test: <set>``.
    runs : bool
        Whether ``just done`` would run it.
    reasons : tuple of str
        Why it would run, empty when it would not.
    """

    check: str
    runs: bool
    reasons: tuple[str, ...]


def _verdict(check: str, reasons: Sequence[str]) -> Verdict:
    """Return the verdict of `check` given its `reasons`."""
    return Verdict(check=check, runs=bool(reasons), reasons=tuple(reasons))


def report(root: Path) -> list[Verdict]:
    """Return each check's verdict, in the order of ``TASKS``.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    list of Verdict
        One per task, ``test`` replaced by one per C++ label, by name, then
        one per Python test set.
    """
    verdicts = []
    for name, task in _checks.TASKS.items():
        if name != "test":
            verdicts.append(_verdict(name, _checks.why(task, root)))
            continue
        labels = _ctest.due(PRESET, root)
        verdicts.extend(_verdict(f"test: {k}", labels[k]) for k in sorted(labels))
        found = _pytest_sets.due(root)
        verdicts.extend(_verdict(f"test: {k}", v) for k, v in found.items())
    return verdicts


def cli(argv: Sequence[str]) -> int:
    """Print each check, ``runs`` or ``unchanged``, then its reasons indented.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name: none.

    Returns
    -------
    int
        0: what would run is no failure.
    """
    argparse.ArgumentParser(
        prog="python -m validation._affected",
        description="Print whether just done would run each check, and why.",
    ).parse_args(argv)
    for verdict in report(_checks._root()):
        lines = [f"{verdict.check}: {'runs' if verdict.runs else 'unchanged'}"]
        lines += [f"  {reason}" for reason in verdict.reasons]
        print("\n".join(lines), flush=True)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
