"""Mutation testing of sqlearn's C++ with Mull (``just mutate-engine``).

The ``mutate`` preset compiles our groups with Mull's plugin for LLVM 23
(``engine/cmake/hardening.cmake``), which builds every mutant of the paths
``engine/mull.yml`` takes into the programs, each off until mull-runner turns
it on. ``run`` runs mull-runner on each program of ``PROGRAMS``, mutants on
lines no test reaches included, into one SQLite report, then mull-reporter
over it, so a mutant counts as killed when any program kills it (a core
mutant the raw group's tests never reach is killed by core's). Results are
never cached: Mull's cache keeps a killed mutant killed after the tests
change.

A survivor (``Survived``, or ``NoCoverage``: no test reached it) fails the
run unless ``engine/mull.yml``'s ``survivors`` list names it with a reason;
an entry whose mutant no longer survives fails too, so the list stays true.
Mull reads the file's other keys and leaves that list alone. A mutant is
named ``<path under engine/>:<line>:<column>:<mutator>``.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROGRAMS = ("test_core", "test_raw")
"""The test programs Mull runs: each group's own."""

PRESET = "mutate"
"""The preset whose programs carry the mutants."""

SURVIVING = frozenset({"Survived", "NoCoverage"})
"""The statuses of a mutant no test killed, in Mull's Elements report."""

ENTRY = re.compile(r"^  - mutant: (\S+)\n    reason: *(.*)$", re.MULTILINE)
"""One entry of the ``survivors`` list: its mutant, then its reason."""


def _say(text: str, *, error: bool = False) -> None:
    """Print `text` at once (to stderr when `error`), before a program run after."""
    print(text, file=sys.stderr if error else sys.stdout, flush=True)


def survivors(report: dict[str, Any], engine: Path) -> set[str]:
    """Return the mutants of the report no test killed.

    Parameters
    ----------
    report : dict
        Mull's Elements report (mutation-testing-elements' JSON).
    engine : Path
        The ``engine`` directory, the root of the names.

    Returns
    -------
    set of str
        Each one as ``<path under engine/>:<line>:<column>:<mutator>``.
    """
    found: set[str] = set()
    for path, entry in report["files"].items():
        name = Path(path).relative_to(engine).as_posix()
        for mutant in entry["mutants"]:
            if mutant["status"] in SURVIVING:
                start = mutant["location"]["start"]
                found.add(
                    f"{name}:{start['line']}:{start['column']}:{mutant['mutatorName']}"
                )
    return found


def recorded(text: str) -> dict[str, str]:
    """Return the survivors ``mull.yml`` keeps, each with its reason.

    Parameters
    ----------
    text : str
        ``engine/mull.yml``.

    Returns
    -------
    dict of str to str
        Each mutant's reason.

    Raises
    ------
    ValueError
        With a ``Fix:`` line, when the list is missing, an entry has no
        reason, a mutant is named twice, or a line of the list is no entry.
    """
    form = "  - mutant: <path>:<line>:<column>:<mutator>\n    reason: <why it survives>"
    head = re.search(r"^survivors:(.*)$", text, re.MULTILINE)
    if head is None:
        raise ValueError(
            f"mull.yml has no survivors list.\nFix: add `survivors: []`, or\n{form}"
        )
    if head.group(1).strip() == "[]":
        return {}
    body = text[head.end() + 1 :]
    block = re.match(r"(?:(?:  .*|\s*#.*)?(?:\n|$))*", body)
    lines = block.group(0) if block else ""
    kept: dict[str, str] = {}
    for match in ENTRY.finditer(lines):
        mutant, reason = match.group(1), match.group(2).strip()
        if not reason:
            raise ValueError(
                f"mull.yml keeps {mutant} with no reason.\nFix: give it one:\n{form}"
            )
        if mutant in kept:
            raise ValueError(f"mull.yml keeps {mutant} twice.\nFix: keep one entry")
        kept[mutant] = reason
    rest = ENTRY.sub("", lines)
    stray = [
        x for x in rest.splitlines() if x.strip() and not x.strip().startswith("#")
    ]
    if stray:
        raise ValueError(
            "mull.yml's survivors list has a line that is no entry: "
            f"{stray[0].strip()}\n"
            f"Fix: write each as\n{form}"
        )
    return kept


