"""Each group's C++ tests, run only when what they run changed since they passed.

The engine's CTest tests carry one label per group (``sq_add_group``,
``engine/cmake/groups.cmake``); the must-not-compile tests share the label
``must_not_compile``, one unit like a group. ``run`` builds a preset (Ninja
rebuilds only what changed), lists the tests and runs each label whose
identity no kept record passed, printing ``<label>: unchanged since a passed
run`` for the rest.

A label's identity is the SHA-256 of the place (``validation._checks``'s,
then the preset's compiler id and version), the label, and for each of its
tests its CTest entry (name, command, properties) and the bytes of each file
its command names: a group's program, whose bytes stand for its sources,
since Ninja relinks it only when an object changed and ``sq_stable_link``
makes a relink of the same objects the same bytes. A test with no program of
its own, one that builds a target (``cmake --build ... --target <t>``, the
must-not-compile tests), adds that target's compile commands, its sources'
bytes and every header under the directories its commands include with
``-I``; with no compile command to show what builds it, it runs every time
and is never recorded.

The records follow ``validation._checks``'s rules: the file
``ctest-<preset>.json`` in ``sqlearn-checks/`` of git's common directory, the
newest ``KEPT`` records, written to a temporary file then moved into place,
an unreadable one counting as absent. A record names every label passed in a
run or found unchanged; a failed label is not in it. The identity taken
before a label runs is the one recorded, and only when it is unchanged after.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from validation import _checks

HEADERS = frozenset({".h", ".hh", ".hpp", ".hxx", ".inc", ".ipp"})
"""The suffixes of the headers a target's include directories hold."""

TOOLS = ("cmake", "ctest", "ninja")
"""The programs a run needs on ``PATH``."""

Test = dict[str, Any]
"""One test of ``ctest --show-only=json-v1``."""


