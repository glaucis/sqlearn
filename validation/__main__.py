"""Run every validation runner, write the results, fail on a sqlearn failure.

``python -m validation`` (``just validate``) writes each runner's cases to
``<name>.results.json`` beside it and ``environment.json`` at the top, and
exits 1 when any sqlearn case fails (ADR 0016: a failure blocks the merge).
"""

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from validation import _cases

ROOT = Path(__file__).parent

RUNNERS = (
    "validation.sqlearn.agg.validate_aggregates",
    "validation.sqlearn.preprocessing.validate_impute",
    "validation.sqlearn.preprocessing.validate_scale",
    "validation.sqlearn.preprocessing.validate_onehot",
    "validation.sqlearn.preprocessing.validate_ordinal",
    "validation.sqlearn.preprocessing.validate_target",
    "validation.sqlearn.metrics.validate_accuracy",
    "validation.pipelines.validate_slice",
)


def results_path(runner: ModuleType) -> Path:
    """Return where a runner's results go: ``validate_x.py`` → ``x.results.json``."""
    source = Path(runner.__file__ or "")
    return source.with_name(source.stem.removeprefix("validate_") + ".results.json")


def main(runners: Sequence[ModuleType], root: Path) -> int:
    """Run `runners`, write their results and the environment under `root`."""
    failed = []
    for runner in runners:
        cases = runner.cases()
        _cases.write_json(results_path(runner), {"rules": _cases.RULES, "cases": cases})
        failed += [c for c in cases if c["result"] == "fail"]
        counts: dict[str, int] = {}
        for c in cases:
            counts[c["result"]] = counts.get(c["result"], 0) + 1
        print(f"{runner.__name__}: {dict(sorted(counts.items()))}")  # noqa: T201
    _cases.write_json(root / "environment.json", _cases.environment())
    for c in failed:
        print(f"FAIL: {c}", file=sys.stderr)  # noqa: T201
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main([importlib.import_module(name) for name in RUNNERS], ROOT))
