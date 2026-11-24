"""The coverage gate of sqlearn's C++ (``just coverage-engine``).

The ``coverage`` preset builds our groups and their tests with Clang's
source-based coverage (``-fprofile-instr-generate -fcoverage-mapping``,
``engine/cmake/hardening.cmake``) under Homebrew LLVM, whose
``llvm-profdata`` and ``llvm-cov`` read the profile format its clang
writes. ``run`` runs every CTest test of that build with
``LLVM_PROFILE_FILE`` pointing at a fresh directory, merges the profiles,
prints llvm-cov's report of ``engine/src/`` (lines, regions, functions and
branches, per file), and fails when fewer than ``FLOOR`` per cent of the
lines ran.

The report reads ``engine/src/`` alone, so the tests, the fuzz targets, the
benchmarks, the test libraries and the standard library are never in it;
the bindings (``engine/src/bindings/``) are left out too, since they are
built only in the wheel and run from Python, uninstrumented. A ``.cpp`` of
``engine/src/`` that no test program compiles would be missing from the
totals unseen, so it fails the gate, named with a ``Fix:`` line.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

LLVM = Path("/opt/homebrew/opt/llvm/bin")
"""Homebrew LLVM's tools: the formula is keg-only, so they are off ``PATH``."""

FLOOR = 95.0
"""The least per cent of lines that must run, as the Python package's floor."""

PRESET = "coverage"
"""The preset the gate measures."""

KINDS = ("lines", "regions", "branches")
"""The totals printed; only the lines are gated."""


def _say(text: str, *, error: bool = False) -> None:
    """Print `text` at once (to stderr when `error`), before a program run after."""
    print(text, file=sys.stderr if error else sys.stdout, flush=True)


def programs(listing: dict[str, Any], build: Path) -> list[Path]:
    """Return the programs of the build the tests run, each once, sorted.

    Parameters
    ----------
    listing : dict
        CTest's ``--show-only=json-v1`` listing.
    build : Path
        The build directory.

    Returns
    -------
    list of Path
        Each test's program, when it is a file inside `build`; a test whose
        command is another program (cmake, for the must-not-compile tests)
        has none.
    """
    found: set[Path] = set()
    for test in listing.get("tests", []):
        command = test.get("command")
        if not command:
            continue
        program = Path(command[0])
        if program.is_relative_to(build) and program.is_file():
            found.add(program)
    return sorted(found)


