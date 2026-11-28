"""Run the validation runners that changed, write the results, gate on failure.

``python -m validation`` (``just validate``) reruns each runner only when a
file it imported changed since a passed run (``_record``); ``--all`` (``just
validate-all``, at a release) reruns every one. Each runner runs in its own
process, writes its cases to ``<name>.results.json`` beside it, and saves its
record; ``environment.json`` is written at the top when any runner ran. Exit 1
when any sqlearn case fails (ADR 0016: a failure blocks the merge).
"""

import argparse
import importlib
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from validation import _cases, _checks, _groups, _record

ROOT = Path(__file__).parent

RUNNERS: tuple[str, ...] = ()
"""The runners, by module. None today: the old Python's runners are in
``old_python/validation/``, and the C++'s are written group by group."""


def results_path(runner: ModuleType) -> Path:
    """Return where a runner's results go: ``validate_x.py`` → ``x.results.json``."""
    source = Path(runner.__file__ or "")
    return source.with_name(source.stem.removeprefix("validate_") + ".results.json")


def run_one(name: str, repo: Path, groups: str | None = None) -> int:
    """Run the runner `name` in this process, write its results, save its record.

    The child's half of `main` (``--one``): what it imported is known only
    in the process that ran it. The files it could depend on are hashed
    before it is imported, and those hashes recorded; a file it loaded that
    changed while it ran, or was not there before, or a C++ group it uses that
    changed, saves no record of a pass; nor does a run under groups that could
    not be read (``_checks.UNREADABLE``). Exit 1 when a sqlearn case failed.
    `groups` is the identity of the C++ groups the runner uses, which `main`
    took once for every runner; `main` then takes it again after all of them
    and drops the passes of a runner whose groups moved. Run alone (None), the
    identity is computed here, and again after the run.
    """
    before = _record.candidates(repo)
    environment = _cases.environment()
    environment["groups"] = groups if groups is not None else _record.engine(repo, name)
    runner = importlib.import_module(name)
    cases = runner.cases()
    _cases.write_json(results_path(runner), {"rules": _cases.RULES, "cases": cases})
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["result"]] = counts.get(c["result"], 0) + 1
    print(f"{name}: {dict(sorted(counts.items()))}", flush=True)  # noqa: T201
    failed = [c for c in cases if c["result"] == "fail"]
    depends, moved = _record.as_before(_record.loaded_files(repo), before, repo)
    # run alone, the identity was taken before the run: take it again, so a
    # pass is never recorded for groups that changed since; `main` does so
    # once for every runner it ran
    if groups is None and _record.engine(repo, name) != environment["groups"]:
        moved.append("the C++ groups it uses")
    # a failed run is saved whatever moved: it only ever makes a runner rerun,
    # and cancels an earlier pass of the same inputs. Under groups that could
    # not be read nothing is saved: such a record stands for no build, and a
    # failure under it cancels no pass (``matching`` compares environments)
    if environment["groups"] == _checks.UNREADABLE:
        print(  # noqa: T201
            f"{name}: not recorded, the C++ groups are unreadable", flush=True
        )
    elif moved and not failed:
        print(  # noqa: T201
            f"{name}: not recorded, these files or groups changed while it ran or"
            f" were not there before: {', '.join(moved)}",
            flush=True,
        )
    else:
        _record.save(
            _record.record_dir(repo),
            _record.Record(
                runner=name,
                depends=depends,
                environment=environment,
                counts=counts,
                passed=not failed,
            ),
        )
    for c in failed:
        print(f"FAIL: {c}", file=sys.stderr)  # noqa: T201
    return 1 if failed else 0


def _drop_moved(repo: Path, ran: dict[str, str], readable: bool) -> None:
    """Drop the passes of runners in `ran` whose C++ groups moved while they ran.

    `ran` maps a runner to the identity it ran under; the identity is taken
    again here, once for every runner, so a pass is never kept for groups
    that changed since. Nothing to do when the build was unreadable (nothing
    was recorded then).
    """
    if not readable:
        return
    try:
        after = _groups.fingerprints(repo, _groups.WHEEL_BUILD)
    except _groups.Unreadable:
        after = None
    directory = _record.record_dir(repo)
    for name, identity in ran.items():
        now = _record.engine(repo, name, after) if after else _checks.UNREADABLE
        if now != identity:
            _record.forget_passes(directory, name, identity)
            print(  # noqa: T201
                f"{name}: not recorded, these files or groups changed while it"
                " ran or were not there before: the C++ groups it uses",
                flush=True,
            )


def main(runners: Sequence[str], root: Path, *, everything: bool = False) -> int:
    """Run each of `runners` that changed since a passed run; write the environment.

    `root` is ``validation/``; its parent is the repository whose files a
    record hashes. A runner whose record matches is reported unchanged and
    its results file left alone; every other one (all of them with
    `everything`) runs in its own process, ``-m validation --one <name>``.
    """
    if not runners:
        print("no validation runners: nothing to validate", flush=True)  # noqa: T201
        return 0
    repo = root.resolve().parent
    base = _cases.environment()
    directory = _record.record_dir(repo)
    try:
        prints = _groups.fingerprints(repo, _groups.WHEEL_BUILD)
    except _groups.Unreadable as error:
        # no record matches: every runner reruns, and none keeps a match
        print(f"the C++ groups are unreadable: {error}", flush=True)  # noqa: T201
        prints = None
    failed = False
    ran: dict[str, str] = {}
    for name in runners:
        # a record's environment holds the identity of the groups the runner
        # uses; environment.json is committed, so it keeps the versions alone
        identity = _record.engine(repo, name, prints) if prints else _checks.UNREADABLE
        environment = {**base, "groups": identity}
        records = _record.load(directory, name)
        if not everything and _record.matching(records, repo, environment):
            print(f"{name}: unchanged since a passed run", flush=True)  # noqa: T201
            continue
        child = subprocess.run(
            [sys.executable, "-m", "validation", "--one", name, "--groups", identity],
            cwd=repo,
            check=False,
        )
        ran[name] = identity
        failed = failed or child.returncode != 0
    if ran:
        _drop_moved(repo, ran, prints is not None)
        _cases.write_json(root / "environment.json", base)
    return 1 if failed else 0


def _cli(argv: Sequence[str]) -> int:
    """Parse ``[--all]`` or ``--one <module>`` and run."""
    parser = argparse.ArgumentParser(prog="python -m validation")
    parser.add_argument("--all", action="store_true", help="rerun every runner")
    parser.add_argument("--one", metavar="MODULE", help=argparse.SUPPRESS)
    parser.add_argument("--groups", metavar="IDENTITY", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.one:
        return run_one(args.one, Path.cwd().resolve(), args.groups)
    return main(RUNNERS, ROOT, everything=args.all)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
