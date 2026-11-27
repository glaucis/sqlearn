"""The audit of the C++ groups' claims by coverage (``just audit-groups``).

Each C++ group declares the Python tests and the validation runners that use
it (``sq_add_group``'s ``PYTHON_TESTS`` and ``VALIDATION``), and the checks
rerun a test set or a runner only when the groups it declares change (spec
§5.2 of ``docs/specs/selection-by-group.md``). A declaration naming too few
groups would skip a rerun unseen, so the audit runs them on the coverage
wheel, sqlearn's C++ built with Clang's source-based coverage and DuckDB
not (the override of ``pyproject.toml`` that ``_groups.AUDIT_ENV`` selects,
built in ``COVERAGE_BUILD``), and fails when one ran C++ of a group outside
its declared groups and those they are built on.

``run`` measures a bare ``import sqlearn`` first: what it runs (``core``'s
start-up, the ``crash`` handler) must be in the shared part, the closure of
the groups the bindings and the extension read
(``_groups.Fingerprints.shared_groups``), since a change to it reruns
everything; a group that runs at import outside it is a finding
(``startup``). Any set may run the shared groups. A set declares every group
whose claimed paths overlap its own (``declarations``). Then each Python
test set (``_pytest_sets.sets``),
its passes of ``_pytest_sets.PASSES``, and each validation runner a group
claims, each in its own processes with ``LLVM_PROFILE_FILE`` in a directory of
its own; llvm-profdata merges each one's profiles and ``llvm-cov export
-summary-only`` of the module says which groups ran (``ran``). A set or runner
no group claims uses every group, so it can never be a finding and is not
measured. Each finding (``findings``) names the group to add. The runners run
without their records and results files, and the sets without
``tests.json``: the audit writes nothing but its own directory, ``OUT``.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from validation import _coverage, _groups, _pytest_sets
from validation.__main__ import RUNNERS

COVERAGE_BUILD = Path("build") / f"coverage-{sys.implementation.cache_tag}"
"""The coverage wheel's build directory, relative to the root (the override's
``build-dir``, ``build/coverage-{cache_tag}``), whose manifest the audit
reads."""

OUT = Path("build/audit")
"""Where the profiles go, relative to the root, emptied at each run."""

STARTUP = "startup"
"""The name of the bare import's measure, as no set or runner is called."""


def _say(text: str) -> None:
    """Print `text` at once, before the output of a program run after it."""
    print(text, flush=True)  # noqa: T201


def _owner(filename: str, groups: dict[str, _groups.Group]) -> str | None:
    """Return the group whose directory holds `filename`, the deepest one."""
    path = "/" + filename.replace("\\", "/").lstrip("/")
    holding = [g for g in groups.values() if f"/{g.dir.strip('/')}/" in path]
    if not holding:
        return None
    return max(holding, key=lambda g: len(g.dir)).name


def ran(export: dict[str, Any], groups: dict[str, _groups.Group]) -> set[str]:
    """Return the groups with any covered region in `export`.

    Parameters
    ----------
    export : dict
        ``llvm-cov export -summary-only``'s JSON: each file's path, as it
        was compiled, and its regions' summary.
    groups : dict of str to Group
        The manifest's groups; a file counts for the group whose ``dir``
        holds it.

    Returns
    -------
    set of str
        The groups any of whose regions ran.
    """
    found = set()
    for data in export.get("data", []):
        for entry in data.get("files", []):
            regions = entry.get("summary", {}).get("regions", {})
            if int(regions.get("covered", 0)) <= 0:
                continue
            owner = _owner(str(entry.get("filename", "")), groups)
            if owner is not None:
                found.add(owner)
    return found


def startup(profile: dict[str, Any], groups: dict[str, _groups.Group]) -> set[str]:
    """Return the groups a bare ``import sqlearn`` runs.

    They must belong to the shared part (spec §5.2): every test and runner
    runs them, so a change to one must rerun everything (``findings``).

    Parameters
    ----------
    profile : dict
        ``llvm-cov export -summary-only``'s JSON of the import alone.
    groups : dict of str to Group
        The manifest's groups.

    Returns
    -------
    set of str
        The groups the import ran.
    """
    return ran(profile, groups)


