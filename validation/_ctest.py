"""Each group's C++ tests, run only when what they run changed since they passed.

The engine's CTest tests carry one label per group (``sq_add_group``,
``engine/cmake/groups.cmake``); the must-not-compile tests share the label
``must_not_compile``, one unit like a group. ``run`` builds a preset (Ninja
rebuilds only what changed), lists the tests and runs each label whose
identity no kept record passed, printing ``<label>: unchanged since a passed
run`` for the rest. ``due`` builds the same way and says which labels
``run`` would run and why, running none (``just affected``).

A label's identity is the SHA-256 of the place, the label, and for each of
its tests:

- its CTest entry (name, command, properties);
- the bytes of each file its command names: a group's program, whose bytes
  stand for its sources, since Ninja relinks it only when an object changed
  and ``sq_stable_link`` makes a relink of the same objects the same bytes;
- for a program of the build, the bytes of every shared library it loads
  outside the system's (``/usr/lib/``, ``/System/``, ``/lib/``): the
  sanitizers' runtime, another libc++, a library of the build;
- the bytes of the files it reads at run time (CTest's ``REQUIRED_FILES``,
  ``sq_test_data``);
- for a test that builds a target (``cmake --build ... --target <t>``, the
  must-not-compile tests, which have no program): that target's compile
  commands, the bytes of every file the compiler reads for them (its own
  ``-M`` list: the source, every header however found) and of every
  response file. With no compile command, or one the compiler cannot list,
  it runs every time and is never recorded.

The place is ``validation._checks``'s, then the compiler as it is now (the
path the build was configured with, its ``--version``, the bytes of the real
compiler behind it, and on macOS of the linker), then the variables of the
environment that change what a test checks (``SANITIZER_ENVIRONMENT``). A
compiler changed in place since the build was configured configures it
afresh.

The records follow ``validation._checks``'s rules: the file
``ctest-<preset>.json`` in ``sqlearn-checks/`` of git's common directory, the
newest ``KEPT`` records, written to a temporary file then moved into place,
an unreadable one counting as absent. A run records the labels that passed in
it or were found unchanged, never a label that failed; a label that fails
also takes its identity out of every kept record, so a failure just seen is
not skipped next time. The identity taken before a label runs is the one
recorded, and only when it is unchanged after.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from validation import _checks

TOOLS = ("cmake", "ctest", "ninja")
"""The programs a run needs on ``PATH``."""

SANITIZER_ENVIRONMENT = re.compile(r"^(ASAN|UBSAN|LSAN|TSAN|TYSAN|MSAN|RC|CATCH)_")
"""The variables whose values change what a test checks: part of the place."""

SYSTEM = ("/usr/lib/", "/System/", "/lib/", "/lib64/", "/usr/lib64/")
"""The system's libraries: an OS update changes the place (its platform)."""

STDERR = 2
"""The file descriptor of standard error, where ``due`` sends the build's output."""

STAMP = "sqlearn-compiler.txt"
"""The file, in a build directory, naming the compiler it was configured with."""

Test = dict[str, Any]
"""One test of ``ctest --show-only=json-v1``."""

Entry = dict[str, Any]
"""One compile command of ``compile_commands.json``."""


def _sha(path: Path) -> str:
    """Return the SHA-256 of `path`'s bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _output(argv: Sequence[str], cwd: Path | None = None) -> str | None:
    """Return the standard output of `argv`, or None when it fails or is absent."""
    try:
        done = subprocess.run(
            list(argv), cwd=cwd, check=False, capture_output=True, text=True
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _configured_compiler(build: Path) -> str | None:
    """Return the C++ compiler `build` was configured with, None before."""
    for found in sorted(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake")):
        for line in found.read_text(encoding="utf-8").splitlines():
            matched = re.fullmatch(r'set\(CMAKE_CXX_COMPILER "(.*)"\)', line)
            if matched:
                return matched.group(1)
    return None


def _behind(path: Path) -> Path:
    """Return the real program behind `path`: through xcrun's shims, symlinks."""
    if sys.platform == "darwin" and path.parent == Path("/usr/bin"):
        found = _output(["xcrun", "--find", path.name])
        if found and found.strip():
            path = Path(found.strip())
    return path.resolve()


