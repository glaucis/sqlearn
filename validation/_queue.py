"""Run every due benchmark and profile in turn, only while the machine is idle.

``just bench-queue`` is covered by one go-ahead (ADR 0081). The queue waits
for an idle machine (at most 30 minutes), then runs each name ``_bench.due``
lists: its benchmark, then its profile when both are due. Before each later
item it waits again, for at most 5 minutes, since the previous item's own
threads linger in the 1-minute load average; still busy, it stops and lists
what is left. A failed item is reported and the queue goes on.
"""

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from validation import _bench, _checks, _groups, _load, _profile

_LATER_LIMIT = 300
_LATER_EVERY = 30


def _later() -> bool:
    return _load.wait_for_idle(_LATER_LIMIT, _LATER_EVERY)


def _items(root: Path) -> list[_bench.Due]:
    """Return the due items in running order: a name's benchmark, then its profile."""
    listed = _bench.due(root)
    out: list[_bench.Due] = []
    for item in listed:
        if item.kind != "bench":
            continue
        out.append(item)
        out.extend(p for p in listed if p.kind == "profile" and p.name == item.name)
    out.extend(
        p
        for p in listed
        if p.kind == "profile" and not any(b.name == p.name for b in out)
    )
    return out


def presets(root: Path) -> list[str]:
    """Return the engine presets the due items need.

    Parameters
    ----------
    root : Path
        The repository's working tree, built.

    Returns
    -------
    list of str
        ``release`` when a due benchmark is a ``bench_`` program, ``profile``
        when a profile is due; empty when nothing needs one.
    """
    listed = _bench.due(root)
    out: list[str] = []
    if any(i.kind == "bench" and i.name.startswith("bench_") for i in listed):
        out.append("release")
    if any(i.kind == "profile" for i in listed):
        out.append("profile")
    return out


def _profile_needs_samply(root: Path) -> bool:
    """Return whether a profile is due and samply is missing."""
    return shutil.which("samply") is None and any(
        i.kind == "profile" for i in _bench.due(root)
    )


def _newest(root: Path, item: _bench.Due) -> dict[str, Any]:
    key = "profile" if item.kind == "profile" else "bench"
    records = _checks.load(_checks.record_dir(root), f"{key}-{item.name}")
    return dict(records[-1]) if records else {}


def _comparison(record: dict[str, Any], root: Path) -> str | None:
    summary = record.get("summary")
    if not summary:
        return None
    return str((root / str(summary)).with_name("compare.md").relative_to(root))


def _report(root: Path, items: list[_bench.Due], results: dict[int, str]) -> None:
    print("Queue report:")  # noqa: T201
    for index, item in enumerate(items):
        what = results.get(index, "not run")
        line = f"  {what}: {item.kind} {item.name}"
        if what == "ran":
            record = _newest(root, item)
            if "seconds" in record:
                line += (
                    f"  {record['seconds']:.1f} s, load "
                    f"{record.get('uptime_before', '?')} before, "
                    f"{record.get('uptime_after', '?')} after"
                )
                if record.get("loaded"):
                    line += " (machine loaded: stays due)"
            path = _comparison(record, root) if item.kind == "profile" else None
            if path:
                line += f"  (comparison: {path})"
        print(line)  # noqa: T201


def run(
    root: Path,
    wait: Callable[[], bool] = _load.wait_for_idle,
    later_wait: Callable[[], bool] = _later,
) -> int:
    """Run the due benchmarks and profiles, and report what ran.

    Parameters
    ----------
    root : Path
        The repository's working tree, built, with the presets the items need
        already built (``presets``).
    wait : callable
        Waits for an idle machine before the first item; False when it never
        came. Tests pass a fake.
    later_wait : callable
        The same before each later item, for a shorter time.

    Returns
    -------
    int
        0 when every item ran and none failed; 1 when one failed, the load
        stopped the queue, or a profile is due and samply is missing; 3 when
        the machine was never idle (nothing ran).
    """
    items = _items(root)
    if not items:
        print("nothing is due")  # noqa: T201
        return 0
    if any(i.kind == "profile" for i in items) and shutil.which("samply") is None:
        print("samply is not installed.\nFix: brew install samply")  # noqa: T201
        return 1
    if not wait():
        print(  # noqa: T201
            f"The machine was never idle: load {_load.now():.2f}, idle is below "
            f"{_load.threshold(_cores()):.2f}. Nothing ran."
        )
        return 3
    results: dict[int, str] = {}
    code = 0
    for index, item in enumerate(items):
        if index and not later_wait():
            print(  # noqa: T201
                f"The load rose (now {_load.now():.2f}): stopping, "
                f"{len(items) - index} left."
            )
            code = 1
            break
        runner = _bench.run if item.kind == "bench" else _profile.run
        try:
            status = runner(root, item.name)
        except _groups.Unreadable as error:
            print(f"{item.kind} {item.name}: {error}")  # noqa: T201
            status = 1
        if status == 0:
            results[index] = "ran"
        else:
            results[index] = f"failed (exit {status})"
            code = 1
    _report(root, items, results)
    return code


def _cores() -> int:
    return os.cpu_count() or 1


def cli(argv: Sequence[str], root: Path | None = None) -> int:
    """Parse ``presets`` or ``run`` and act in `root` (the current directory)."""
    here = root or Path.cwd()
    try:
        if argv == ["presets"]:
            if _profile_needs_samply(here):
                print(  # noqa: T201
                    "samply is not installed.\nFix: brew install samply",
                    file=sys.stderr,
                )
                return 1
            for preset in presets(here):
                print(preset)  # noqa: T201
            return 0
        if argv == ["run"]:
            return run(here)
    except _groups.Unreadable as error:
        print(f"queue: {error}", file=sys.stderr)  # noqa: T201
        return 1
    print("usage: python -m validation._queue presets | run")  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
