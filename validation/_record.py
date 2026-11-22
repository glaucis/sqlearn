"""Each runner's record: the files it imported, hashed, and its verdict.

A runner reruns only when a file it depends on changed (spec §4): every
module it imported from the repository, ``uv.lock`` (the libraries it ran
with) and devdata's files (the data it read). A record holds their SHA-256
hashes, the environment (``_cases.environment()``) and the counts of each
result. It stands for a rerun while it passed, its environment is the same
and every file it names is present with the same hash; anything else reruns.

The records live in the git common directory, so every worktree shares them:
a record is valid only while its hashes match, whichever worktree wrote it.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TypedDict

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


def digest(paths: Iterable[Path], root: Path) -> dict[str, str]:
    """Return each path, relative to `root`, with its content's SHA-256."""
    root = root.resolve()
    return {
        Path(p).resolve().relative_to(root).as_posix(): hashlib.sha256(
            Path(p).read_bytes()
        ).hexdigest()
        for p in paths
    }


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
    """Return the newest record that passed with nothing it depends on changed."""
    for record in reversed(records):
        if (
            record["passed"]
            and record["environment"] == environment
            and _unchanged(record["depends"], root)
        ):
            return record
    return None


def _path(directory: Path, runner: str) -> Path:
    """Return the file holding `runner`'s records."""
    return directory / f"{runner}.json"


def load(directory: Path, runner: str) -> list[Record]:
    """Return `runner`'s records in `directory`, oldest first; none when absent."""
    path = _path(directory, runner)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(directory: Path, record: Record) -> None:
    """Add `record` to its runner's file, keeping the newest ``KEPT``.

    Written to a temporary file and moved into place, so a reader (another
    worktree's run) never sees half a file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    records = [*load(directory, record["runner"]), record][-KEPT:]
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(records, out, indent=1, sort_keys=True)
    os.replace(temporary, _path(directory, record["runner"]))