def compiler(build: Path) -> str:
    """Return the C++ compiler of `build` as it is now, not as CMake found it.

    CMake detects a compiler once, so the same path updated in place (an
    Xcode or Command Line Tools update behind ``/usr/bin/c++``, ``brew upgrade
    llvm`` behind its symlink) leaves its cache as it was; this looks again.

    Parameters
    ----------
    build : Path
        A configured build directory.

    Returns
    -------
    str
        The configured path, its ``--version``, the real compiler's path and
        the SHA-256 of its bytes, and on macOS the linker's; empty before the
        build was configured.
    """
    path = _configured_compiler(build)
    if path is None:
        return ""
    parts = [path, _output([path, "--version"]) or "no --version"]
    programs = [_behind(Path(path))]
    if sys.platform == "darwin":
        linker = _output(["xcrun", "--find", "ld"])
        if linker and linker.strip():
            programs.append(Path(linker.strip()).resolve())
    parts.extend(f"{p}\0{_sha(p) if p.is_file() else 'absent'}" for p in programs)
    return "\n".join(parts)


def _environment() -> str:
    """Return the variables matching ``SANITIZER_ENVIRONMENT``, sorted."""
    return "\n".join(
        f"{name}={value}"
        for name, value in sorted(os.environ.items())
        if SANITIZER_ENVIRONMENT.match(name)
    )


def _place(live: str) -> str:
    """Return the SHA-256 of the checks' place, the compiler `live`, the variables."""
    where = "\0".join((_checks.place(), live, _environment()))
    return hashlib.sha256(where.encode()).hexdigest()


def _cmake(argv: Sequence[str], engine: Path, out: int | None = None) -> int:
    """Run a CMake command in `engine`, its output to `out`; return its exit code.

    `out` is a file descriptor, None for this process's standard output.
    """
    return subprocess.run(list(argv), cwd=engine, check=False, stdout=out).returncode


def _build(
    preset: str, engine: Path, build: Path, out: int | None = None
) -> tuple[int, str]:
    """Configure and build `preset`; return the first failing code and the compiler.

    A build directory configured with another compiler than today's (its
    stamp, ``STAMP``, differs) is configured afresh. CMake's and Ninja's
    output goes to the file descriptor `out`, None for standard output.
    """
    new = not (build / "CMakeCache.txt").exists()
    code = _cmake(["cmake", "--preset", preset], engine, out)
    if code != 0:
        return code, ""
    live = compiler(build)
    stamp = build / STAMP
    digest = hashlib.sha256(live.encode()).hexdigest()
    try:
        before = stamp.read_text(encoding="utf-8")
    except OSError:
        before = None
    if not new and before != digest:
        _say(
            f"C++ tests: the compiler changed since {preset} was configured: "
            "configuring afresh"
        )
        code = _cmake(["cmake", "--fresh", "--preset", preset], engine, out)
        if code != 0:
            return code, ""
        live = compiler(build)
        digest = hashlib.sha256(live.encode()).hexdigest()
    stamp.write_text(digest, encoding="utf-8")
    code = _cmake(["cmake", "--build", "--preset", preset, "--parallel"], engine, out)
    return code, live


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


def _property(test: Test, name: str) -> list[str]:
    """Return the values of `test`'s property `name`, empty without it."""
    for prop in test.get("properties", []):
        if prop.get("name") == name:
            value = prop.get("value", [])
            return [str(v) for v in (value if isinstance(value, list) else [value])]
    return []


def _targets(command: Sequence[str]) -> list[str]:
    """Return the targets a ``--target`` of `command` names."""
    return [
        command[i + 1]
        for i, arg in enumerate(command[:-1])
        if arg in {"--target", "-t"}
    ]