def verdict(found: set[str], kept: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return the survivors with no entry, and the entries with no survivor.

    Parameters
    ----------
    found : set of str
        ``survivors``' result.
    kept : dict of str to str
        ``recorded``'s result.

    Returns
    -------
    (list of str, list of str)
        Both sorted; the run passes when both are empty.
    """
    return sorted(found - kept.keys()), sorted(kept.keys() - found)


def run(engine: Path, tools: Path) -> int:
    """Run Mull on each program of ``PROGRAMS`` and judge the survivors.

    Parameters
    ----------
    engine : Path
        The ``engine`` directory, its ``mutate`` preset built.
    tools : Path
        The directory of ``mull-runner`` and ``mull-reporter``.

    Returns
    -------
    int
        0 when every survivor is kept with a reason and every entry still
        survives; Mull's exit code when it fails; 1 otherwise.
    """
    config = engine / "mull.yml"
    try:
        kept = recorded(config.read_text())
    except ValueError as error:
        _say(str(error), error=True)
        return 1
    build = engine / "build" / PRESET
    out = build / "mull"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = dict(os.environ, MULL_CONFIG=str(config))
    report = ["--report-dir", str(out), "--report-name", "engine"]
    for program in PROGRAMS:
        done = subprocess.run(
            [
                str(tools / "mull-runner"),
                "--allow-surviving",
                "--include-not-covered",
                "--no-cache",
                "--no-output",
                # Homebrew LLVM's libc++, which the programs load through their rpath
                "--ld-search-path",
                "/opt/homebrew/opt/llvm/lib/c++",
                "--reporters",
                "SQLite",
                *report,
                str(build / program),
            ],
            env=env,
            check=False,
        )
        if done.returncode != 0:
            _say(f"mull-runner failed on {program}.", error=True)
            return done.returncode
    done = subprocess.run(
        [
            str(tools / "mull-reporter"),
            "--allow-surviving",
            "--reporters",
            "Elements",
            *report,
            str(out / "engine.sqlite"),
        ],
        env=env,
        check=False,
    )
    if done.returncode != 0:
        _say("mull-reporter failed.", error=True)
        return done.returncode
    elements = json.loads((out / "engine.json").read_text())
    total = sum(len(entry["mutants"]) for entry in elements["files"].values())
    found = survivors(elements, engine)
    unrecorded, stale = verdict(found, kept)
    _say(
        f"\nmutants: {total}, killed: {total - len(found)}, kept survivors: {len(kept)}"
    )
    if unrecorded:
        _say("\nSurvivors with no reason in engine/mull.yml:", error=True)
        for name in unrecorded:
            _say(f"  {name}", error=True)
        _say(
            "Fix: add the test that kills each (the report is "
            f"{(out / 'engine.html').relative_to(engine.parent)}); keep one only "
            "with its reason in mull.yml's survivors",
            error=True,
        )
    if stale:
        _say(
            "\nEntries of engine/mull.yml whose mutant no longer survives:",
            error=True,
        )
        for name in stale:
            _say(f"  {name}", error=True)
        _say("Fix: remove them from mull.yml's survivors", error=True)
    return 1 if unrecorded or stale else 0


def cli(argv: Sequence[str]) -> int:
    """Run Mull on the working tree's engine.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name: the directory of Mull's tools.

    Returns
    -------
    int
        ``run``'s exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._mutate")
    parser.add_argument(
        "tools", type=Path, help="the directory of mull-runner and mull-reporter"
    )
    args = parser.parse_args(argv)
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return run(Path(top) / "engine", args.tools.resolve())


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
