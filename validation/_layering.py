"""The layering check: each C++ group's ``DEPENDS`` against what it includes.

A group's ``DEPENDS`` (``sq_add_group``, ``engine/cmake/groups.cmake``)
decides what a change to it reruns, and the link no longer keeps it honest:
each group is a static archive linking its ``DEPENDS``, so linking is
transitive. This check reads the manifest (``<build>/sq_groups.json``) and
the files themselves, and holds no list of allowed layers of its own. The
rules:

1. A group's files (``engine/src/<name>/``) and its tests
   (``engine/tests/<name>/``) include only their own group and the groups
   its ``DEPENDS`` names.
2. ``DEPENDS`` names every group in the closure of the groups it names:
   ``DEPENDS`` is not transitive.
3. Every ``DEPENDS`` entry is in the closure of the groups the group's own
   files include (its tests do not count: the archive links ``DEPENDS`` for
   the group's code). Otherwise it is stale, and makes a change rerun what
   it cannot affect.
4. ``DEPENDS`` has no cycle.
5. No group includes a shared directory (``engine/src/bindings``).

An include names a group when its path's first part is a group's name, as
the groups' include root, ``engine/src``, resolves it; ``"..."`` and
``<...>`` count alike, and so does an include in a comment, so the check
fails safe. Includes of the standard library and third parties name no
group. Run it as ``uv run --locked python -m validation._layering``; the
``tidy`` task runs it after ``just tidy-engine``, which configures the
``llvm-dev`` build whose manifest it reads.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from validation import _groups

INCLUDE_ROOT = "engine/src"
"""Where the groups' includes resolve (``sq_target_options``)."""

TESTS = "engine/tests"
"""The directory holding each group's tests, one directory per group."""

BUILD = Path("engine") / "build" / "llvm-dev"
"""The build whose manifest the check reads, relative to the root."""

_INCLUDE = re.compile(r'#\s*include\s*[<"]([^>"]+)[>"]')
"""An include directive, anywhere on its line: a comment's counts too."""


def _say(text: str) -> None:
    """Print `text` at once, before the output of a program run after it."""
    print(text, flush=True)  # noqa: T201


