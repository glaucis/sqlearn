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
peak memory and the load (``uptime``) before and after. A run that ends on a
busy machine (``_load.loaded_after``: the load less its own cores) is marked
``loaded``: it is kept, but only a clean record (``clean``) clears "due" or
gives the last numbers.
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

from validation import _checks, _groups, _load, _pytest_sets

SCRIPTS = Path("validation/benchmarks")
"""Where the page scripts are, relative to the root."""

PROGRAMS = Path("engine/bench")
"""Where the sources of the C++ programs are, relative to the root."""

PROGRAM_BUILD = Path("engine/build/release")
"""The release build the programs are built in, relative to the root."""

PROGRAM_BINARIES = PROGRAM_BUILD / "bench"
"""Where ``just bench-engine`` builds the programs, relative to the root."""

PROFILE_BUILD = Path("engine/build/profile")
"""The profile build the programs are profiled from, relative to the root."""

PROFILE_BINARIES = PROFILE_BUILD / "bench"
"""Where the profile build keeps the programs, relative to the root."""

_KEY = "bench"
_PROFILE_KEY = "profile"


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
        The newest clean record's wall time, cores and peak memory; None when it
        never ran. A profile has seconds only.
    kind : str
        ``"bench"`` for a benchmark, ``"profile"`` for the profile of a C++
        program (``profile-<name>`` records).
    """

    name: str
    page: str
    last_seconds: float | None
    last_cores: float | None
    last_peak_mb: float | None
    kind: str = "bench"


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
    binary: Path | None = None,
) -> str:
    """Return the SHA-256 of what `item` measured.

    Its bytes, its groups, the place, and the Python it times (`library`);
    for a program, the binary's bytes instead of the Python, as the one that
    runs is the one measured (`binary` names another, the profile build's).
    """
    try:
        source = item.source.read_bytes()
    except OSError as error:
        raise _groups.Unreadable(f"{item.source} could not be read: {error}") from error
    if item.program:
        try:
            measured = hashlib.sha256(
                (binary or Path(item.argv[0])).read_bytes()
            ).hexdigest()
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


def _records(root: Path, name: str, key: str = _KEY) -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]", _checks.load(_checks.record_dir(root), f"{key}-{name}")
    )


def programs(root: Path) -> list[str]:
    """Return the names of the C++ benchmark programs, ``bench_<name>``.

    Parameters
    ----------
    root : Path
        The repository's working tree, built (``_groups.WHEEL_BUILD``).

    Returns
    -------
    list of str
        Each program a group claims, in ``due``'s order.
    """
    groups = _groups.fingerprints(root, _groups.WHEEL_BUILD).manifest
    return [b.name for b in _benchmarks(root, groups) if b.program]


def profile_identity(root: Path, name: str) -> str:
    """Return the SHA-256 of what the profile of the program `name` measured.

    As a benchmark's identity, with the profile build's binary
    (``PROFILE_BINARIES``) in place of the release one; "no binary" when it
    is not built.

    Parameters
    ----------
    root : Path
        The repository's working tree, built.
    name : str
        A program's name, ``bench_<name>``.

    Returns
    -------
    str
        The hex digest.

    Raises
    ------
    validation._groups.Unreadable
        A manifest, a fingerprint or the program's source cannot be read, or
        `name` is no program.
    """
    prints = _groups.fingerprints(root, _groups.WHEEL_BUILD)
    groups = prints.manifest
    for item in _benchmarks(root, groups):
        if item.program and item.name == name:
            return _identity(item, prints, groups, "", root / PROFILE_BINARIES / name)
    raise _groups.Unreadable(f"no benchmark program {name}")


def clean(record: dict[str, Any]) -> bool:
    """Return whether `record` was measured on an idle machine.

    Parameters
    ----------
    record : dict
        A benchmark record; one without ``loaded`` is clean.

    Returns
    -------
    bool
        True unless the record is marked ``loaded``.
    """
    return not record.get("loaded", False)


def due(root: Path) -> list[Due]:
    """Return the benchmarks and profiles whose identity has no clean record.

    Runs none. The profiles, one for each C++ program, come after the
    benchmarks.

    Parameters
    ----------
    root : Path
        The repository's working tree, built (``_groups.WHEEL_BUILD``).

    Returns
    -------
    list of Due
        Each out-of-date benchmark with what its newest clean record measured.

    Raises
    ------
    validation._groups.Unreadable
        A manifest, a fingerprint or a script's constants cannot be read.
    """
    prints = _groups.fingerprints(root, _groups.WHEEL_BUILD)
    groups = prints.manifest
    benchmarks = _benchmarks(root, groups)
    library = _library(root)
    out: list[Due] = []
    for item in benchmarks:
        records = [r for r in _records(root, item.name) if clean(r)]
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
    for item in benchmarks:
        if not item.program:
            continue
        records = [r for r in _records(root, item.name, _PROFILE_KEY) if clean(r)]
        identity = _identity(
            item, prints, groups, "", root / PROFILE_BINARIES / item.name
        )
        if any(r["digest"] == identity for r in records):
            continue
        out.append(
            Due(
                item.name,
                "",
                records[-1]["seconds"] if records else None,
                None,
                None,
                "profile",
            )
        )
    return out


def _out_of_date(root: Path, name: str, build_dir: Path = PROGRAM_BUILD) -> str | None:
    """Return why the program `name` is not built as its sources are, or None.

    ``ninja -n`` lists the work the build (`build_dir`, relative to the root:
    the release build, or the profile one) would do; any means the binary is
    not what the sources make. Nothing is rebuilt here.
    """
    build = root / build_dir
    if not build.is_dir():
        return f"its build {build} does not exist"
    try:
        done = subprocess.run(
            ["ninja", "-C", str(build), "-n", name],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return f"ninja could not run: {error}"
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip()[:200]
        return f"ninja could not list its work: {said}"
    work = [
        line
        for line in done.stdout.splitlines()
        if line and not line.startswith("ninja:")
    ]
    if work:
        return f"{name} is out of date ({work[0]})"
    return None


def _uptime() -> str:
    try:
        return subprocess.run(
            ["uptime"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return "unknown"


@dataclass(frozen=True)
class Measured:
    """What one timed child run showed.

    Attributes
    ----------
    returncode : int
        The child's exit code.
    wall : float
        Its wall time, in seconds.
    cores : float
        User plus system time over the wall time.
    peak_mb : float
        Its peak memory, in MB.
    before, after : str
        The load (``uptime``) before and after the run.
    """

    returncode: int
    wall: float
    cores: float
    peak_mb: float
    before: str
    after: str


def measure(argv: Sequence[str], cwd: Path) -> Measured:
    """Run `argv` in `cwd` and time it: the one measuring block of every record.

    Parameters
    ----------
    argv : sequence of str
        The command.
    cwd : Path
        Its working directory.

    Returns
    -------
    Measured
        Its exit code, wall time, cores, peak memory and the load around it.

    Raises
    ------
    OSError
        The command did not start.
    """
    before = _uptime()
    start = time.perf_counter()
    child = subprocess.Popen(argv, cwd=cwd)
    _, status, usage = os.wait4(child.pid, 0)
    wall = time.perf_counter() - start
    child.returncode = os.waitstatus_to_exitcode(status)
    return Measured(
        returncode=child.returncode,
        wall=wall,
        cores=(usage.ru_utime + usage.ru_stime) / wall,
        peak_mb=usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024),
        before=before,
        after=_uptime(),
    )


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
        The benchmark's exit code; 2 when `name` is no benchmark; 1 when it
        is a C++ program whose build is out of date (it is never rebuilt
        here).
    """
    prints = _groups.fingerprints(root, _groups.WHEEL_BUILD)
    groups = prints.manifest
    chosen = [b for b in _benchmarks(root, groups) if b.name == name]
    if not chosen:
        print(f"no benchmark {name}: `just benchmarks-due` lists them")  # noqa: T201
        return 2
    item = chosen[0]
    if item.program:
        stale = _out_of_date(root, name)
        if stale is not None:
            print(  # noqa: T201
                f"{name}: not run, {stale}.\n"
                f"Fix: just bench {name} (it builds the program first)"
            )
            return 1
    identity = _identity(
        item,
        prints,
        groups,
        _library(root),
    )
    try:
        measured = measure(item.argv, root)
    except OSError as error:
        print(f"{name} did not start: {error}")  # noqa: T201
        return 127
    if measured.returncode != 0:
        return measured.returncode
    record = {
        "digest": identity,
        "config": name,
        "files": {},
        "seconds": measured.wall,
        "cores": measured.cores,
        "peak_mb": measured.peak_mb,
        "uptime_before": measured.before,
        "uptime_after": measured.after,
        "loaded": _load.loaded_after(measured.cores),
    }
    _checks.save(
        _checks.record_dir(root),
        f"{_KEY}-{name}",
        cast("_checks.Record", record),
    )
    return 0


def _line(item: Due) -> str:
    if item.kind == "profile":
        if item.last_seconds is None:
            return f"profile {item.name}  never run"
        return f"profile {item.name}  last {item.last_seconds:.1f} s"
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
