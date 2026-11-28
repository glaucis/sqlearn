"""The Python tests by set, each run only when its identity changed since it passed.

The tests fall into sets (``sets``):

- ``tooling``: the tests of the checks, the hooks, the engine's build, the
  docs and the datasets of development (``TOOLING``). They read the
  engine's files as text (presets, ``mull.yml``, the fuzz corpus, the CMake
  files, the C++ comments included), the package's modules and
  ``.clangd``, and some load the module, so their identity is the SHA-256
  of ``TOOLING_INPUTS``' files and the module's whole identity: any engine
  or ``src/`` edit reruns them, a minute at most.
- ``group:<name>``: the tests a C++ group claims (its ``PYTHON_TESTS`` in
  the manifest), whose identity is the SHA-256 of its own test files, every
  file of ``LIBRARY_INPUTS`` (``src/``, since ``import sqlearn`` loads the
  whole package, and what the tests import beside it), the shared test
  files (every file under ``tests/src/``, the other sets' tests included,
  since a test module may import another's, the ``conftest.py`` files
  above its paths, ``tests/public_api.*``) and the
  module as the group's closure reads it (``validation._groups.identity``).
- ``unclaimed``: every test under ``tests/src/`` no group claims, the same
  way, with every group, as what no group claims depends on all of them.

Each identity also holds the settings every task reads
(``validation._checks.SETTINGS``: the locked versions, pytest's
configuration) and the place it runs in. A set whose identity a kept record
passed prints ``<set>: unchanged since a passed run``; each other set runs
the passes of ``PASSES`` on its paths; a pass that finds no test passes, a
set none of whose passes finds one fails. The records follow
``validation._ctest``'s rules, under the key ``pytest-sets``: a set that
fails takes its identity out of every kept record, and a set whose identity
moved while it ran (taken again after the run) is not recorded. When the
fingerprints cannot be read, the reason is printed and every set runs, none
recorded. ``due`` says which sets ``run`` would run and why, running none
(``just affected``).
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from validation import _checks, _ctest, _groups

TOOLING = _checks.TOOLING
"""The tooling tests' paths."""

TOOLING_INPUTS = _checks.TOOLING_INPUTS
"""What the tooling tests import or read, every file as text."""

LIBRARY_INPUTS = (
    "src",
    # What the library tests import beside sqlearn: the validation's cases.
    "validation",
)
"""What every library set imports or reads, its own test files aside."""

LIBRARY = "tests/src"
"""Where the library tests live: each in a group's set or the unclaimed one."""

PASSES = (
    ("-n", "auto", "-m", "not slow and not serial"),
    ("-p", "no:xdist", "-m", "serial and not slow"),
    ("-p", "no:xdist", "-m", "slow"),
)
"""The fast tests in parallel, the serial ones alone, the slow tier."""

NO_TESTS = 5
"""pytest's exit code when it collects no test: a pass of a set may find none
(a set need not hold every tier), but a set none of whose passes finds a test
fails, since a path or a marker is broken."""

KEY = "pytest-sets"
"""The records' file in ``sqlearn-checks/``, without ``.json``."""

Sets = dict[str, tuple[tuple[str, ...], set[str] | None]]
"""Each set's name with its test paths and the groups it uses (None: every one)."""


def _say(text: str) -> None:
    """Print `text` at once, before the output of a program run after it."""
    print(text, flush=True)  # noqa: T201


def _is_test(name: str) -> bool:
    """Return whether the file `name` is one pytest collects."""
    base = name.rsplit("/", 1)[-1]
    return base.endswith(".py") and (
        base.startswith("test_") or base.endswith("_test.py")
    )


def _under(name: str, path: str) -> bool:
    """Return whether `name` is the path `path` or lies under it."""
    return name == path or name.startswith(f"{path.rstrip('/')}/")


def _compact(directory: str, tests: list[str], claimed: list[str]) -> list[str]:
    """Return `tests` under `directory` no claim covers, as few paths as can be.

    A directory none of whose tests is claimed stands for all of them.
    """
    mine = [t for t in tests if _under(t, directory)]
    if not any(_under(t, c) for t in mine for c in claimed):
        return [directory] if mine else []
    found: list[str] = []
    children = sorted({t[len(directory) + 1 :].split("/", 1)[0] for t in mine})
    for child in children:
        path = f"{directory}/{child}"
        if path in mine:
            if not any(_under(path, c) for c in claimed):
                found.append(path)
        else:
            found.extend(_compact(path, mine, claimed))
    return found