def _arguments(entry: Entry) -> list[str]:
    """Return a compile command's argv, from ``arguments`` or ``command``."""
    if "arguments" in entry:
        return [str(a) for a in entry["arguments"]]
    return shlex.split(str(entry.get("command", "")))


_DROP = frozenset({"-c", "-MD", "-MMD"})
"""The flags of a compile command left out of its ``-M`` listing."""

_DROP_WITH_VALUE = frozenset({"-o", "-MF", "-MT", "-MQ"})
"""The flags left out with the value after them."""


def _read_by_compiler(entry: Entry) -> list[Path] | None:
    """Return every file the compiler reads for `entry`, by its own ``-M``.

    The source and each header, however found (its own directory, ``-I``,
    ``-isystem``, ``-iquote``, ``-include``); None when it cannot list them.
    """
    argv = []
    skip = False
    for arg in _arguments(entry):
        if skip:
            skip = False
        elif arg in _DROP_WITH_VALUE:
            skip = True
        elif arg not in _DROP:
            argv.append(arg)
    here = Path(str(entry.get("directory", ".")))
    listing = _output([*argv, "-M"], cwd=here)
    if listing is None:
        return None
    _, _, files = listing.replace("\\\n", " ").partition(": ")
    names = [n.replace("\\ ", " ") for n in re.split(r"(?<!\\)\s+", files) if n]
    return [here / n for n in names]


def _target_parts(target: str, entries: list[Entry]) -> list[str]:
    """Return what builds `target`: its compile commands and what they read."""
    parts = []
    marker = f"/CMakeFiles/{target}.dir/"
    for entry in entries:
        if marker not in str(entry.get("output", "")):
            continue
        argv = _arguments(entry)
        parts.append(shlex.join(argv))
        read = _read_by_compiler(entry)
        if read is None:
            parts.append(f"unknown\0{os.urandom(16).hex()}")
            continue
        here = Path(str(entry.get("directory", ".")))
        response = [here / a[1:] for a in argv if a.startswith("@")]
        parts.extend(f"{p}\0{_file_part(p)}" for p in sorted({*read, *response}))
    if not parts:
        # Nothing says what builds it (no compile_commands.json, or a target
        # of no source): an identity of its own each time, so it always runs.
        parts.append(f"unknown\0{os.urandom(16).hex()}")
    return parts


def _file_part(path: Path) -> str:
    """Return the SHA-256 of `path`'s bytes, or ``absent``."""
    return _sha(path) if path.is_file() else "absent"


