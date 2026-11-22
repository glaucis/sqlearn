"""Each check as a task that runs only when its inputs changed.

A task names its inputs and its configuration as git pathspecs, and the
steps that check them. A whole task (``types``, ``test``) runs when the
digest of its inputs and configuration has no passed record; a per-file
task (``format``, ``lint``) gives each step the files whose own digest has
no passed record under today's configuration, and every file once the
configuration changed. ``everything`` runs it all regardless, and records.

The digest covers the tracked files and the untracked ones git does not
ignore; a tracked file deleted from the working tree is absent from it, so
its deletion is a change. The checks' own outputs are never inputs. The
digest is taken before the run and only that one is recorded, and only
when nothing changed while the task ran, so a file edited meanwhile is
checked again.

The records live in the git common directory, ``sqlearn-checks/``, one
file per task, so every worktree shares them; two worktrees recording at
once can lose a record, which costs a rerun, never a skip.
"""

import argparse
import hashlib
import json
import os
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
    """

    command: tuple[str, ...]
    files: tuple[str, ...] = ()


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
        Its commands, run in order; the first to fail stops it.
    per_file : bool
        Whether each file's result depends only on that file and the
        settings, so only the changed files are checked.
    """

    name: str
    inputs: tuple[str, ...]
    config: tuple[str, ...]
    steps: tuple[Step, ...]
    per_file: bool


class Record(TypedDict):
    """One passed run of one task: the digests of what it checked."""

    digest: str
    config: str
    files: dict[str, str]


TASKS: dict[str, Task] = {}
"""The checks by name (filled by the per-task recipes' table)."""


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


def _hashes(names: Sequence[str], root: Path) -> dict[str, str]:
    """Return each file of `names` with its content's SHA-256."""
    return {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}


def _combined(names: Sequence[str], root: Path) -> str:
    """Return the SHA-256 of each file's path, a NUL, its bytes, a NUL, sorted."""
    sha = hashlib.sha256()
    for name in sorted(names):
        sha.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
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
        The hex digest of every file under its inputs and configuration.
    """
    return _combined(
        sorted({*_listed(task.inputs, root), *_listed(task.config, root)}), root
    )


def _config(task: Task, root: Path) -> str:
    """Return the SHA-256 of `task`'s configuration alone."""
    return _combined(_listed(task.config, root), root)


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


def load(directory: Path, task: str) -> list[Record]:
    """Return `task`'s records in `directory`, oldest first; none when absent."""
    path = directory / f"{task}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(directory: Path, task: str, record: Record) -> None:
    """Add `record` to `task`'s file, keeping the newest ``KEPT``.

    Written to a temporary file and moved into place, so a reader (another
    worktree's run) never sees half a file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    records = [*load(directory, task), record][-KEPT:]
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(records, out, indent=1, sort_keys=True)
    os.replace(temporary, directory / f"{task}.json")


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


def _run_steps(task: Task, root: Path, files: list[Path] | None) -> int:
    """Run `task`'s steps in order, each given its share of `files` when set."""
    for step in task.steps:
        argv = list(step.command)
        if files is not None:
            taken = set(_listed(step.files or task.inputs, root))
            mine = [f.as_posix() for f in files if f.as_posix() in taken]
            if not mine:
                continue
            argv += mine
        code = subprocess.run(argv, cwd=root, check=False).returncode
        if code != 0:
            return code
    return 0


def run(task_name: str, root: Path, *, everything: bool = False) -> int:
    """Run the task `task_name` unless a passed run checked today's inputs.

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
        The exit code of the first step to fail, else 0.
    """
    task = TASKS[task_name]
    root = root.resolve()
    whole = digest(task, root)
    config = _config(task, root)
    files = _hashes(_listed(task.inputs, root), root)
    directory = record_dir(root)
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
        print(f"{task.name}: unchanged since a passed run", flush=True)  # noqa: T201
        return 0
    code = _run_steps(task, root, None if todo is None else [Path(n) for n in todo])
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


def cli(argv: Sequence[str]) -> int:
    """Parse ``<task> [--all]`` and run it in the current working tree.

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
    parser.add_argument("task", choices=sorted(TASKS), help="the check to run")
    parser.add_argument(
        "--all", action="store_true", help="run all of it, recorded or not"
    )
    args = parser.parse_args(argv)
    return run(args.task, _root(), everything=args.all)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