def sets(groups: dict[str, _groups.Group], root: Path) -> Sets:
    """Return the Python test sets of the tree under `root`.

    Parameters
    ----------
    groups : dict of str to Group
        The manifest's groups, whose ``python_tests`` claim paths.
    root : Path
        The repository's working tree.

    Returns
    -------
    dict
        ``tooling``, then ``group:<name>`` for each group claiming tests,
        then ``unclaimed``: each with its test paths, relative to `root`,
        and the groups it uses, None for every group. A set with no path is
        left out.

    Raises
    ------
    ValueError
        A test file under ``tests/`` lies in no set, so would never run.
    """
    tests = [n for n in _checks._listed(["tests"], root) if _is_test(n)]
    found: Sets = {}
    tooling = tuple(p for p in TOOLING if (root / p).exists())
    if tooling:
        found["tooling"] = (tooling, None)
    claimed: list[str] = []
    for name in sorted(groups):
        paths = groups[name].python_tests
        if paths:
            found[f"group:{name}"] = (tuple(paths), {name})
            claimed.extend(paths)
    unclaimed = _compact(LIBRARY, tests, claimed)
    if unclaimed:
        found["unclaimed"] = (tuple(unclaimed), None)
    covered = [*tooling, *claimed, LIBRARY]
    loose = [t for t in tests if not any(_under(t, p) for p in covered)]
    if loose:
        raise ValueError(
            f"Python tests: {', '.join(loose)} lie in no test set, so would "
            "never run.\n"
            f"Fix: move them under {LIBRARY}/, claim them in a group's "
            "PYTHON_TESTS (sq_add_group), or add their directory to TOOLING "
            "(validation/_checks.py)"
        )
    return found


def _shared(paths: Sequence[str]) -> list[str]:
    """Return the pathspecs of the test files a library set shares with others.

    Every file under ``tests/src/``, the other sets' tests included (a test
    module may import another's: ``_saving/test_learned`` imports
    ``test_recipe``; any ``src/`` edit reruns them all anyway), the public
    API's lists, and each ``conftest.py`` from the root down to each of
    `paths`.
    """
    specs = {
        LIBRARY,
        ":(glob)tests/public_api.*",
        "conftest.py",
    }
    for path in paths:
        parts = path.split("/")
        specs.update(
            "/".join([*parts[:i], "conftest.py"]) for i in range(1, len(parts))
        )
    return sorted(specs)


def _files(specs: Sequence[str], root: Path) -> set[str]:
    """Return the present files under `specs`, tracked or not ignored."""
    return set(_checks._listed(specs, root))


def _read(root: Path) -> _groups.Fingerprints | _groups.Unreadable:
    """Return the module's fingerprints, or why they cannot be read."""
    try:
        return _groups.fingerprints(root, _groups.WHEEL_BUILD)
    except _groups.Unreadable as error:
        return error


def _identities(
    chosen: Sets, prints: _groups.Fingerprints | _groups.Unreadable, root: Path
) -> dict[str, str] | None:
    """Return each set of `chosen` with its identity, None when unreadable.

    The reason is printed when the fingerprints cannot be read.
    """
    try:
        if isinstance(prints, _groups.Unreadable):
            raise prints
        modules = {
            name: _groups.identity(prints, prints.manifest, uses)
            for name, (_, uses) in chosen.items()
        }
    except _groups.Unreadable as error:
        _say(
            f"Python tests: the C++ groups are unreadable: {error}\n"
            "every set runs, and none is recorded"
        )
        return None
    settings = _files(_checks.SETTINGS, root)
    found = {}
    for name, (paths, _) in chosen.items():
        if name == "tooling":
            files = _files(TOOLING_INPUTS, root)
            links = _checks._gitlinks(TOOLING_INPUTS, root)
        else:
            files = _files(paths, root) | _files(LIBRARY_INPUTS, root)
            files |= _files(_shared(paths), root)
            links = {}
        combined = _checks._combined(sorted(files | settings), root, links)
        whole = f"{name}\0{combined}\0{modules[name]}"
        found[name] = hashlib.sha256(whole.encode()).hexdigest()
    return found


def _run_set(paths: Sequence[str], root: Path) -> int:
    """Run every pass of ``PASSES`` on `paths`; return the first failing code.

    A pass that collects nothing (``NO_TESTS``) passes, unless every pass
    does: then the set fails with ``NO_TESTS``.
    """
    codes = []
    for options in PASSES:
        argv = ["pytest", "-p", "validation._tests_report", *options, *paths]
        codes.append(subprocess.run(argv, cwd=root, check=False).returncode)
    if all(code == NO_TESTS for code in codes):
        return NO_TESTS
    return next((c for c in codes if c not in {0, NO_TESTS}), 0)