def _fix(name: str, group: str, groups: dict[str, _groups.Group]) -> str:
    """Return the claim that would declare `group` for the set or runner `name`."""
    if name.startswith("group:"):
        paths = " ".join(groups[name.removeprefix("group:")].python_tests)
        return f"sq_add_group({group} PYTHON_TESTS {paths})"
    return f"sq_add_group({group} VALIDATION {name})"


def findings(
    declared: dict[str, set[str] | None],
    seen: dict[str, set[str]],
    start: set[str],
    shared: set[str],
    groups: dict[str, _groups.Group],
) -> list[str]:
    """Return each group a set or runner ran outside what it declares.

    Parameters
    ----------
    declared : dict of str to set of str or None
        Each set (``group:<name>``, as ``_pytest_sets.sets`` names it) or
        runner (its claim name, ``validate_pca``) with the groups it
        declares; None for every group, which never yields a finding.
    seen : dict of str to set of str
        Each one's groups that ran (``ran``).
    start : set of str
        The groups the bare import ran (``startup``).
    shared : set of str
        The groups in the shared part (``Fingerprints.shared_groups``): any
        set may run them, as a change to one reruns everything.
    groups : dict of str to Group
        The manifest's groups.

    Returns
    -------
    list of str
        First ``"<group> runs at import but is not shared: Fix: ..."`` for
        each group of `start` outside `shared` (a change to it would rerun
        nothing), then ``"<set> ran <group>: Fix: ..."`` for each, sorted by
        set then group.

    Raises
    ------
    Unreadable
        A declaration names no group of the manifest.
    """
    found = [
        f"{group} runs at import but is not shared: Fix: include its header in "
        "the bindings (engine/src/bindings/), so it is in the shared part, or "
        "keep it from running at import"
        for group in sorted(start - shared)
    ]
    for name in sorted(seen):
        uses = declared.get(name)
        if uses is None:
            continue
        allowed = _groups.closure(groups, uses) | shared
        found.extend(
            f"{name} ran {group}: Fix: add it to {_fix(name, group, groups)}"
            for group in sorted(seen[name] - allowed)
        )
    return found


def _overlap(one: str, other: str) -> bool:
    """Return whether the paths `one` and `other` are equal or one holds the other."""
    one, other = one.rstrip("/"), other.rstrip("/")
    return one == other or one.startswith(f"{other}/") or other.startswith(f"{one}/")


def declarations(
    sets: _pytest_sets.Sets, groups: dict[str, _groups.Group]
) -> dict[str, set[str] | None]:
    """Return what each Python test set declares, for the audit.

    A set's tests can be claimed by several groups: two groups claiming one
    path run the same tests, and a group claiming a directory runs the tests
    another claims under it. So a set declares every group claiming a path
    equal to one of its own, above it or below it; the claims that exist then
    clear what it runs.

    Parameters
    ----------
    sets : dict
        ``_pytest_sets.sets``' result: each set's paths and groups.
    groups : dict of str to Group
        The manifest's groups.

    Returns
    -------
    dict of str to set of str or None
        Each set with the groups it declares; None for every group.
    """
    found: dict[str, set[str] | None] = {}
    for name, (paths, uses) in sets.items():
        if uses is None:
            found[name] = None
            continue
        found[name] = set(uses) | {
            g.name
            for g in groups.values()
            if any(_overlap(p, c) for p in paths for c in g.python_tests)
        }
    return found


def _module() -> Path:
    """Return the module's binary, found without loading it."""
    spec = importlib.util.find_spec(_groups.MODULE)
    if spec is None or spec.origin is None:
        raise _groups.Unreadable(f"no module {_groups.MODULE} is installed")
    return Path(spec.origin)


