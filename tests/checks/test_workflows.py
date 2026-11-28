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


def test_codeql_builds_without_the_build_cache():
    """CodeQL reads what the compiler compiles: a restored engine/build makes
    the build a no-op and CodeQL sees nothing, so its job restores no build
    folders and ccache is off."""
    job = _load(RELEASE_TIER)["jobs"]["codeql"]
    setup = next(s for s in job["steps"] if s.get("uses") == "./.github/actions/setup")
    assert setup["with"]["cache"] == "false"
    assert job["env"]["CCACHE_DISABLE"] == "1"
    cache = next(
        s
        for s in _load(SETUP)["runs"]["steps"]
        if s.get("uses", "").startswith("actions/cache@")
    )
    assert cache["if"] == "inputs.cache == 'true'"


def test_a_tag_cannot_run_its_own_code():
    """The tag reaches the recipe's shell as an argument, never as its text."""
    # Run as code, it would print 42 marked; as text it reads $((6*7)).
    done = _release_tag("v1.0.0' ]] || echo $((6*7))-RAN; [[ 'v1.0.0")
    assert done.returncode != 0
    assert "42-RAN" not in done.stdout + done.stderr


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo`; its output, stripped."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _tagged_repo(tmp_path: Path) -> Path:
    """A repository whose one commit is tagged v1.0.0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "c",
    )
    _git(repo, "tag", "v1.0.0")
    return repo


def _release_assets(
    repo: Path, tag: str, assets: Path
) -> subprocess.CompletedProcess[str]:
    """`just check-release-assets <tag> <assets>`, run in `repo`."""
    return subprocess.run(
        [
            "just",
            "--justfile",
            str(REPO / "justfile"),
            "--working-directory",
            str(repo),
            "check-release-assets",
            tag,
            str(assets),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _assets(tmp_path: Path, *names: str) -> Path:
    """A folder holding an empty file of each name."""
    folder = tmp_path / "assets"
    folder.mkdir()
    for name in names:
        (folder / name).write_text("")
    return folder


WHEEL_100 = "sqlearn-1.0.0-cp312-abi3-macosx_15_0_arm64.whl"


def test_a_release_attaches_the_wheels_of_its_tags_commit(tmp_path):
    """Run on the tag's own commit, with wheels of the tag's version: passes."""
    repo = _tagged_repo(tmp_path)
    assert _release_assets(repo, "v1.0.0", _assets(tmp_path, WHEEL_100)).returncode == 0


def test_a_release_run_on_another_commit_is_refused(tmp_path):
    """The workflow built some branch, not the tag: its wheels are not the
    release's."""
    repo = _tagged_repo(tmp_path)
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "d",
    )
    done = _release_assets(repo, "v1.0.0", _assets(tmp_path, WHEEL_100))
    assert done.returncode != 0
    assert "Fix:" in done.stdout + done.stderr


@pytest.mark.parametrize(
    "names",
    [
        ("sqlearn-1.0.1.dev3+gabc-cp312-abi3-macosx_15_0_arm64.whl",),
        (WHEEL_100, "sqlearn-1.0.0.dev1-cp312-abi3-manylinux_2_28_x86_64.whl"),
        (),
    ],
)
def test_a_release_without_its_versions_wheels_is_refused(tmp_path, names):
    """Every wheel is the tag's version, and there is at least one."""
    repo = _tagged_repo(tmp_path)
    done = _release_assets(repo, "v1.0.0", _assets(tmp_path, *names))
    assert done.returncode != 0
    assert "Fix:" in done.stdout + done.stderr


def test_the_release_job_checks_its_assets_before_it_publishes():
    """The release job checks the tag's commit and the wheels' versions, then
    creates the release; it checks out the history, where the tag is."""
    steps = _load(RELEASE_TIER)["jobs"]["release"]["steps"]
    runs = [s["run"] for s in steps if "run" in s]
    assert runs == [
        'just check-release-assets "$TAG" assets',
        'gh release create "$TAG" --verify-tag --title "sqlearn $TAG" assets/*',
    ]
    assert steps[0]["with"]["fetch-depth"] == 0