def _macho(binary: Path, *, library: bool) -> tuple[list[str], list[str]]:
    """Return the libraries a Mach-O file names and its run-path directories.

    A `library`'s own install name, which ``otool -L`` lists first, is left out.
    """
    names = []
    listing = (_output(["otool", "-L", str(binary)]) or "").splitlines()
    for line in listing[2 if library else 1 :]:
        name = line.strip().split(" (")[0]
        if name:
            names.append(name)
    rpaths = []
    lines = (_output(["otool", "-l", str(binary)]) or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            for after in lines[i + 1 : i + 4]:
                found = re.match(r"\s*path (.*) \(offset \d+\)", after)
                if found:
                    rpaths.append(found.group(1))
                    break
    return names, rpaths


def _placed(text: str, loader: Path, program: Path) -> str:
    """Return `text` with ``@executable_path`` and ``@loader_path`` replaced."""
    return text.replace("@executable_path", str(program.parent)).replace(
        "@loader_path", str(loader.parent)
    )


def _resolve(name: str, loader: Path, program: Path, rpaths: list[str]) -> Path | None:
    """Return the file the dynamic loader would load for `name`, None if none.

    `rpaths` are the run-path directories dyld searches for an ``@rpath/``
    name of `loader`, already placed: `loader`'s own, then those of each
    image that loaded it, back to the program's.
    """
    if name.startswith("@rpath/"):
        rest = name.removeprefix("@rpath/")
        for rpath in rpaths:
            candidate = Path(rpath) / rest
            if candidate.is_file():
                return candidate.resolve()
        return None
    candidate = Path(_placed(name, loader, program))
    return candidate.resolve() if candidate.is_file() else None


def _libraries(program: Path) -> list[str]:
    """Return each non-system shared library `program` loads, with its digest.

    On macOS through ``otool``: each file's names, an ``@rpath/`` one
    resolved as dyld does, through the run paths of the whole chain that
    loaded it (its own, then each loader's, back to the program's; an
    ``@loader_path`` in a run path is the directory of the file declaring
    it). Elsewhere through ``ldd`` when present. A library that cannot be
    found is named as such.
    """
    found: list[str] = []
    if sys.platform == "darwin" and shutil.which("otool"):
        start = program.resolve()
        seen = {start}
        queue: list[tuple[Path, list[str]]] = [(start, [])]
        while queue:
            binary, inherited = queue.pop()
            names, own = _macho(binary, library=binary != start)
            rpaths = [_placed(r, binary, start) for r in own] + inherited
            for name in names:
                if name.startswith(SYSTEM):
                    continue
                path = _resolve(name, binary, start, rpaths)
                if path is None:
                    found.append(f"{name}\0unresolved")
                elif path not in seen:
                    seen.add(path)
                    queue.append((path, rpaths))
                    found.append(f"{path}\0{_sha(path)}")
    elif shutil.which("ldd"):
        for line in (_output(["ldd", str(program)]) or "").splitlines():
            name, arrow, rest = line.strip().partition("=> ")
            target = rest.split(" (")[0].strip() if arrow else ""
            if not arrow or target.startswith(SYSTEM):
                continue
            path = Path(target)
            found.append(
                f"{path}\0{_sha(path)}" if path.is_file() else f"{name}\0unresolved"
            )
    return sorted(found)


def _compile_entries(build: Path) -> list[Entry]:
    """Return `build`'s compile commands, none when it has no such file."""
    path = build / "compile_commands.json"
    if not path.exists():
        return []
    entries: list[Entry] = json.loads(path.read_text(encoding="utf-8"))
    return entries


def _identities(
    units: dict[str, list[Test]], build: Path, place: str
) -> dict[str, str]:
    """Return each label of `units` with the SHA-256 of what its tests run."""
    entries = _compile_entries(build)
    inside = build.resolve()
    found = {}
    for label, tests in units.items():
        sha = hashlib.sha256(f"{place}\0{label}\0".encode())
        for test in sorted(tests, key=lambda t: str(t.get("name"))):
            entry = {k: test.get(k) for k in ("name", "command", "properties")}
            sha.update(json.dumps(entry, sort_keys=True).encode() + b"\0")
            command = [str(a) for a in test.get("command") or []]
            for arg in command:
                path = Path(arg)
                if not (path.is_absolute() and path.is_file()):
                    continue
                sha.update(f"{arg}\0{_sha(path)}\0".encode())
                if path.resolve().is_relative_to(inside):
                    for library in _libraries(path):
                        sha.update(library.encode() + b"\0")
            for data in _property(test, "REQUIRED_FILES"):
                sha.update(f"{data}\0{_file_part(Path(data))}\0".encode())
            for target in _targets(command):
                for part in _target_parts(target, entries):
                    sha.update(part.encode() + b"\0")
        found[label] = sha.hexdigest()
    return found


def _units(tests: list[Test]) -> tuple[dict[str, list[Test]], list[str]]:
    """Return the tests by label, and the names of those with no label."""
    units: dict[str, list[Test]] = {}
    loose = []
    for test in tests:
        labels = _property(test, "LABELS")
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


def _forget(directory: Path, key: str, failed: dict[str, str]) -> None:
    """Take each failed label's identity out of every kept record of `key`."""
    records = _checks.load(directory, key)
    kept = [
        _checks.Record(
            digest=r["digest"],
            config=r["config"],
            files={k: v for k, v in r["files"].items() if failed.get(k) != v},
        )
        for r in records
    ]
    if kept != records:
        _checks.write(directory, key, kept)


def _prepared(
    preset: str, root: Path, out: int | None = None
) -> tuple[int, Path, dict[str, list[Test]], str]:
    """Build `preset` and list its tests by label, saying what stops a run.

    The build's output goes to the file descriptor `out`, None for standard
    output.

    Returns the first failing code (the build's, or 1 for a missing tool, a
    test with no TIMEOUT or a test no label selects), the build directory,
    the tests by label and the place; the last two are empty after a
    failure.
    """
    engine = root / "engine"
    build = engine / "build" / preset
    missing = [t for t in TOOLS if shutil.which(t) is None]
    if missing:
        _say(
            f"C++ tests: {', '.join(missing)} not on PATH.\n"
            "Fix: run `just doctor`, then install what it names"
        )
        return 1, build, {}, ""
    code, live = _build(preset, engine, build, out)
    if code != 0:
        _say(f"C++ tests: the {preset} build failed; no test ran, none recorded")
        return code, build, {}, ""
    units, loose = _units(_tests(build))
    if loose:
        _say(
            f"C++ tests: {', '.join(sorted(loose))} carry no label, so no "
            "group would run them.\n"
            "Fix: add them with sq_add_group, or set_tests_properties(<test> "
            "PROPERTIES LABELS <group>)"
        )
        return 1, build, {}, ""
    endless = sorted(
        str(t.get("name"))
        for tests in units.values()
        for t in tests
        if not _property(t, "TIMEOUT")
    )
    if endless:
        _say(
            f"C++ tests: {', '.join(endless)} carry no TIMEOUT, so a hang "
            "would stall the run for good.\n"
            "Fix: register them with sq_test_timeout(<test>) "
            "(engine/cmake/groups.cmake)"
        )
        return 1, build, {}, ""
    return 0, build, units, _place(live)


def due(preset: str, root: Path) -> dict[str, list[str]]:
    """Return each label of `preset` with why ``run`` would run it; runs none.

    It builds the preset, since a label's identity holds its program's bytes,
    and writes no record. What the build and its checks print goes to
    standard error, so standard output holds only the caller's answer.

    Parameters
    ----------
    preset : str
        A preset of ``engine/CMakePresets.json``.
    root : Path
        The repository's working tree.

    Returns
    -------
    dict of str to list of str
        Each label with its reasons, empty when unchanged since a passed
        run. When the build or its tests' listing fails, one entry,
        ``build``, says so: ``run`` would fail there.
    """
    root = root.resolve()
    with contextlib.redirect_stdout(sys.stderr):
        code, build, units, place = _prepared(preset, root, STDERR)
    if code != 0:
        return {"build": [f"the {preset} build or its tests' listing failed"]}
    return _checks.reasons(
        _identities(units, build, place),
        _checks.record_dir(root),
        f"ctest-{preset}",
        "its test program, data or command changed",
    )


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
        failing one included), or 1 for a missing tool, a test with no
        TIMEOUT or a test no label selects; else 0.
    """
    root = root.resolve()
    code, build, units, place = _prepared(preset, root)
    if code != 0:
        return code
    key = f"ctest-{preset}"
    directory = _checks.record_dir(root)
    done = _checks.passed(directory, key)
    before = _identities(units, build, place)
    good: dict[str, str] = {}
    failed: dict[str, str] = {}
    ran = []
    first = 0
    for label in sorted(units):
        if not everything and (label, before[label]) in done:
            _say(f"{label}: unchanged since a passed run")
            good[label] = before[label]
            continue
        code = _run_label(build, label)
        if code != 0:
            first = first or code
            failed[label] = before[label]
            continue
        ran.append(label)
    if failed:
        _forget(directory, key, failed)
    after = _identities(units, build, place) if ran else {}
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
            _checks.Record(digest=whole, config=place, files=good),
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
