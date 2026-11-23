"""Each runner's record: the files it imported, hashed, and its verdict.

A runner reruns only when a file it depends on changed (spec §4): every
module it imported from the repository, ``uv.lock`` (the libraries it ran
with) and devdata's files (the data it read). A record holds their SHA-256
hashes as they were before the runner was imported (``candidates``), the
environment (``_cases.environment()``: the libraries, Python, the OS and its
release, the machine, numpy's BLAS; with ``engine``, the digest of what the
engine module is built from) and the counts of each result. A file
it loaded that changed while it ran, or was not there before, saves no
passed record, so results of the old code are never recorded as the new
code's. A runner is skipped when the newest record whose environment is the
same and whose every file is present with the same hash passed; a failed run
of the same inputs cancels an earlier pass, and anything else reruns.

The records live in the git common directory, so every worktree shares them:
a record is valid only while its hashes match, whichever worktree wrote it.
"""

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TypedDict

from validation import _checks

KEPT = 20
"""How many records of each runner are kept, the newest."""


class Record(TypedDict):
    """One run of one runner: what it depended on, where, and how it went."""

    runner: str
    depends: dict[str, str]
    environment: dict[str, str]
    counts: dict[str, int]
    passed: bool


def loaded_files(root: Path) -> list[Path]:
    """Return the files a run under `root` depended on, resolved and sorted.

    The source of every imported module under `root` and outside its
    ``.venv``, ``uv.lock``, and every file under ``devdata/data/``.
    """
    root = root.resolve()
    venv = root / ".venv"
    files = set()
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if (
            path.is_relative_to(root)
            and not path.is_relative_to(venv)
            and path.is_file()
        ):
            files.add(path)
    lock = root / "uv.lock"
    if lock.is_file():
        files.add(lock)
    data = root / "devdata" / "data"
    if data.is_dir():
        files.update(p for p in data.rglob("*") if p.is_file())
    return sorted(files)


def candidates(root: Path) -> dict[str, str]:
    """Return, hashed, every file a run under `root` could depend on.

    The Python files git lists under `root` (tracked, or untracked and not
    ignored) outside its ``.venv``, ``uv.lock`` and every file under
    ``devdata/data/``: taken before the runner is imported, the hashes a
    record keeps for the files it then loaded.
    """
    root = root.resolve()
    out = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
            "*.pyi",
            ":(exclude).venv",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    files = {root / n.decode() for n in out.split(b"\0") if n}
    lock = root / "uv.lock"
    files.add(lock)
    data = root / "devdata" / "data"
    if data.is_dir():
        files.update(data.rglob("*"))
    return digest((p for p in files if p.is_file()), root)


def as_before(
    loaded: Iterable[Path], before: dict[str, str], root: Path
) -> tuple[dict[str, str], list[str]]:
    """Return the pre-run hashes of `loaded`, and those of it that changed.

    Parameters
    ----------
    loaded : iterable of Path
        The files the run loaded (``loaded_files``).
    before : dict of str to str
        ``candidates`` taken before the run.
    root : Path
        The repository.

    Returns
    -------
    tuple of (dict of str to str, list of str)
        Each loaded file with its hash before the run, and the sorted names
        of those whose bytes changed during the run or that were not there
        before it: when any, no passed record is saved.
    """
    now = digest(loaded, root)
    depends = {name: before[name] for name in now if name in before}
    moved = sorted(name for name, sha in now.items() if before.get(name) != sha)
    return depends, moved


def digest(paths: Iterable[Path], root: Path) -> dict[str, str]:
    """Return each path, relative to `root`, with its content's SHA-256."""
    root = root.resolve()
    return {
        Path(p).resolve().relative_to(root).as_posix(): hashlib.sha256(
            Path(p).read_bytes()
        ).hexdigest()
        for p in paths
    }