def _measure(
    name: str, argvs: Sequence[Sequence[str]], root: Path, module: Path
) -> tuple[dict[str, Any], int]:
    """Run each of `argvs` with its profiles in ``OUT/<name>``; return their
    export and the first failing exit code (pytest's ``NO_TESTS`` passes).

    Raises
    ------
    Unreadable
        No program wrote a profile: the module is not instrumented.
    """
    profiles = root / OUT / name.replace(":", "-")
    profiles.mkdir(parents=True)
    env = dict(os.environ, LLVM_PROFILE_FILE=str(profiles / "%p-%m.profraw"))
    first = 0
    for argv in argvs:
        code = subprocess.run(argv, cwd=root, env=env, check=False).returncode
        if code not in {0, _pytest_sets.NO_TESTS}:
            first = first or code
    raw = sorted(profiles.glob("*.profraw"))
    if not raw:
        raise _groups.Unreadable(
            f"{name} wrote no coverage profile, so {module} is not instrumented.\n"
            "Fix: run it through just audit-groups, which builds the coverage wheel"
        )
    merged = profiles / "merged.profdata"
    tools = _coverage.LLVM
    merge = [str(tools / "llvm-profdata"), "merge", "-sparse", *map(str, raw)]
    subprocess.run([*merge, "-o", str(merged)], check=True)
    cover = [str(tools / "llvm-cov"), "export", "-summary-only"]
    export = subprocess.run(
        [*cover, f"-instr-profile={merged}", str(module)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(export), first


def run(root: Path) -> int:
    """Measure the bare import, each claimed set and runner; print the findings.

    Parameters
    ----------
    root : Path
        The repository's working tree, its coverage wheel installed in the
        running environment.

    Returns
    -------
    int
        1 when there is a finding, a measured program failed, or the build
        cannot be read; else 0.
    """
    root = root.resolve()
    try:
        groups, _ = _groups.load(root / COVERAGE_BUILD)
        shared = set(_groups.fingerprints(root, COVERAGE_BUILD).shared_groups)
        module = _module()
    except _groups.Unreadable as error:
        _say(f"The audit cannot read the coverage build: {error}")
        return 1
    shutil.rmtree(root / OUT, ignore_errors=True)
    python = sys.executable
    declared: dict[str, set[str] | None] = {}
    seen: dict[str, set[str]] = {}
    failed = []
    try:
        profile, code = _measure(
            STARTUP, [[python, "-c", "import sqlearn"]], root, module
        )
        if code:
            failed.append(STARTUP)
        start = startup(profile, groups)
        _say(f"{STARTUP}: ran {', '.join(sorted(start)) or 'no group'}")
        measures: dict[str, list[list[str]]] = {}
        sets = _pytest_sets.sets(groups, root)
        declared.update(declarations(sets, groups))
        for name, (paths, _) in sets.items():
            measures[name] = [
                [python, "-m", "pytest", *options, *paths]
                for options in _pytest_sets.PASSES
            ]
        for runner in RUNNERS:
            claim = runner.rsplit(".", 1)[-1]
            claimed = {g.name for g in groups.values() if claim in g.validation}
            declared[claim] = claimed or None
            load = f"import importlib; importlib.import_module({runner!r}).cases()"
            measures[claim] = [[python, "-c", load]]
        for name, argvs in measures.items():
            if declared[name] is None:
                _say(f"{name}: claimed by no group, so uses every one: not measured")
                continue
            _say(f"{name}: declares {', '.join(sorted(declared[name] or ()))}")
            export, code = _measure(name, argvs, root, module)
            if code:
                failed.append(name)
            seen[name] = ran(export, groups)
        found = findings(declared, seen, start, shared, groups)
    except (_groups.Unreadable, ValueError, subprocess.CalledProcessError) as error:
        _say(f"The audit could not measure the groups: {error}")
        return 1
    for line in found:
        _say(line)
    for name in failed:
        _say(f"{name}: failed on the coverage wheel, so its measure may be short")
    if not found and not failed:
        _say("No set or runner ran a group outside its declared groups.")
    return 1 if found or failed else 0


def cli(argv: Sequence[str]) -> int:
    """Run the audit on the working tree (no arguments).

    Parameters
    ----------
    argv : sequence of str
        The arguments after the program's name (none).

    Returns
    -------
    int
        ``run``'s exit code.
    """
    argparse.ArgumentParser(prog="python -m validation._audit").parse_args(argv)
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return run(Path(top))


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
