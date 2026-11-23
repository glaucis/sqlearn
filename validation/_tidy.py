"""clang-tidy and include-what-you-use over sqlearn's own C++, from one
compile database: the ``tidy`` task's first two steps (``validation._checks``).

Our sources compile in three builds, so ``database`` takes each one's
command from the build that compiles it:

- the groups and their tests from the ``llvm-dev`` preset, Homebrew LLVM's,
  the clang these tools are built on;
- the benchmarks from the ``release`` preset, the one flavour of the two
  that build them (``engine/bench/CMakeLists.txt``);
- the bindings and the extension from the wheel's build,
  ``build/<cache tag>``, which ``uv run`` keeps current: they need DuckDB's,
  nanobind's and Python's headers, which only that build has. Its nanobind
  include directory was in uv's build environment, gone once the build
  ended, so it is replaced by this environment's nanobind, the same pinned
  release (``pyproject.toml``'s ``lint`` group and build requirements).

The database, ``engine/build/tidy/compile_commands.json``, holds our
sources alone: never a submodule's, never the must-not-compile cases (they
are meant not to compile) nor the must-not-pass-tidy ones (meant to fail
it). A source no build compiles is refused with a ``Fix:`` line, so none is
skipped unseen.
"""

import argparse
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

LLVM = Path("/opt/homebrew/opt/llvm/bin")
"""Homebrew LLVM's tools: the formula is keg-only, so they are off ``PATH``."""

SOURCES = (
    "engine/src/*.cpp",
    "engine/tests/*.cpp",
    "engine/bench/*.cpp",
    "engine/extension/src/*.cpp",
    ":(exclude)engine/tests/must_not_compile",
    ":(exclude)engine/tests/must_not_pass_tidy",
)
"""Our C++ sources, as git pathspecs; a header is checked through them."""

WHEEL = ("engine/src/bindings/", "engine/extension/")
"""The sources only the wheel's build compiles."""

BENCH = ("engine/bench/",)
"""The sources only the optimised presets compile."""


def sources(root: Path) -> list[str]:
    """Return our C++ sources under `root`, tracked or not ignored, sorted.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    list of str
        Their paths relative to `root`.
    """
    out = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *SOURCES,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return sorted(
        {n.decode() for n in out.split(b"\0") if n and (root / n.decode()).is_file()}
    )


def _build(name: str) -> str:
    """Return which build compiles the source `name`: wheel, release or llvm-dev."""
    if name.startswith(WHEEL):
        return "wheel"
    if name.startswith(BENCH):
        return "release"
    return "llvm-dev"