def _compiler() -> str:
    """Return the first line of the C++ compiler's ``--version``, or ``none``.

    The compiler CMake picks: ``CXX``, else ``c++``.
    """
    command = shlex.split(os.environ.get("CXX") or "c++")
    try:
        done = subprocess.run(
            [*command, "--version"], capture_output=True, text=True, check=False
        )
    except OSError:
        return "none"
    return (done.stdout.splitlines() or ["none"])[0]


def engine(root: Path) -> str:
    """Return the digest of what the engine module under `root` is built from.

    Every file under ``engine/`` and the commit each submodule there pins,
    as ``_checks`` digests a task's inputs; ``pyproject.toml``'s
    ``[build-system]`` table (the build requirements, pinned exactly) and its
    ``[tool.scikit-build]`` table; and the C++ compiler's version. A module
    built from other inputs is another engine, so every runner reruns. Its
    inputs, not the binary nor its version string: a rebuild of the same
    inputs is the same engine, and the version stays ``2.0.1`` through any
    edit of sqlearn's C++.
    """
    root = root.resolve()
    files = _checks._listed(("engine",), root)
    links = _checks._gitlinks(("engine",), root)
    pyproject = root / "pyproject.toml"
    project = (
        tomllib.loads(pyproject.read_text(encoding="utf-8"))
        if pyproject.is_file()
        else {}
    )
    tables = {
        "build-system": project.get("build-system", {}),
        "scikit-build": project.get("tool", {}).get("scikit-build", {}),
    }
    sha = hashlib.sha256(_checks._combined(files, root, links).encode() + b"\0")
    sha.update(json.dumps(tables, sort_keys=True).encode() + b"\0")
    sha.update(_compiler().encode())
    return sha.hexdigest()


def environment(base: dict[str, str], root: Path) -> dict[str, str]:
    """Return the environment a record keeps: `base`, with the engine's digest."""
    return {**base, "engine": engine(root)}


def record_dir(root: Path) -> Path:
    """Return the records' directory: ``sqlearn-validation`` in git's common one."""
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (root / common).resolve() / "sqlearn-validation"


def _unchanged(depends: dict[str, str], root: Path) -> bool:
    """Whether every file of `depends` is present under `root` with its hash."""
    for name, sha in depends.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            return False
    return True


def matching(
    records: Sequence[Record], root: Path, environment: dict[str, str]
) -> Record | None:
    """Return the newest record of today's inputs, if it passed; else None.

    Among the records whose environment equals `environment` and whose every
    file is present with the same hash, the newest decides: a failed run
    cancels an earlier pass of the same inputs, so the runner reruns.
    """
    for record in reversed(records):
        if record["environment"] == environment and _unchanged(record["depends"], root):
            return record if record["passed"] else None
    return None


def _path(directory: Path, runner: str) -> Path:
    """Return the file holding `runner`'s records."""
    return directory / f"{runner}.json"


def _is_record(value: object) -> bool:
    """Return whether `value` has a record's shape, as JSON gives it."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("runner"), str)
        and isinstance(value.get("passed"), bool)
        and all(
            isinstance(value.get(key), dict)
            for key in ("depends", "environment", "counts")
        )
        and all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in value["depends"].items()
        )
    )


def load(directory: Path, runner: str) -> list[Record]:
    """Return `runner`'s records in `directory`, oldest first.

    None when the file is absent, unreadable or not a list of records: that
    costs a rerun, never a crash.
    """
    try:
        records = json.loads(_path(directory, runner).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(records, list) or not all(_is_record(r) for r in records):
        return []
    return records


def save(directory: Path, record: Record) -> None:
    """Add `record` to its runner's file, keeping the newest ``KEPT``.

    Written to a temporary file and moved into place, so a reader (another
    worktree's run) never sees half a file; a write that fails removes it.
    """
    directory.mkdir(parents=True, exist_ok=True)
    records = [*load(directory, record["runner"]), record][-KEPT:]
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(records, out, indent=1, sort_keys=True)
        os.replace(temporary, _path(directory, record["runner"]))
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
