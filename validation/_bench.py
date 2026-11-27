"""The benchmarks that are out of date, and the one run on request.

No check runs a benchmark (ADR 0072): ``due`` only lists, and ``run`` is what
``just bench <name>`` calls after Tomas's go-ahead. A benchmark is a page
script in ``validation/benchmarks`` or a C++ program a group claims
(``BENCH`` of ``sq_add_group``). Its identity is the bytes of its script (or
the source of its program), the identity of the C++ groups it measures
(``_groups.identity``), the Python it times (``src``, ``validation`` and the
settings, hashed as the library's tests are; a program's
binary instead) in this place; it is due when no record has it. A
script names its page and its groups in two module constants, ``PAGE`` and
``GROUPS`` (None for every group), read here without running the script.

The records are one file for each benchmark, ``bench-<name>``, in the same
directory as the checks' (``_checks.record_dir``). A run records its wall
time, its cores (user plus system time over the wall time, of the child), its
peak memory and the load (``uptime``) before and after.
"""

import ast
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from validation import _checks, _groups, _pytest_sets

SCRIPTS = Path("validation/benchmarks")
"""Where the page scripts are, relative to the root."""

PROGRAMS = Path("engine/bench")
"""Where the sources of the C++ programs are, relative to the root."""

PROGRAM_BINARIES = Path("engine/build/release/bench")
"""Where ``just bench-engine`` builds the programs, relative to the root."""

_KEY = "bench"


@dataclass(frozen=True)
class Due:
    """One benchmark out of date, and what its last run measured.

    Attributes
    ----------
    name : str
        The script's name, or ``bench_<name>`` for a C++ program.
    page : str
        The page it feeds (``docs/benchmarks/*.md``); empty for a program
        that prints its table and has none.
    last_seconds, last_cores, last_peak_mb : float or None
        The newest record's wall time, cores and peak memory; None when it
        never ran.
    """

    name: str
    page: str
    last_seconds: float | None
    last_cores: float | None
    last_peak_mb: float | None


@dataclass(frozen=True)
class _Benchmark:
    name: str
    page: str
    groups: tuple[str, ...] | None
    source: Path
    argv: tuple[str, ...]
    program: bool = False


def _constants(script: Path) -> tuple[str, tuple[str, ...] | None]:
    """Return the script's ``PAGE`` and ``GROUPS``, read without running it."""
    found: dict[str, Any] = {}
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as error:
        raise _groups.Unreadable(f"{script} could not be read: {error}") from error
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in ("PAGE", "GROUPS"):
                try:
                    found[target.id] = ast.literal_eval(value)
                except ValueError as error:
                    raise _groups.Unreadable(
                        f"{script}: {target.id} is not a literal"
                    ) from error
    page, groups = found.get("PAGE"), found.get("GROUPS", ...)
    if not isinstance(page, str):
        raise _groups.Unreadable(f"{script} names no PAGE (a string)")
    if groups is ...:
        raise _groups.Unreadable(f"{script} names no GROUPS (a tuple or None)")
    if groups is not None and not (
        isinstance(groups, tuple) and all(isinstance(g, str) for g in groups)
    ):
        raise _groups.Unreadable(f"{script}: GROUPS is not a tuple of names or None")
    return page, groups


def _benchmarks(root: Path, groups: dict[str, _groups.Group]) -> list[_Benchmark]:
    """Return every benchmark: the page scripts, then the groups' programs."""
    found: list[_Benchmark] = []
    folder = root / SCRIPTS
    for script in sorted(folder.glob("[!_]*.py")) if folder.is_dir() else []:
        page, uses = _constants(script)
        found.append(
            _Benchmark(
                script.stem,
                page,
                uses,
                script,
                (sys.executable, "-m", f"validation.benchmarks.{script.stem}"),
            )
        )
    programs = sorted(
        (entry, group.name) for group in groups.values() for entry in group.bench
    )
    for entry, owner in programs:
        name = f"bench_{entry}"
        found.append(
            _Benchmark(
                name,
                "",
                (owner,),
                root / PROGRAMS / f"{name}.cpp",
                (str(root / PROGRAM_BINARIES / name),),
                program=True,
            )
        )
    return found


def _library(root: Path) -> str:
    """Return the SHA-256 of the Python a script times: what the library's tests read.

    The library, the validation (every helper a script imports, and the
    cases), the data of development and the settings, as the library test
    sets hash them (``_pytest_sets``).
    """
    files = set(_checks._listed(_pytest_sets.LIBRARY_INPUTS, root))
    files |= set(_checks._listed(_checks.SETTINGS, root))
    return _checks._combined(sorted(files), root, {})