def _includes(path: Path) -> list[tuple[int, str, str]]:
    """Return each include of `path`: its line number, its line, its path."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [
        (number, line.strip(), match.group(1))
        for number, line in enumerate(text.splitlines(), start=1)
        for match in _INCLUDE.finditer(line)
    ]


def included(path: Path, groups: Iterable[str]) -> set[str]:
    """Return the groups whose headers `path` includes.

    Parameters
    ----------
    path : Path
        A file of C++.
    groups : iterable of str
        The groups' names.

    Returns
    -------
    set of str
        Each group named by the first part of one of the file's includes.
    """
    names = set(groups)
    return {
        first
        for _, _, header in _includes(path)
        if (first := header.split("/", 1)[0]) in names and "/" in header
    }


def _files(root: Path, directory: str) -> list[Path]:
    """Return every file under `directory` of `root`, sorted."""
    return sorted(p for p in (root / directory).rglob("*") if p.is_file())


def _cycles(groups: dict[str, _groups.Group]) -> list[list[str]]:
    """Return each set of groups that depend on one another, sorted."""
    reach = {name: _groups.closure(groups, g.depends) for name, g in groups.items()}
    cycles: list[list[str]] = []
    for name in sorted(groups):
        if name not in reach[name] or any(name in c for c in cycles):
            continue
        cycles.append(sorted(n for n in reach[name] if name in reach[n]))
    return cycles


def problems(
    root: Path,
    groups: dict[str, _groups.Group],
    *,
    shared: Iterable[str] = (),
) -> list[str]:
    """Return what breaks the layering rules, one message per problem.

    Parameters
    ----------
    root : Path
        The repository's root.
    groups : dict of str to Group
        The manifest's groups.
    shared : iterable of str, optional
        The manifest's shared directories, relative to `root`; those under
        ``INCLUDE_ROOT`` are what rule 5 refuses. Empty by default, which
        leaves rule 5 nothing to refuse.

    Returns
    -------
    list of str
        Each problem, ending with a ``Fix:`` line: the includes refused,
        then, group by group, the dependencies to name and the stale ones,
        then the cycles. Empty when every rule holds.
    """
    directories = [d.rstrip("/") for d in shared]
    found: list[str] = []
    for name in sorted(groups):
        group = groups[name]
        allowed = {name, *group.depends}
        for path in _files(root, group.dir) + _files(root, f"{TESTS}/{name}"):
            where = path.relative_to(root).as_posix()
            for number, line, header in _includes(path):
                first = header.split("/", 1)[0]
                target = f"{INCLUDE_ROOT}/{header}"
                inside = [d for d in directories if target.startswith(f"{d}/")]
                if inside:
                    found.append(
                        f"{where}:{number}: {line}: group {name} includes "
                        f"{target} of the shared directory {inside[0]}, which "
                        "no group may reach.\n"
                        f"Fix: move what {name} needs into a group, or drop "
                        "the include"
                    )
                elif "/" in header and first in groups and first not in allowed:
                    named = ", ".join(group.depends) or "nothing"
                    found.append(
                        f"{where}:{number}: {line}: group {name} includes "
                        f"{first}, which its DEPENDS ({named}) does not name.\n"
                        f"Fix: add {first} to DEPENDS of {name} in its "
                        "sq_add_group (engine/CMakeLists.txt), or drop the "
                        "include"
                    )
    for name in sorted(groups):
        group = groups[name]
        missing = _groups.closure(groups, group.depends) - set(group.depends) - {name}
        for other in sorted(missing):
            found.append(
                f"group {name}'s DEPENDS ({', '.join(group.depends)}) leaves out "
                f"{other}, which they depend on: DEPENDS is not transitive.\n"
                f"Fix: add {other} to DEPENDS of {name} in its sq_add_group "
                "(engine/CMakeLists.txt)"
            )
        reads: set[str] = set()
        for path in _files(root, group.dir):
            reads |= included(path, groups)
        reached = _groups.closure(groups, reads - {name})
        for other in sorted(set(group.depends) - reached):
            found.append(
                f"group {name}'s DEPENDS names {other}, which none of "
                f"{group.dir}/ includes, directly or through the groups it "
                f"includes: it is stale, and a change to {other} reruns "
                f"{name}, which it cannot affect.\n"
                f"Fix: remove {other} from DEPENDS of {name} in its "
                "sq_add_group (engine/CMakeLists.txt)"
            )
    for cycle in _cycles(groups):
        found.append(
            f"groups {', '.join(cycle)} depend on one another in a cycle of "
            "DEPENDS.\n"
            "Fix: remove the DEPENDS entry that closes the cycle, moving what "
            "the groups share into a group of its own"
        )
    return found


def cli(argv: Sequence[str]) -> int:
    """Check the working tree's groups against the ``llvm-dev`` manifest.

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name: ``--root`` (the
        repository's root, git's top level by default) and ``--build`` (the
        build holding the manifest, ``BUILD`` under the root by default).

    Returns
    -------
    int
        0 when every rule holds; 1 when one does not, or the manifest cannot
        be read, each problem printed.
    """
    parser = argparse.ArgumentParser(prog="python -m validation._layering")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--build", type=Path)
    args = parser.parse_args(argv)
    root = args.root
    if root is None:
        root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    build = args.build if args.build is not None else root / BUILD
    try:
        groups, shared = _groups.load(build)
    except _groups.Unreadable as error:
        _say(
            f"Layering: {error}.\nFix: run `just tidy-engine`, which configures "
            "the llvm-dev build"
        )
        return 1
    found = problems(root, groups, shared=shared)
    for problem in found:
        _say(problem)
    if found:
        return 1
    _say(f"Layering: the DEPENDS of {', '.join(sorted(groups))} hold.")
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
