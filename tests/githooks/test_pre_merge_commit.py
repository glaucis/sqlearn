"""Tests of .githooks/pre-merge-commit: real merges in scratch repositories."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".githooks"

# Notes each run, and fails where the file FAKE_JUST_FAIL_ON names is present
# in the directory it runs in: the export of the index the hook checks.
STAND_IN = """#!/usr/bin/env bash
echo "args=$*" >> "$FAKE_JUST_LOG"
if [ -n "${FAKE_JUST_FAIL_ON-}" ] && [ -e "$FAKE_JUST_FAIL_ON" ]; then
  echo "check failed on $FAKE_JUST_FAIL_ON" >&2
  exit 1
fi
exit 0
"""


def git(cwd, *args, env, check=True):
    """Run git in cwd and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch(tmp_path):
    """A repository with both hooks, a stand-in just, and diverged main and side."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    just = bin_dir / "just"
    just.write_text(STAND_IN)
    just.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "just.log"
    ambient = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "UV_", "FAKE_JUST_"))
    }
    env = {
        **ambient,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_JUST_LOG": str(log),
    }
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    git(repo, "config", "core.hooksPath", ".githooks", env=env)
    (repo / ".githooks").mkdir()
    for name in ("pre-commit", "pre-merge-commit"):
        shutil.copy(HOOKS / name, repo / ".githooks" / name)
        (repo / ".githooks" / name).chmod(0o755)
    (repo / ".venv").mkdir()
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    git(repo, "switch", "-c", "side", env=env)
    (repo / "bad.txt").write_text("bad\n")
    git(repo, "add", "bad.txt", env=env)
    git(repo, "commit", "-m", "chore: add bad", env=env)
    git(repo, "switch", "main", env=env)
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "c.txt", env=env)
    git(repo, "commit", "-m", "chore: add c", env=env)
    log.unlink(missing_ok=True)
    return repo, env, log


def head(repo, env):
    """Return the commit HEAD names."""
    return git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


def test_a_clean_merge_bringing_a_failing_file_is_refused(scratch):
    """A merge without conflicts runs the pre-commit checks, which refuse it."""
    repo, env, log = scratch
    before = head(repo, env)
    done = git(
        repo,
        "merge",
        "--no-edit",
        "side",
        env={**env, "FAKE_JUST_FAIL_ON": "bad.txt"},
        check=False,
    )
    assert done.returncode != 0
    assert head(repo, env) == before
    assert "check failed on bad.txt" in done.stderr
    assert "the commit is refused" in done.stderr
    assert "args=pre-commit" in log.read_text()


def test_a_clean_merge_that_passes_lands(scratch):
    """A merge whose files pass the checks lands as a merge commit."""
    repo, env, log = scratch
    before = head(repo, env)
    done = git(repo, "merge", "--no-edit", "side", env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert git(repo, "rev-parse", "HEAD^1", env=env).stdout.strip() == before
    assert "args=pre-commit" in log.read_text()


def test_the_hook_is_committed_executable():
    """The hook is committed with the executable bit, or git silently skips it."""
    done = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/pre-merge-commit"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    assert done.stdout.startswith("100755")
