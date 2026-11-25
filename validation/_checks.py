"""Each check as a task that runs only when its inputs changed.

A task names its inputs and its configuration as git pathspecs, the tools
from outside uv.lock whose versions are configuration too, and the steps
that check them. A whole task (``types``, ``test``) runs when the
digest of its inputs and configuration has no passed record; a per-file
task (``format``, ``lint``) gives each step the files whose own digest has
no passed record under today's configuration, and every file once the
configuration changed. ``everything`` runs it all regardless, and records.
Every step runs, a failing one included, so one tool's failure hides no
other's findings. A step that keeps records of its own (the C++ groups,
``validation._ctest``) runs even when its task is unchanged, and is told
when to run everything.

The digest covers the tracked files and the untracked ones git does not
ignore; a tracked file deleted from the working tree is absent from it, so
its deletion is a change. The checks' own outputs are never inputs. The
place a task runs in is part of its configuration: another Python, platform
or machine reruns every task. The
digest is taken before the run and only that one is recorded, and only
when nothing changed while the task ran, so a file edited meanwhile is
checked again.

The records live in the git common directory, ``sqlearn-checks/``, one
file per task, so every worktree shares them; two worktrees recording at
once can lose a record, which costs a rerun, never a skip; a record file
that cannot be read or parsed counts as absent.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

KEPT = 20
"""How many records of each task are kept, the newest."""

OUTPUTS = (
    ":(exclude)validation/tests.json",
    ":(exclude)validation/environment.json",
    ":(exclude,glob)validation/**/*.results.json",
)
"""The checks' own outputs, excluded from every task's inputs."""


@dataclass(frozen=True)
class Step:
    """One command of a task, and the inputs it takes.

    Attributes
    ----------
    command : tuple of str
        The argv. A per-file task appends the changed files it takes.
    files : tuple of str
        The pathspecs, within the task's inputs, this step takes; empty for
        every input.
    ok : tuple of int
        The exit codes that are a pass: pytest's 5, no test collected, is
        one for a pass that selects none.
    everything : tuple of str
        The arguments appended when the task runs all through
        (``everything``): a step that keeps records of its own, as the C++
        groups do, then runs all of its own too.
    always : bool
        Whether it runs when the task is unchanged since a passed run, the
        other steps skipped: it keeps records of its own and decides what to
        run, so what its records name and no input of the task does (the
        compiler, for the C++ groups) still reruns it.
    """

    command: tuple[str, ...]
    files: tuple[str, ...] = ()
    ok: tuple[int, ...] = (0,)
    everything: tuple[str, ...] = ()
    always: bool = False


@dataclass(frozen=True)
class Task:
    """One check: what it reads, what reruns it whole, and how it runs.

    Attributes
    ----------
    name : str
        Its name, ``just <name>``.
    inputs : tuple of str
        The pathspecs of the files it checks or reads.
    config : tuple of str
        The pathspecs of the settings whose change reruns all of it.
    steps : tuple of Step
        Its commands, run in order, each whatever the others' exit.
    per_file : bool
        Whether each file's result depends only on that file and the
        settings, so only the changed files are checked.
    layout : tuple of str
        The pathspecs of files whose names, not bytes, are configuration: a
        tool that classifies by which files exist (ruff's import sorting)
        reruns on every file when one appears or goes.
    tools : tuple of tuple of str
        The argv of each command that names a tool from outside uv.lock
        (Homebrew's clang-tidy): its output is configuration, so an upgraded
        tool reruns all of the task. A tool that is not installed counts as
        absent, and the task's own step then fails.
    """

    name: str
    inputs: tuple[str, ...]
    config: tuple[str, ...]
    steps: tuple[Step, ...]
    per_file: bool
    layout: tuple[str, ...] = ()
    tools: tuple[tuple[str, ...], ...] = ()


class Record(TypedDict):
    """One passed run of one task: the digests of what it checked."""

    digest: str
    config: str
    files: dict[str, str]


SETTINGS = (
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "justfile",
    # The tools' own configuration files, at the root or deeper: one added
    # governs every file it reaches, so it reruns all of each task. An absent
    # one hashes as absent.
    ":(glob)**/pyproject.toml",
    ":(glob)**/ruff.toml",
    ":(glob)**/.ruff.toml",
    ":(glob)**/typos.toml",
    ":(glob)**/_typos.toml",
    ":(glob)**/.typos.toml",
    ":(glob)**/rumdl.toml",
    ":(glob)**/.rumdl.toml",
    ":(glob)**/mypy.ini",
    ":(glob)**/.mypy.ini",
    ":(glob)**/ty.toml",
)
"""The settings every task reads: the tools', the locked versions, the recipes."""

PYTHON = ("*.py", "*.pyi")
"""Every Python file, at any depth."""

MARKDOWN = ("*.md",)
"""Every Markdown file, at any depth."""

LLVM = "/opt/homebrew/opt/llvm/bin"
"""Homebrew LLVM's tools: the formula is keg-only, so they are off ``PATH``."""

CXX = ("*.cpp", "*.hpp")
"""Every C++ file of ours: git lists no file inside a submodule."""

CMAKE = (":(glob)**/CMakeLists.txt", ":(glob)**/*.cmake")
"""Every CMake file of ours, at any depth."""

ENGINE_SOURCES = (
    "engine/src",
    "engine/tests",
    "engine/bench",
    "engine/extension",
)
"""sqlearn's own C++: the groups, their tests, the benchmarks, the extension."""

ENGINE_BUILD = (
    "engine/duckdb-python",
    "engine/src",
    "engine/extension",
    "engine/CMakeLists.txt",
    "engine/cmake",
)
"""What the built module comes from: pyproject's ``tool.uv.cache-keys`` under
``engine/``, on which uv rebuilds it, and duckdb-python's gitlink, which pins
DuckDB's. A task whose result depends on the module or on DuckDB (the
doctests run on it, the type checkers read its stubs) has it as
configuration, so a DuckDB bump or a C++ edit reruns all of it."""

TIDY_INPUTS = (
    *ENGINE_SOURCES,
    "engine/.clang-tidy",
    "engine/src/raw/.clang-tidy",
    "engine/iwyu.imp",
    # What the tools check and how: the sources and their exclusions, the
    # build each comes from, IWYU's flags and mapping files.
    "validation/_tidy.py",
    "engine/cmake",
    "engine/CMakeLists.txt",
    "engine/CMakePresets.json",
    # Their headers are what our includes resolve to: a bump reruns it.
    "engine/duckdb-python",
    "engine/third_party",
)
"""What clang-tidy, include-what-you-use and the headers-alone build read."""

TEST_INPUTS = (
    "src",
    "tests",
    "validation",
    "devdata",
    # Files the tests read as data.
    "docs/architecture/engine-inventory.md",
    # The engine's build files and sources, and the submodules' commits.
    "engine",
    "docs/conf.py",
    ".githooks",
    "commitlint.config.mjs",
    ":(glob)**/conftest.py",
)
"""What the tests import or read, so a change to any of it reruns them all."""

SQL_INPUTS = (
    # The extension: its sources, its config and its .test files.
    "engine/extension",
    # Our C++ it links (core::describe), and the build of the runner.
    "engine/src",
    "engine/sqllogic",
    "engine/cmake",
    "engine/CMakeLists.txt",
    "engine/CMakePresets.json",
    # DuckDB, through duckdb-python's gitlink, which pins its own.
    "engine/duckdb-python",
    "validation/_ctest.py",
)
"""What DuckDB's unittest with the sqlearn extension, and its SQL tests, come from."""

_PYTEST_PASSES = (
    ("-n", "auto", "-m", "not slow and not serial", "--ignore=tests/githooks"),
    ("-p", "no:xdist", "-m", "serial and not slow", "--ignore=tests/githooks"),
    ("-p", "no:xdist", "-m", "slow", "--ignore=tests/githooks"),
    ("-n", "auto", "-m", "", "tests/githooks"),
)
"""The fast tests in parallel, the serial ones alone, the slow tier, the hooks."""


def _table() -> dict[str, Task]:
    """Return the checks by name; the tools are those of the environment.

    ``validate`` is not among them: its runners keep records of their own
    (``python -m validation``).
    """
    tasks = (
        Task(
            name="format",
            inputs=(*PYTHON, *MARKDOWN, *CXX, *CMAKE),
            config=(
                *SETTINGS,
                # clang-format reads the nearest one, at any depth.
                ":(glob)**/.clang-format",
                ".gersemirc",
                # gersemi lays out calls by the signatures defined here
                # (.gersemirc's definitions).
                "engine/cmake",
            ),
            steps=(
                Step(("ruff", "format", "--check", "--force-exclude"), PYTHON),
                # rumdl applies its configured excludes to named files itself.
                Step(("rumdl", "fmt", "--check"), MARKDOWN),
                Step((f"{LLVM}/clang-format", "--dry-run", "-Werror"), CXX),
                Step(("gersemi", "--check"), CMAKE),
            ),
            per_file=True,
            tools=((f"{LLVM}/clang-format", "--version"),),
        ),
        Task(
            name="lint",
            # typos reads every file; ruff and rumdl their own kinds.
            inputs=(".",),
            config=SETTINGS,
            steps=(
                Step(("ruff", "check", "--force-exclude"), PYTHON),
                Step(("typos", "--force-exclude")),
                Step(("rumdl", "check"), MARKDOWN),
            ),
            per_file=True,
            # ruff's import sorting classifies by which modules exist. The
            # layout is the whole task's configuration, so a Python file
            # added or removed reruns every step on every file, the Markdown
            # and the spelling included.
            layout=PYTHON,
        ),
        Task(
            name="docstrings",
            inputs=("src/*.py",),
            config=(*SETTINGS, *ENGINE_BUILD),
            steps=(
                Step(("numpydoc", "lint")),
                # pydoclint through its filter, which drops DOC111.
                Step(("just", "check-docstring-args")),
            ),
            per_file=True,
        ),
        Task(
            name="types",
            inputs=PYTHON,
            # ty and mypy read the module's stubs (_duckdb-stubs).
            config=(*SETTINGS, *ENGINE_BUILD),
            steps=(Step(("ty", "check")), Step(("mypy",))),
            per_file=False,
        ),
        Task(
            name="test",
            inputs=TEST_INPUTS,
            config=SETTINGS,
            steps=(
                # Each C++ group whose test program changed since it passed
                # (validation/_ctest.py), on the sanitized dev build.
                Step(
                    ("just", "test-engine-changed", "dev"),
                    everything=("--all",),
                    always=True,
                ),
                *(
                    Step(
                        ("pytest", "-p", "validation._tests_report", *p),
                        # Only the serial pass may find nothing: a marker or a
                        # testpaths broken elsewhere must fail, not pass.
                        ok=(0, 5) if "serial and not slow" in p else (0,),
                    )
                    for p in _PYTEST_PASSES
                ),
            ),
            per_file=False,
        ),
        Task(
            name="sql",
            inputs=SQL_INPUTS,
            config=SETTINGS,
            steps=(
                # The extension's sqllogictest files, on DuckDB's unittest
                # (the sqllogic preset, validation/_ctest.py, whose records
                # then decide). Not `always`: it runs when its inputs or the
                # compiler changed, so a tree that never touches them never
                # builds DuckDB's tree for it.
                Step(("just", "test-sql"), everything=("--all",)),
            ),
            per_file=False,
            tools=(
                # The compiler behind the build (an Xcode or Command Line
                # Tools update), and the SDK it compiles against.
                ("c++", "--version"),
                ("xcrun", "--show-sdk-version"),
            ),
        ),
        Task(
            name="tidy",
            inputs=TIDY_INPUTS,
            config=SETTINGS,
            steps=(
                # clang-tidy, with the static analyser, then
                # include-what-you-use, over one compile database of our
                # sources (validation/_tidy.py); then every header alone.
                Step(("just", "tidy-engine")),
                Step(("just", "iwyu-engine")),
                Step(("just", "headers-alone")),
            ),
            per_file=False,
            tools=(
                (f"{LLVM}/clang-tidy", "--version"),
                ("include-what-you-use", "--version"),
                # The SDK whose headers the wheel's compile commands read.
                ("xcrun", "--show-sdk-version"),
            ),
        ),
        Task(
            name="docs",
            inputs=("docs", "src", "examples"),
            # The doctests run on the built module.
            config=(*SETTINGS, *ENGINE_BUILD),
            steps=(Step(("just", "build-docs")),),
            per_file=False,
        ),
    )
    return {t.name: t for t in tasks}


TASKS: dict[str, Task] = _table()
"""The checks by name, ``just <name>`` each."""


def _listed(pathspecs: Sequence[str], root: Path) -> list[str]:
    """Return the present files under `pathspecs`, tracked or not ignored, sorted."""
    if not pathspecs:
        return []
    out = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *pathspecs,
            *OUTPUTS,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    names = {n.decode() for n in out.split(b"\0") if n}
    return sorted(n for n in names if (root / n).is_file())


def _gitlinks(pathspecs: Sequence[str], root: Path) -> dict[str, str]:
    """Return each submodule under `pathspecs` with the commit the tree pins.

    A gitlink (mode 160000) is a directory in the working tree, so
    ``_listed`` drops it; its commit is what a bump changes.
    """
    if not pathspecs:
        return {}
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z", "--", *pathspecs],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    links = {}
    for entry in out.split("\0"):
        info, _, name = entry.partition("\t")
        mode, commit, *_ = info.split(" ") if info else ("", "", "")
        if mode == "160000":
            links[name] = commit
    return links


def _mode(path: Path) -> bytes:
    """Return ``x`` for an executable file, ``-`` for any other.

    The hook tests assert the executable bit, so it is part of a file.
    """
    return b"x" if path.stat().st_mode & 0o111 else b"-"


def _hashes(names: Sequence[str], root: Path) -> dict[str, str]:
    """Return each file of `names` with the SHA-256 of its mode and content."""
    return {
        n: hashlib.sha256(_mode(root / n) + (root / n).read_bytes()).hexdigest()
        for n in names
    }


def _place() -> bytes:
    """Return what names the place a task runs in: Python, platform, machine."""
    return "\0".join((sys.version, platform.platform(), platform.machine())).encode()


def _tool_versions(task: Task) -> bytes:
    """Return what each of `task`'s tools prints, its argv first; absent when
    it cannot run."""
    out = b""
    for argv in task.tools:
        try:
            done = subprocess.run(list(argv), capture_output=True, check=False)
            said = done.stdout + done.stderr
        except OSError:
            said = b"absent"
        out += "\0".join(argv).encode() + b"\0" + said + b"\0"
    return out


def _combined(
    names: Sequence[str], root: Path, links: dict[str, str] | None = None
) -> str:
    """Return the SHA-256 of the place, then each file's path, mode and bytes.

    The place leads, then, sorted, each file's path, a NUL, its mode, its
    bytes, a NUL; then, sorted, each submodule's path, a NUL, its commit, a
    NUL.
    """
    sha = hashlib.sha256(_place() + b"\0")
    for name in sorted(names):
        path = root / name
        sha.update(name.encode() + b"\0" + _mode(path) + path.read_bytes() + b"\0")
    for name, commit in sorted((links or {}).items()):
        sha.update(name.encode() + b"\0" + commit.encode() + b"\0")
    return sha.hexdigest()


def digest(task: Task, root: Path) -> str:
    """Return the SHA-256 of `task`'s inputs and configuration under `root`.

    Parameters
    ----------
    task : Task
        The task whose files are hashed.
    root : Path
        The repository's working tree.

    Returns
    -------
    str
        The hex digest of the place it runs in, every file under its inputs
        and configuration, the commit each submodule there pins, and its
        tools' versions.
    """
    names = sorted({*_listed(task.inputs, root), *_listed(task.config, root)})
    links = {
        **_gitlinks(task.inputs, root),
        **_gitlinks(task.config, root),
    }
    combined = _combined(names, root, links)
    if not task.tools:
        return combined
    tools = b"\0tools\0" + _tool_versions(task)
    return hashlib.sha256(combined.encode() + tools).hexdigest()


def _config(task: Task, root: Path) -> str:
    """Return the SHA-256 of the place, `task`'s configuration and its layout.

    The layout is the sorted names of the files under ``task.layout``, never
    their bytes: a new or removed file changes it. The commit each submodule
    under the configuration pins, and the tools' versions, count too.
    """
    layout = "\0".join(_listed(task.layout, root)).encode()
    links = _gitlinks(task.config, root)
    sha = hashlib.sha256(_combined(_listed(task.config, root), root, links).encode())
    sha.update(b"\0layout\0" + layout)
    if task.tools:
        sha.update(b"\0tools\0" + _tool_versions(task))
    return sha.hexdigest()


def record_dir(root: Path) -> Path:
    """Return the records' directory: ``sqlearn-checks`` in git's common one.

    Parameters
    ----------
    root : Path
        The repository's working tree.

    Returns
    -------
    Path
        The directory, which may not exist yet.
    """
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (root / common).resolve() / "sqlearn-checks"


def _is_record(value: object) -> bool:
    """Return whether `value` has a record's shape, as JSON gives it."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("digest"), str)
        and isinstance(value.get("config"), str)
        and isinstance(value.get("files"), dict)
        and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value["files"].items()
        )
    )


def load(directory: Path, task: str) -> list[Record]:
    """Return `task`'s records in `directory`, oldest first.

    None when the file is absent, unreadable or not a list of records: that
    costs a rerun, never a crash.
    """
    path = directory / f"{task}.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(records, list) or not all(_is_record(r) for r in records):
        return []
    return records


def save(directory: Path, task: str, record: Record) -> None:
    """Add `record` to `task`'s file, keeping the newest ``KEPT``.

    Written to a temporary file and moved into place, so a reader (another
    worktree's run) never sees half a file; a write that fails removes it.
    """
    write(directory, task, [*load(directory, task), record])


def write(directory: Path, task: str, records: list[Record]) -> None:
    """Write `records` as `task`'s file, the newest ``KEPT`` of them.

    Written to a temporary file and moved into place, so a reader (another
    worktree's run) never sees half a file; a write that fails removes it.

    Parameters
    ----------
    directory : Path
        The records' directory, made when absent.
    task : str
        The name of the file, without ``.json``.
    records : list of Record
        Oldest first.
    """
    directory.mkdir(parents=True, exist_ok=True)
    records = records[-KEPT:]
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(records, out, indent=1, sort_keys=True)
        os.replace(temporary, directory / f"{task}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _changed(task: Task, root: Path, config: str, files: dict[str, str]) -> list[Path]:
    """Return the files of `files` no kept record of `task` passed under `config`."""
    passed = {
        (name, sha)
        for record in load(record_dir(root), task.name)
        if record["config"] == config
        for name, sha in record["files"].items()
    }
    return [Path(n) for n, sha in files.items() if (n, sha) not in passed]


def changed_files(task: Task, root: Path) -> list[Path]:
    """Return `task`'s input files with no passed record, relative to `root`.

    Parameters
    ----------
    task : Task
        A per-file task.
    root : Path
        The repository's working tree.

    Returns
    -------
    list of Path
        Sorted: the files whose digest no kept record passed under today's
        configuration, so every file when the configuration changed.
    """
    files = _hashes(_listed(task.inputs, root), root)
    return _changed(task, root, _config(task, root), files)


def _run_steps(
    task: Task, root: Path, files: list[Path] | None, *, everything: bool = False
) -> int:
    """Run every step of `task`, each given its share of `files` when set.

    With `everything`, each step is given its ``everything`` arguments too.

    Returns the first failing step's exit code, else 0: a failure does not
    stop the steps after it, so their findings show too.
    """
    first = 0
    for step in task.steps:
        argv = list(step.command)
        if everything:
            argv += step.everything
        if files is not None:
            taken = set(_listed(step.files or task.inputs, root))
            mine = [f.as_posix() for f in files if f.as_posix() in taken]
            if not mine:
                continue
            argv += mine
        code = subprocess.run(argv, cwd=root, check=False).returncode
        if code not in step.ok and first == 0:
            first = code
    return first


def _run_always(task: Task, root: Path) -> int:
    """Run the steps of `task` that run when it is unchanged, on all its inputs.

    Returns the first failing step's exit code, else 0.
    """
    first = 0
    for step in task.steps:
        if not step.always:
            continue
        code = subprocess.run(list(step.command), cwd=root, check=False).returncode
        if code not in step.ok and first == 0:
            first = code
    return first


def run(task_name: str, root: Path, *, everything: bool = False) -> int:
    """Run the task `task_name` unless a passed run checked today's inputs.

    A step marked ``always`` runs either way: it keeps records of its own.

    Parameters
    ----------
    task_name : str
        A key of ``TASKS``.
    root : Path
        The repository's working tree.
    everything : bool
        Run every step on every file, recorded or not.

    Returns
    -------
    int
        The exit code of the first step to fail, else 0; every step runs.
    """
    task = TASKS[task_name]
    root = root.resolve()
    whole = digest(task, root)
    config = _config(task, root)
    files = _hashes(_listed(task.inputs, root), root)
    directory = record_dir(root)
    if task.per_file and not files:
        print(f"{task.name}: no files to check", flush=True)  # noqa: T201
        return 0
    if task.per_file:
        todo = (
            sorted(files)
            if everything
            else [p.as_posix() for p in _changed(task, root, config, files)]
        )
        skip = not todo
    else:
        todo = None
        skip = not everything and any(
            r["digest"] == whole for r in load(directory, task.name)
        )
    if skip:
        code = _run_always(task, root)
        print(f"{task.name}: unchanged since a passed run", flush=True)  # noqa: T201
        return code
    code = _run_steps(
        task,
        root,
        None if todo is None else [Path(n) for n in todo],
        everything=everything,
    )
    if code != 0:
        return code
    if digest(task, root) != whole:
        print(  # noqa: T201
            f"{task.name}: not recorded, its inputs changed while it ran", flush=True
        )
        return 0
    save(
        directory,
        task.name,
        Record(digest=whole, config=config, files=files if task.per_file else {}),
    )
    return 0


def _root() -> Path:
    """Return the working tree holding the current directory."""
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(top)


def place() -> str:
    """Return the SHA-256 of the place the checks run in, as one word.

    The same place every task's digest starts with: Python, platform,
    machine. ``just done`` remembers a passed tree with it.

    Returns
    -------
    str
        The hex digest.
    """
    return hashlib.sha256(_place()).hexdigest()


def cli(argv: Sequence[str]) -> int:
    """Parse ``<task> [--all]`` and run it in the current working tree.

    ``--place`` instead prints ``place()`` and runs nothing.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name.

    Returns
    -------
    int
        The task's exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._checks")
    parser.add_argument(
        "task", nargs="?", choices=sorted(TASKS), help="the check to run"
    )
    parser.add_argument(
        "--all", action="store_true", help="run all of it, recorded or not"
    )
    parser.add_argument(
        "--place", action="store_true", help="print the place the checks run in"
    )
    args = parser.parse_args(argv)
    if args.place:
        print(place())  # noqa: T201
        return 0
    if args.task is None:
        parser.error("a task is needed, or --place")
    return run(args.task, _root(), everything=args.all)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