def _identity(
    item: _Benchmark,
    prints: _groups.Fingerprints,
    groups: dict[str, _groups.Group],
    library: str,
) -> str:
    """Return the SHA-256 of what `item` measured.

    Its bytes, its groups, the place, and the Python it times (`library`);
    for a program, the binary's bytes instead of the Python, as the one that
    runs is the one measured.
    """
    try:
        source = item.source.read_bytes()
    except OSError as error:
        raise _groups.Unreadable(f"{item.source} could not be read: {error}") from error
    if item.program:
        try:
            measured = hashlib.sha256(Path(item.argv[0]).read_bytes()).hexdigest()
        except OSError:
            measured = "no binary"
    else:
        measured = library
    parts = [
        item.name.encode(),
        hashlib.sha256(source).hexdigest().encode(),
        _groups.identity(prints, groups, item.groups).encode(),
        measured.encode(),
        _checks.place().encode(),
    ]
    return hashlib.sha256(b"\0".join(parts)).hexdigest()


def _records(root: Path, name: str) -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]", _checks.load(_checks.record_dir(root), f"{_KEY}-{name}")
    )


def due(root: Path) -> list[Due]:
    """Return the benchmarks whose identity has no record. Runs none.

    Parameters
    ----------
    root : Path
        The repository's working tree, built (``_groups.WHEEL_BUILD``).

    Returns
    -------
    list of Due
        Each out-of-date benchmark with what its newest record measured.

    Raises
    ------
    validation._groups.Unreadable
        A manifest, a fingerprint or a script's constants cannot be read.
    """
    groups, _ = _groups.load(root / _groups.WHEEL_BUILD)
    benchmarks = _benchmarks(root, groups)
    prints = _groups.fingerprints(root, _groups.WHEEL_BUILD)
    library = _library(root)
    out: list[Due] = []
    for item in benchmarks:
        records = _records(root, item.name)
        if any(
            r["digest"] == _identity(item, prints, groups, library) for r in records
        ):
            continue
        last = records[-1] if records else None
        out.append(
            Due(
                item.name,
                item.page,
                last["seconds"] if last else None,
                last["cores"] if last else None,
                last["peak_mb"] if last else None,
            )
        )
    return out


def _uptime() -> str:
    try:
        return subprocess.run(
            ["uptime"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return "unknown"


def run(root: Path, name: str) -> int:
    """Run the benchmark `name`, record it when it succeeds, return its exit code.

    Parameters
    ----------
    root : Path
        The repository's working tree, built.
    name : str
        A benchmark's name, as ``due`` lists it.

    Returns
    -------
    int
        The benchmark's exit code; 2 when `name` is no benchmark.
    """
    groups, _ = _groups.load(root / _groups.WHEEL_BUILD)
    chosen = [b for b in _benchmarks(root, groups) if b.name == name]
    if not chosen:
        print(f"no benchmark {name}: `just benchmarks-due` lists them")  # noqa: T201
        return 2
    item = chosen[0]
    identity = _identity(
        item,
        _groups.fingerprints(root, _groups.WHEEL_BUILD),
        groups,
        _library(root),
    )
    before = _uptime()
    start = time.perf_counter()
    try:
        child = subprocess.Popen(item.argv, cwd=root)
    except OSError as error:
        print(f"{name} did not start: {error}")  # noqa: T201
        return 127
    _, status, usage = os.wait4(child.pid, 0)
    wall = time.perf_counter() - start
    child.returncode = os.waitstatus_to_exitcode(status)
    after = _uptime()
    if child.returncode != 0:
        return child.returncode
    record = {
        "digest": identity,
        "config": name,
        "files": {},
        "seconds": wall,
        "cores": (usage.ru_utime + usage.ru_stime) / wall,
        "peak_mb": usage.ru_maxrss
        / (1024 * 1024 if sys.platform == "darwin" else 1024),
        "uptime_before": before,
        "uptime_after": after,
    }
    _checks.save(
        _checks.record_dir(root),
        f"{_KEY}-{name}",
        cast("_checks.Record", record),
    )
    return 0


def _line(item: Due) -> str:
    page = item.page or "no page"
    if item.last_seconds is None:
        return f"{item.name}  ({page})  never run"
    return (
        f"{item.name}  ({page})  last {item.last_seconds:.1f} s, "
        f"{item.last_cores:.1f} cores, {item.last_peak_mb:.0f} MB"
    )


def cli(argv: Sequence[str]) -> int:
    """Parse ``due`` or ``run <name>`` and act in the current directory."""
    root = Path.cwd()
    try:
        if argv[:1] == ["due"] and len(argv) == 1:
            listed = due(root)
            for item in listed:
                print(_line(item))  # noqa: T201
            if not listed:
                print("no benchmark is due")  # noqa: T201
            return 0
        if argv[:1] == ["run"] and len(argv) == 2:
            return run(root, argv[1])
    except _groups.Unreadable as error:
        print(f"benchmarks: {error}")  # noqa: T201
        return 1
    print("usage: python -m validation._bench due | run <name>")  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