def compiler(build: Path) -> str:
    """Return the C++ compiler's id and version, as `build`'s CMake found them.

    Parameters
    ----------
    build : Path
        A configured build directory.

    Returns
    -------
    str
        Each ``CMAKE_CXX_COMPILER_ID`` and ``CMAKE_CXX_COMPILER_VERSION`` line
        of its ``CMakeCXXCompiler.cmake``, one per line; empty when none.
    """
    keys = ("set(CMAKE_CXX_COMPILER_ID ", "set(CMAKE_CXX_COMPILER_VERSION ")
    return "\n".join(
        line
        for found in sorted(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
        for line in found.read_text(encoding="utf-8").splitlines()
        if line.startswith(keys)
    )


def _place(build: Path) -> str:
    """Return the SHA-256 of the checks' place and the preset's compiler."""
    where = _checks.place() + "\0" + compiler(build)
    return hashlib.sha256(where.encode()).hexdigest()


def _build(preset: str, engine: Path) -> int:
    """Configure and build `preset` in `engine`; return the first failing code."""
    for argv in (
        ["cmake", "--preset", preset],
        ["cmake", "--build", "--preset", preset, "--parallel"],
    ):
        code = subprocess.run(argv, cwd=engine, check=False).returncode
        if code != 0:
            return code
    return 0


def _tests(build: Path) -> list[Test]:
    """Return the tests CTest lists in `build`."""
    listing = subprocess.run(
        ["ctest", "--test-dir", str(build), "--show-only=json-v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tests: list[Test] = json.loads(listing)["tests"]
    return tests


def _labels(test: Test) -> list[str]:
    """Return the labels of `test`, empty for none."""
    for prop in test.get("properties", []):
        if prop.get("name") == "LABELS":
            return [str(label) for label in prop.get("value", [])]
    return []


def _targets(command: Sequence[str]) -> list[str]:
    """Return the targets a ``--target`` of `command` names."""
    return [
        command[i + 1]
        for i, arg in enumerate(command[:-1])
        if arg in {"--target", "-t"}
    ]


def _arguments(entry: dict[str, Any]) -> list[str]:
    """Return a compile command's argv, from ``arguments`` or ``command``."""
    if "arguments" in entry:
        return [str(a) for a in entry["arguments"]]
    return shlex.split(str(entry.get("command", "")))


def _includes(entry: dict[str, Any]) -> list[Path]:
    """Return the directories a compile command includes with ``-I``."""
    argv = _arguments(entry)
    here = Path(str(entry.get("directory", ".")))
    found = []
    for i, arg in enumerate(argv):
        if arg == "-I" and i + 1 < len(argv):
            found.append(argv[i + 1])
        elif arg.startswith("-I") and len(arg) > 2:
            found.append(arg[2:])
    return [here / d for d in found]


class _Hasher:
    """The SHA-256 of files, each read once per identity."""

    def __init__(self) -> None:
        self._seen: dict[Path, str] = {}

    def file(self, path: Path) -> str:
        """Return the SHA-256 of `path`'s bytes."""
        if path not in self._seen:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            self._seen[path] = digest.hexdigest()
        return self._seen[path]


def _compile_entries(build: Path) -> list[dict[str, Any]]:
    """Return `build`'s compile commands, none when it has no such file."""
    path = build / "compile_commands.json"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return entries


def _target_parts(
    target: str, entries: Iterable[dict[str, Any]], hasher: _Hasher
) -> list[str]:
    """Return what builds `target`: its compile commands, sources and headers."""
    parts = []
    headers: set[Path] = set()
    marker = f"/CMakeFiles/{target}.dir/"
    for entry in entries:
        if marker not in str(entry.get("output", "")):
            continue
        source = Path(str(entry["directory"])) / str(entry["file"])
        parts.append(shlex.join(_arguments(entry)))
        parts.append(f"{source}\0{hasher.file(source)}")
        for directory in _includes(entry):
            if directory.is_dir():
                headers.update(
                    p
                    for p in directory.rglob("*")
                    if p.suffix in HEADERS and p.is_file()
                )
    if not parts:
        # Nothing says what builds it (no compile_commands.json, or a target
        # of no source): an identity of its own each time, so it always runs.
        parts.append(f"unknown\0{os.urandom(16).hex()}")
    parts.extend(f"{h}\0{hasher.file(h)}" for h in sorted(headers))
    return parts


def _identities(units: dict[str, list[Test]], build: Path) -> dict[str, str]:
    """Return each label of `units` with the SHA-256 of what its tests run."""
    hasher = _Hasher()
    entries = _compile_entries(build)
    place = _place(build)
    found = {}
    for label, tests in units.items():
        sha = hashlib.sha256(f"{place}\0{label}\0".encode())
        for test in sorted(tests, key=lambda t: str(t.get("name"))):
            entry = {k: test.get(k) for k in ("name", "command", "properties")}
            sha.update(json.dumps(entry, sort_keys=True).encode() + b"\0")
            command = [str(a) for a in test.get("command") or []]
            for arg in command:
                path = Path(arg)
                if path.is_absolute() and path.is_file():
                    sha.update(f"{arg}\0{hasher.file(path)}\0".encode())
            for target in _targets(command):
                for part in _target_parts(target, entries, hasher):
                    sha.update(part.encode() + b"\0")
        found[label] = sha.hexdigest()
    return found


def _units(tests: list[Test]) -> tuple[dict[str, list[Test]], list[str]]:
    """Return the tests by label, and the names of those with no label."""
    units: dict[str, list[Test]] = {}
    loose = []
    for test in tests:
        labels = _labels(test)
        if not labels:
            loose.append(str(test.get("name")))
        for label in labels:
            units.setdefault(label, []).append(test)
    return units, loose


def _say(text: str) -> None:
    """Print `text` at once, before the output of a program run after it."""
    print(text, flush=True)  # noqa: T201


def _run_label(build: Path, label: str) -> int:
    """Run the tests labelled exactly `label`; return CTest's exit code."""
    argv = [
        "ctest",
        "--test-dir",
        str(build),
        "-L",
        f"^{re.escape(label)}$",
        "--output-on-failure",
    ]
    return subprocess.run(argv, check=False).returncode


def run(preset: str, root: Path, *, everything: bool = False) -> int:
    """Build `preset` and run each label whose identity no record passed.

    Parameters
    ----------
    preset : str
        A preset of ``engine/CMakePresets.json``, built into
        ``engine/build/<preset>``.
    root : Path
        The repository's working tree.
    everything : bool
        Run every label, recorded or not, and record the passes.

    Returns
    -------
    int
        The first failing code: the build's, a test's (every label runs, a
        failing one included), or 1 for a missing tool or a test no label
        selects; else 0.
    """
    root = root.resolve()
    engine = root / "engine"
    build = engine / "build" / preset
    missing = [t for t in TOOLS if shutil.which(t) is None]
    if missing:
        _say(
            f"C++ tests: {', '.join(missing)} not on PATH.\n"
            "Fix: run `just doctor`, then install what it names"
        )
        return 1
    code = _build(preset, engine)
    if code != 0:
        _say(f"C++ tests: the {preset} build failed; no test ran, none recorded")
        return code
    units, loose = _units(_tests(build))
    if loose:
        _say(
            f"C++ tests: {', '.join(sorted(loose))} carry no label, so no "
            "group would run them.\n"
            "Fix: add them with sq_add_group, or set_tests_properties(<test> "
            "PROPERTIES LABELS <group>)"
        )
        return 1
    key = f"ctest-{preset}"
    directory = _checks.record_dir(root)
    passed = {
        (label, sha)
        for record in _checks.load(directory, key)
        for label, sha in record["files"].items()
    }
    before = _identities(units, build)
    good: dict[str, str] = {}
    ran = []
    first = 0
    for label in sorted(units):
        if not everything and (label, before[label]) in passed:
            _say(f"{label}: unchanged since a passed run")
            good[label] = before[label]
            continue
        code = _run_label(build, label)
        if code != 0:
            first = first or code
            continue
        ran.append(label)
    after = _identities(units, build) if ran else {}
    recorded = False
    for label in ran:
        if after[label] != before[label]:
            _say(
                f"{label}: not recorded, what it runs changed while it ran or "
                "is not known (no compile_commands.json)"
            )
            continue
        good[label] = before[label]
        recorded = True
    if recorded:
        whole = hashlib.sha256(json.dumps(good, sort_keys=True).encode()).hexdigest()
        _checks.save(
            directory,
            key,
            _checks.Record(digest=whole, config=_place(build), files=good),
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
    """Parse ``<preset> [--all]`` and run it in the current working tree.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name.

    Returns
    -------
    int
        ``run``'s exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._ctest")
    parser.add_argument("preset", help="the preset to build and test, as dev")
    parser.add_argument(
        "--all", action="store_true", help="run every group, recorded or not"
    )
    args = parser.parse_args(argv)
    return run(args.preset, _root(), everything=args.all)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
