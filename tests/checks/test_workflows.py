"""The GitHub workflows: the release tier, started by hand, and the site's
deploy; each step a `just` recipe, each action pinned to a commit."""

import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
RELEASE_TIER = WORKFLOWS / "release-tier.yml"
SETUP = REPO / ".github" / "actions" / "setup" / "action.yml"


def _load(path: Path) -> dict[str, Any]:
    """The YAML file at `path`."""
    return yaml.safe_load(path.read_text())


def _on(workflow: dict[str, Any]) -> dict[str, Any]:
    """A workflow's triggers: YAML 1.1 reads the key `on` as True."""
    return workflow.get("on", workflow.get(True)) or {}


def _steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step of a workflow's jobs, or of a composite action."""
    if "runs" in document:
        return document["runs"]["steps"]
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


def _documents() -> list[tuple[Path, dict[str, Any]]]:
    """Each workflow and the composite action."""
    paths = [*sorted(WORKFLOWS.glob("*.yml")), SETUP]
    return [(path, _load(path)) for path in paths]


def test_the_release_tier_starts_only_by_hand():
    """No CI runs by itself before 1.0.0 (spec §3.5): workflow_dispatch only,
    with an optional tag to release."""
    on = _on(_load(RELEASE_TIER))
    assert list(on) == ["workflow_dispatch"]
    tag = on["workflow_dispatch"]["inputs"]["tag"]
    assert tag["required"] is False
    assert tag["type"] == "string"


def test_every_action_is_pinned_to_a_commit():
    """A tag can be moved; a commit cannot. Each `uses:` names a full SHA."""
    unpinned = [
        (path.name, step["uses"])
        for path, document in _documents()
        for step in _steps(document)
        if "uses" in step
        and not step["uses"].startswith("./")
        and not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"])
    ]
    assert unpinned == []


def test_every_job_names_its_permissions():
    """The workflows read the repository and nothing more, but where a job
    says what else it needs: CodeQL's findings, the release, the Pages
    deploy."""
    wider = {"codeql", "release", "deploy"}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _load(path)
        assert workflow["permissions"] == {"contents": "read"}, path.name
        for name, job in workflow["jobs"].items():
            if name not in wider:
                assert "permissions" not in job, (path.name, name)


def test_every_run_step_is_one_line():
    """A step longer than one line is a `just` recipe, which runs here too."""
    long = [
        (path.name, step.get("name", step["run"][:40]))
        for path, document in _documents()
        for step in _steps(document)
        if "run" in step and "\n" in step["run"].strip()
    ]
    assert long == []


def test_the_release_job_waits_for_every_other_job():
    """A release attaches nothing until every platform and check passed, and
    runs only when a tag was given."""
    jobs = _load(RELEASE_TIER)["jobs"]
    assert set(jobs) == {
        "macos-checks",
        "macos-engine",
        "macos-mutate",
        "linux",
        "codeql",
        "wheels",
        "release",
    }
    assert set(jobs["release"]["needs"]) == set(jobs) - {"release"}
    assert jobs["release"]["if"] == "inputs.tag != ''"


def _release_tag(tag: str) -> subprocess.CompletedProcess[str]:
    """`just check-release-tag <tag>`."""
    return subprocess.run(
        ["just", "--justfile", str(REPO / "justfile"), "check-release-tag", tag],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("tag", ["v1.0.0", "v1.2.0", "v10.11.0"])
def test_a_major_or_minor_tag_is_a_release(tag):
    """A release is a major or minor version tag (spec §3.4)."""
    assert _release_tag(tag).returncode == 0


@pytest.mark.parametrize("tag", ["v1.0.1", "1.0.0", "v1.0.0-rc1", "v1.0", ""])
def test_any_other_tag_is_refused(tag):
    """A patch, a missing v, a suffix: no release tier runs for it."""
    done = _release_tag(tag)
    assert done.returncode != 0
    assert "Fix:" in done.stdout + done.stderr


def test_every_pytest_run_reports_its_skips():
    """A test skipped for want of a platform's reference build is listed in the
    run's summary beside the failures, never a silent green (spec §3.5)."""
    pytest_options = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"][
        "pytest"
    ]["ini_options"]
    assert "-rfEs" in pytest_options["addopts"]
