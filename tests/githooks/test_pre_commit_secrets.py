"""gitleaks in the commit hook: a staged secret refuses the commit.

The hook runs ``just pre-commit`` on an export of the index. Here a stand-in
``just`` runs the repository's own ``check-secrets`` recipe for it, with the
real ``just`` and gitleaks, so the commit meets the recipe the hook meets.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "pre-commit"
JUST = shutil.which("just")

# gitleaks' own true positive for its aws-access-token rule
# (cmd/generate/config/rules/aws.go), built here so this file holds no key.
FAKE_KEY = "AKIA" + "LALEMEL33243OLIB"

STAND_IN = """#!/usr/bin/env bash
[ "$1" = pre-commit ] || exit 1
exec "$REAL_JUST" --justfile "$REAL_JUSTFILE" --working-directory "$PWD" check-secrets
"""

pytestmark = pytest.mark.skipif(
    JUST is None or shutil.which("gitleaks") is None,
    reason="just and gitleaks (brew install just gitleaks)",
)


def git(cwd, *args, env, check=True):
    """Run git in cwd and return the completed process."""
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True
    )


@pytest.fixture
def scratch(tmp_path):
    """A repository with the hook and one commit, and its environment."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "just").write_text(STAND_IN)
    (bin_dir / "just").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    ambient = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "UV_"))}
    env = {
        **ambient,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REAL_JUST": str(JUST),
        "REAL_JUSTFILE": str(REPO / "justfile"),
    }
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    git(repo, "config", "core.hooksPath", ".githooks", env=env)
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    (repo / ".githooks" / "pre-commit").chmod(0o755)
    (repo / ".venv").mkdir()
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    return repo, env


def test_a_staged_secret_refuses_the_commit(scratch):
    """A staged AWS key refuses the commit; the output names the file and the
    rule, never the key."""
    repo, env = scratch
    before = git(repo, "rev-parse", "HEAD", env=env).stdout
    (repo / "config.txt").write_text(f"aws_access_key_id = {FAKE_KEY}\n")
    git(repo, "add", "config.txt", env=env)
    done = git(repo, "commit", "-m", "chore: add config", env=env, check=False)
    assert done.returncode != 0
    assert git(repo, "rev-parse", "HEAD", env=env).stdout == before
    assert "config.txt" in done.stderr
    assert "aws-access-token" in done.stderr
    assert FAKE_KEY not in done.stdout + done.stderr


def test_a_commit_without_secrets_lands(scratch):
    """A normal file commits."""
    repo, env = scratch
    (repo / "b.txt").write_text("nothing secret\n")
    git(repo, "add", "b.txt", env=env)
    done = git(repo, "commit", "-m", "chore: add b", env=env, check=False)
    assert done.returncode == 0, done.stderr


def test_a_secret_left_unstaged_does_not_refuse_the_commit(scratch):
    """The hook reads what the commit holds: a key on disk but not staged is
    not in it."""
    repo, env = scratch
    (repo / "loose.txt").write_text(f"aws_access_key_id = {FAKE_KEY}\n")
    (repo / "b.txt").write_text("nothing secret\n")
    git(repo, "add", "b.txt", env=env)
    done = git(repo, "commit", "-m", "chore: add b", env=env, check=False)
    assert done.returncode == 0, done.stderr


def test_check_secrets_in_a_checkout_reads_its_index(scratch):
    """Run in a checkout, the recipe exports the index: a staged key fails it,
    the same key unstaged does not."""
    repo, env = scratch
    recipe = [str(JUST), "--justfile", str(REPO / "justfile"), "--working-directory"]
    (repo / "loose.txt").write_text(f"aws_access_key_id = {FAKE_KEY}\n")
    clean = subprocess.run(
        [*recipe, str(repo), "check-secrets"], env=env, capture_output=True, text=True
    )
    assert clean.returncode == 0, clean.stderr
    git(repo, "add", "loose.txt", env=env)
    found = subprocess.run(
        [*recipe, str(repo), "check-secrets"], env=env, capture_output=True, text=True
    )
    assert found.returncode != 0
    assert FAKE_KEY not in found.stdout + found.stderr


def test_the_pre_commit_recipe_runs_check_secrets():
    """`just pre-commit`, what the hook runs, depends on check-secrets."""
    dump = subprocess.run(
        [
            str(JUST),
            "--justfile",
            str(REPO / "justfile"),
            "--dump",
            "--dump-format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    recipe = json.loads(dump.stdout)["recipes"]["pre-commit"]
    assert "check-secrets" in [d["recipe"] for d in recipe["dependencies"]]