def _manifest(
    prints: _groups.Fingerprints | _groups.Unreadable, root: Path
) -> tuple[dict[str, _groups.Group], str | None]:
    """Return the manifest's groups and why it cannot be read, if it cannot.

    With no groups the sets are those of none, and a claim outside
    ``tests/src`` would read as a loose file: the reason lets the caller
    say so instead of asking for a claim.

    The fingerprints carry it; when they cannot be read (a missing compile
    database, say) the manifest alone is loaded. ``_identities`` says why
    the fingerprints cannot be read: the sets are then those of no group.
    """
    if not isinstance(prints, _groups.Unreadable):
        return prints.manifest, None
    try:
        return _groups.load(root / _groups.WHEEL_BUILD)[0], None
    except _groups.Unreadable as error:
        return {}, str(error)


def _loose(error: ValueError, why: str | None) -> str:
    """Return `error`'s text, led by `why` the groups are unreadable if so.

    The ``Fix:`` that asks for a claim in a group's ``PYTHON_TESTS`` cannot be
    followed while the manifest is unreadable; the unreadable reason replaces
    it.
    """
    if why is None:
        return str(error)
    head = str(error).split("\nFix:", 1)[0]
    return (
        f"Python tests: the C++ groups are unreadable: {why}\n"
        f"{head}\nFix: make the manifest readable (build the engine: just "
        "build-engine dev), then rerun"
    )


def due(root: Path) -> dict[str, list[str]]:
    """Return each Python test set with why ``run`` would run it; runs none.

    It writes no record.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    dict of str to list of str
        Each set with its reasons, empty when unchanged since a passed run.
        When a test file lies in no set, one entry, ``sets``, says so; when
        the fingerprints cannot be read, every set runs, for that reason.
    """
    root = root.resolve()
    prints = _read(root)
    groups, why = _manifest(prints, root)
    try:
        chosen = sets(groups, root)
    except ValueError as error:
        return {"sets": [_loose(error, why)]}
    found = _identities(chosen, prints, root)
    if found is None:
        return {name: ["the C++ groups are unreadable"] for name in chosen}
    return _ctest.reasons(
        found,
        _checks.record_dir(root),
        KEY,
        "its tests, what they read or the settings changed",
    )


def run(root: Path, *, everything: bool = False) -> int:
    """Run each Python test set whose identity no kept record passed.

    Parameters
    ----------
    root : Path
        The repository's working tree.
    everything : bool
        Run every set, recorded or not, and record the passes.

    Returns
    -------
    int
        The first failing code of a set (every set runs, a failing one
        included), 1 when a test file lies in no set; else 0.
    """
    root = root.resolve()
    prints = _read(root)
    groups, why = _manifest(prints, root)
    try:
        chosen = sets(groups, root)
    except ValueError as error:
        _say(_loose(error, why))
        return 1
    before = _identities(chosen, prints, root)
    directory = _checks.record_dir(root)
    passed = _ctest.passed(directory, KEY)
    good: dict[str, str] = {}
    failed: dict[str, str] = {}
    ran = []
    first = 0
    for name, (paths, _) in chosen.items():
        if before is not None and not everything and (name, before[name]) in passed:
            _say(f"{name}: unchanged since a passed run")
            good[name] = before[name]
            continue
        _say(f"{name}: {' '.join(paths)}")
        code = _run_set(paths, root)
        if code != 0:
            first = first or code
            if before is not None:
                failed[name] = before[name]
            continue
        ran.append(name)
    if before is None:
        return first
    if failed:
        _ctest._forget(directory, KEY, failed)
    after = _identities(chosen, _read(root), root) if ran else {}
    recorded = False
    for name in ran:
        if after is None or after[name] != before[name]:
            _say(f"{name}: not recorded, its inputs changed while it ran")
            continue
        good[name] = before[name]
        recorded = True
    if recorded:
        whole = hashlib.sha256(json.dumps(good, sort_keys=True).encode()).hexdigest()
        _checks.save(
            directory,
            KEY,
            _checks.Record(digest=whole, config=_checks.place(), files=good),
        )
    return first


def _root() -> Path:
    """Return the working tree holding the current directory."""
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(top)


def cli(argv: Sequence[str]) -> int:
    """Parse ``[--all]`` and run the sets of the current working tree.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name.

    Returns
    -------
    int
        ``run``'s exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._pytest_sets")
    parser.add_argument(
        "--all", action="store_true", help="run every set, recorded or not"
    )
    args = parser.parse_args(argv)
    return run(_root(), everything=args.all)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
