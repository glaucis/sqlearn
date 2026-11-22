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

from validation import _cases, _record

ROOT = Path(__file__).parent

RUNNERS = (
    "validation.sqlearn.agg.validate_aggregates",
    "validation.sqlearn.preprocessing.validate_impute",
    "validation.sqlearn.preprocessing.validate_scale",
    "validation.sqlearn.preprocessing.validate_onehot",
    "validation.sqlearn.preprocessing.validate_ordinal",
    "validation.sqlearn.preprocessing.validate_target",
    "validation.sqlearn.preprocessing.validate_bin",
    "validation.sqlearn.preprocessing.validate_transform",
    "validation.sqlearn.preprocessing.validate_features",
    "validation.sqlearn.metrics.validate_accuracy",
    "validation.sqlearn.metrics.validate_regression",
    "validation.sqlearn.metrics.validate_probability",
    "validation.sqlearn.metrics.validate_classification",
    "validation.sqlearn.metrics.validate_balanced",
    "validation.sqlearn.metrics.validate_tables",
    "validation.sqlearn.metrics.validate_curves",
    "validation.sqlearn.feature_selection.validate_select",
    "validation.sqlearn.decomposition.validate_pca",
    "validation.sqlearn.explore.validate_explore",
    "validation.pipelines.validate_slice",
    "validation.pipelines.validate_preprocessing",
    "validation.pipelines.validate_model_selection",
    "validation.devdata.validate_bundled",
    "validation.devdata.validate_generated",
)


def results_path(runner: ModuleType) -> Path:
    """Return where a runner's results go: ``validate_x.py`` → ``x.results.json``."""
    source = Path(runner.__file__ or "")
    return source.with_name(source.stem.removeprefix("validate_") + ".results.json")


def run_one(name: str, repo: Path) -> int:
    """Run the runner `name` in this process, write its results, save its record.

    The child's half of `main` (``--one``): what it imported is known only
    in the process that ran it. Exit 1 when a sqlearn case failed.
    """
    runner = importlib.import_module(name)
    cases = runner.cases()
    _cases.write_json(results_path(runner), {"rules": _cases.RULES, "cases": cases})
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["result"]] = counts.get(c["result"], 0) + 1
    print(f"{name}: {dict(sorted(counts.items()))}", flush=True)  # noqa: T201
    failed = [c for c in cases if c["result"] == "fail"]
    _record.save(
        _record.record_dir(repo),
        _record.Record(
            runner=name,
            depends=_record.digest(_record.loaded_files(repo), repo),
            environment=_cases.environment(),
            counts=counts,
            passed=not failed,
        ),
    )
    for c in failed:
        print(f"FAIL: {c}", file=sys.stderr)  # noqa: T201
    return 1 if failed else 0


def main(runners: Sequence[str], root: Path, *, everything: bool = False) -> int:
    """Run each of `runners` that changed since a passed run; write the environment.

    `root` is ``validation/``; its parent is the repository whose files a
    record hashes. A runner whose record matches is reported unchanged and
    its results file left alone; every other one (all of them with
    `everything`) runs in its own process, ``-m validation --one <name>``.
    """
    repo = root.resolve().parent
    environment = _cases.environment()
    directory = _record.record_dir(repo)
    failed = False
    ran = False
    for name in runners:
        records = _record.load(directory, name)
        if not everything and _record.matching(records, repo, environment):
            print(f"{name}: unchanged since a passed run", flush=True)  # noqa: T201
            continue
        child = subprocess.run(
            [sys.executable, "-m", "validation", "--one", name], cwd=repo, check=False
        )
        ran = True
        failed = failed or child.returncode != 0
    if ran:
        _cases.write_json(root / "environment.json", environment)
    return 1 if failed else 0


def _cli(argv: Sequence[str]) -> int:
    """Parse ``[--all]`` or ``--one <module>`` and run."""
    parser = argparse.ArgumentParser(prog="python -m validation")
    parser.add_argument("--all", action="store_true", help="rerun every runner")
    parser.add_argument("--one", metavar="MODULE", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.one:
        return run_one(args.one, Path.cwd().resolve())
    return main(RUNNERS, ROOT, everything=args.all)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