def _configure(root: Path, preset: str) -> None:
    """Configure `preset` (its compile database comes with it), or exit with
    CMake's own message."""
    done = subprocess.run(
        ["cmake", "--preset", preset],
        cwd=root / "engine",
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        print(done.stdout + done.stderr, file=sys.stderr)  # noqa: T201
        raise SystemExit(done.returncode)


def _sdk() -> list[str]:
    """Return ``-isysroot`` and macOS's SDK, or nothing off macOS."""
    if shutil.which("xcrun") is None:
        return []
    sdk = subprocess.run(
        ["xcrun", "--show-sdk-path"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return ["-isysroot", sdk]


def _nanobind_include() -> str:
    """Return this environment's nanobind include directory."""
    import nanobind

    return str(nanobind.include_dir())


def _fixed(arguments: list[str], sdk: list[str]) -> list[str]:
    """Return a compile command the tools can run outside its build.

    A missing nanobind include directory (uv's build environment, gone) is
    this environment's; a ``@<object>.modmap`` (CMake's C++ module map,
    empty, as no source of ours is a module, and written only when the
    object builds) is dropped; the SDK is named when the command names none.
    """
    out: list[str] = []
    it = iter(arguments)
    for arg in it:
        if arg.startswith("@") and arg.endswith(".modmap"):
            continue
        if arg == "-isystem":
            path = next(it)
            if path.endswith("/nanobind/include") and not Path(path).is_dir():
                path = _nanobind_include()
            out += [arg, path]
            continue
        out.append(arg)
    if sdk and "-isysroot" not in out:
        out[1:1] = sdk
    return out


def _commands(database: Path) -> dict[str, dict[str, Any]]:
    """Return a build's compile commands by source path, absolute."""
    entries = json.loads(database.read_text(encoding="utf-8"))
    return {str(Path(e["directory"], e["file"]).resolve()): e for e in entries}


def database(root: Path) -> Path:
    """Write the compile database of our sources, and return its directory.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    Path
        ``engine/build/tidy``, holding ``compile_commands.json``.
    """
    names = sources(root)
    builds = {_build(n) for n in names}
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for preset in sorted(builds - {"wheel"}):
        _configure(root, preset)
        found[preset] = _commands(
            root / "engine" / "build" / preset / "compile_commands.json"
        )
    if "wheel" in builds:
        wheel = root / "build" / sys.implementation.cache_tag / "compile_commands.json"
        if not wheel.exists():
            print(  # noqa: T201
                f"The wheel's build, {wheel.parent}, has no compile commands.\n"
                "Fix: uv sync --locked",
                file=sys.stderr,
            )
            raise SystemExit(1)
        found["wheel"] = _commands(wheel)
    sdk = _sdk()
    entries = []
    missing = []
    for name in names:
        path = str((root / name).resolve())
        entry = found[_build(name)].get(path)
        if entry is None:
            missing.append(f"{name} (the {_build(name)} build)")
            continue
        command: list[str] = entry.get("arguments") or shlex.split(entry["command"])
        entries.append(
            {
                "directory": entry["directory"],
                "file": path,
                "arguments": _fixed(command, sdk),
            }
        )
    if missing:
        print(  # noqa: T201
            "No build compiles these sources, so clang-tidy cannot check them:\n  "
            + "\n  ".join(missing)
            + "\nFix: add each to its group's SOURCES or TESTS (sq_add_group,"
            " engine/CMakeLists.txt), then run this again",
            file=sys.stderr,
        )
        raise SystemExit(1)
    out = root / "engine" / "build" / "tidy"
    out.mkdir(parents=True, exist_ok=True)
    (out / "compile_commands.json").write_text(json.dumps(entries, indent=1) + "\n")
    return out


def tidy(root: Path) -> int:
    """Run clang-tidy, with the static analyser, on each of our sources.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    int
        0 when no source has a finding (every finding is an error,
        ``engine/.clang-tidy``), else run-clang-tidy's code.
    """
    built = database(root)
    files = [re.escape(str((root / n).resolve())) + "$" for n in sources(root)]
    return subprocess.run(
        [
            sys.executable,
            str(LLVM / "run-clang-tidy"),
            "-clang-tidy-binary",
            str(LLVM / "clang-tidy"),
            "-p",
            str(built),
            "-quiet",
            "-j",
            str(os.cpu_count() or 1),
            *files,
        ],
        cwd=root / "engine",
        check=False,
    ).returncode


def iwyu(root: Path) -> int:
    """Run include-what-you-use on each of our sources and our headers.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    int
        0 when every file includes what it uses and nothing more, else
        iwyu_tool's code.
    """
    built = database(root)
    tool = shutil.which("iwyu_tool.py")
    if tool is None:
        print(  # noqa: T201
            "include-what-you-use is missing.\nFix: brew install include-what-you-use"
        )
        return 1
    # The mappings include-what-you-use ships beside it: Python's C API.
    shipped = Path(tool).resolve().parent.parent / "share" / "include-what-you-use"
    mappings = [root / "engine" / "iwyu.imp", shipped / "python3.8.imp"]
    return subprocess.run(
        [
            sys.executable,
            tool,
            "-p",
            str(built),
            "-j",
            str(os.cpu_count() or 1),
            *[str((root / n).resolve()) for n in sources(root)],
            "--",
            "-Xiwyu",
            "--error",
            # DuckDB's classes are declared by DuckDB, never by us.
            "-Xiwyu",
            "--no_fwd_decls",
            *[a for m in mappings for a in ("-Xiwyu", f"--mapping_file={m}")],
            # A header with no source of its own (core/expects.hpp) is
            # checked through the sources that include it.
            "-Xiwyu",
            f"--check_also={root.resolve() / 'engine' / 'src'}/*.hpp",
        ],
        cwd=root / "engine",
        check=False,
    ).returncode


def cli(argv: Sequence[str]) -> int:
    """Parse ``tidy`` or ``iwyu`` and run it on the working tree.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name.

    Returns
    -------
    int
        The tool's exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._tidy")
    parser.add_argument("tool", choices=("tidy", "iwyu"), help="the tool to run")
    args = parser.parse_args(argv)
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    root = Path(top)
    return tidy(root) if args.tool == "tidy" else iwyu(root)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