def totals(export: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """Return the covered and the count of each kind in ``KINDS``.

    Parameters
    ----------
    export : dict
        ``llvm-cov export -summary-only``'s JSON.

    Returns
    -------
    dict of str to (int, int)
        Covered, count, for each kind llvm-cov reported.
    """
    found = export["data"][0]["totals"]
    return {
        kind: (int(found[kind]["covered"]), int(found[kind]["count"]))
        for kind in KINDS
        if kind in found
    }


def unmeasured(src: Path, export: dict[str, Any]) -> list[Path]:
    """Return the ``.cpp`` files of `src` outside bindings/ the report lacks.

    Parameters
    ----------
    src : Path
        ``engine/src``.
    export : dict
        ``llvm-cov export``'s JSON.

    Returns
    -------
    list of Path
        The sources no test program compiled, sorted.
    """
    reported = {Path(f["filename"]) for f in export["data"][0]["files"]}
    return [
        path
        for path in sorted(src.rglob("*.cpp"))
        if not path.is_relative_to(src / "bindings") and path not in reported
    ]


def passes(found: dict[str, tuple[int, int]]) -> bool:
    """Return whether at least ``FLOOR`` per cent of the lines ran.

    Parameters
    ----------
    found : dict of str to (int, int)
        ``totals``' result.

    Returns
    -------
    bool
        False also when there are no lines at all.
    """
    covered, count = found.get("lines", (0, 0))
    return count > 0 and 100.0 * covered >= FLOOR * count


def report_arguments(
    engine: Path, profile: Path, binaries: Sequence[Path]
) -> list[str]:
    """Return llvm-cov's arguments for the report of ``engine/src``.

    Parameters
    ----------
    engine : Path
        The ``engine`` directory.
    profile : Path
        The merged profile.
    binaries : sequence of Path
        The instrumented programs, at least one.

    Returns
    -------
    list of str
        The profile, the bindings left out, the programs (the first
        positional, each other after ``-object``) and the sources.
    """
    first, *others = binaries
    arguments = [f"-instr-profile={profile}", "-ignore-filename-regex=/src/bindings/"]
    arguments.append(str(first))
    for other in others:
        arguments += ["-object", str(other)]
    arguments.append(str(engine / "src"))
    return arguments


def run(engine: Path) -> int:
    """Run the tests of the coverage build, print the report, and gate it.

    Parameters
    ----------
    engine : Path
        The ``engine`` directory, its ``coverage`` preset built.

    Returns
    -------
    int
        0 when the gate passes; the tests' exit code when they fail; 1
        otherwise.
    """
    build = engine / "build" / PRESET
    profiles = build / "profiles"
    shutil.rmtree(profiles, ignore_errors=True)
    profiles.mkdir(parents=True)
    env = dict(os.environ, LLVM_PROFILE_FILE=str(profiles / "%p-%m.profraw"))
    tests = subprocess.run(
        ["ctest", "--preset", PRESET], cwd=engine, env=env, check=False
    )
    if tests.returncode != 0:
        _say("The C++ tests failed under the coverage build.", error=True)
        return tests.returncode
    listing = subprocess.run(
        ["ctest", "--preset", PRESET, "--show-only=json-v1"],
        cwd=engine,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    binaries = programs(json.loads(listing), build)
    raw = sorted(profiles.glob("*.profraw"))
    if not binaries or not raw:
        _say(
            "No instrumented program ran, so nothing was measured.\n"
            "Fix: just build-engine coverage, then check that ctest --preset coverage "
            "lists the groups' programs",
            error=True,
        )
        return 1
    profile = build / "coverage.profdata"
    subprocess.run(
        [
            str(LLVM / "llvm-profdata"),
            "merge",
            "-sparse",
            *map(str, raw),
            "-o",
            str(profile),
        ],
        check=True,
    )
    arguments = report_arguments(engine, profile, binaries)
    subprocess.run(
        [str(LLVM / "llvm-cov"), "report", "-show-branch-summary", *arguments],
        check=True,
    )
    export = json.loads(
        subprocess.run(
            [str(LLVM / "llvm-cov"), "export", "-summary-only", *arguments],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    found = totals(export)
    _say("")
    for kind in KINDS:
        covered, count = found.get(kind, (0, 0))
        share = f"{100.0 * covered / count:.2f} %" if count else "-"
        gated = f" (gate: {FLOOR:g} %)" if kind == "lines" else " (not gated)"
        _say(f"{kind}: {covered}/{count}, {share}{gated}")
    failed = False
    missing = unmeasured(engine / "src", export)
    if missing:
        names = ", ".join(str(p.relative_to(engine)) for p in missing)
        _say(
            f"\nNo test program compiles {names}, so its lines are in no total.\n"
            "Fix: give its group TESTS in engine/CMakeLists.txt (sq_add_group)",
            error=True,
        )
        failed = True
    if not passes(found):
        _say(
            f"\nLines of engine/src outside bindings/ are below {FLOOR:g} %.\n"
            "Fix: add the tests the report's missed lines show "
            "(llvm-cov show, with the same arguments, marks them)",
            error=True,
        )
        failed = True
    return 1 if failed else 0


def cli(argv: Sequence[str]) -> int:
    """Run the gate on the working tree's engine.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name (none).

    Returns
    -------
    int
        ``run``'s exit code.
    """
    argparse.ArgumentParser(prog="python -m validation._coverage").parse_args(argv)
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return run(Path(top) / "engine")


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
