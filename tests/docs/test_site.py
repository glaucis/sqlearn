"""The site on GitHub Pages: one version, "dev", under one base, deployed on
each push to main by a workflow that runs no library tests (spec §3.6)."""

import ast
import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
SITE = "https://glaucis.github.io/sqlearn/"
SITE_WORKFLOW = REPO / ".github" / "workflows" / "site.yml"


def _site_workflow() -> dict[str, Any]:
    """site.yml."""
    return yaml.safe_load(SITE_WORKFLOW.read_text())


def test_the_switcher_points_at_the_dev_site():
    """The version switcher's one entry is the dev site (#6)."""
    entries = json.loads((REPO / "docs" / "_static" / "switcher.json").read_text())
    assert entries == [{"name": "dev", "version": "dev", "url": SITE + "dev/"}]


def test_the_readme_holds_no_relative_link():
    """PyPI renders the README without the repository, so every link in it is
    absolute (#4); the Python versions page is the site's."""
    text = (REPO / "README.md").read_text()
    targets = re.findall(r"\]\(([^)]+)\)", text)
    assert targets
    assert [t for t in targets if not t.startswith("https://")] == []
    assert SITE + "dev/architecture/python-versions.html" in targets


def test_the_site_knows_its_base():
    """The pages' canonical links are under the dev site."""
    tree = ast.parse((REPO / "docs" / "conf.py").read_text())
    values = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert values.get("html_baseurl") == SITE + "dev/"


def test_the_site_root_sends_readers_to_dev():
    """The root page redirects to dev/, where 1.0.0's versions sit beside it."""
    page = (REPO / "docs" / "_redirect" / "index.html").read_text()
    assert '<meta http-equiv="refresh" content="0; url=dev/">' in page
    assert '<link rel="canonical" href="' + SITE + 'dev/">' in page


def test_the_site_deploys_from_main_and_runs_no_library_tests():
    """On a push to main or by hand; it checks the links and builds the site
    with its doctests, and runs no test suite, runner or C++ test."""
    workflow = _site_workflow()
    on = workflow.get("on", workflow.get(True))
    assert on == {"push": {"branches": ["main"]}, "workflow_dispatch": None}
    runs = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step
    ]
    assert runs == ["just links", "just build-site _site"]


def test_the_deploy_job_alone_writes_to_pages():
    """Building reads the repository; only the deploy may publish."""
    jobs = _site_workflow()["jobs"]
    assert set(jobs) == {"build", "deploy"}
    assert "permissions" not in jobs["build"]
    assert jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert jobs["deploy"]["needs"] == "build"
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
