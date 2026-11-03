"""Tests of .githooks/pre-commit: real commits in scratch repositories."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "pre-commit"

STAND_IN = """#!/usr/bin/env bash
{
  echo "pwd=$PWD"
  echo "args=$*"
  echo "uv_env=${UV_PROJECT_ENVIRONMENT-}"
  echo "uv_no_sync=${UV_NO_SYNC-}"
} >> "$FAKE_JUST_LOG"
if [ -n "${FAKE_JUST_ASSERT-}" ]; then
  eval "$FAKE_JUST_ASSERT" >> "$FAKE_JUST_LOG" 2>&1
fi
exit "${FAKE_JUST_EXIT:-0}"
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


def make_repo(base: Path, tmp_path: Path):
    """Build a scratch repository with the hook, a stand-in just and one commit."""
    repo = base / "repo"
    repo.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    just = bin_dir / "just"
    just.write_text(STAND_IN)
    just.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    log = tmp_path / "just.log"
    env = {
        **os.environ,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_JUST_LOG": str(log),
    }
    for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "FAKE_JUST_EXIT"):
        env.pop(name, None)
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    git(repo, "config", "core.hooksPath", ".githooks", env=env)
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    (repo / ".githooks" / "pre-commit").chmod(0o755)
    (repo / "a.txt").write_text("a-head\n")
    (repo / "b.txt").write_text("b-head\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    log.unlink(missing_ok=True)
    return repo, env, log


@pytest.fixture
def scratch(tmp_path):
    """A scratch repository: (path, env, log)."""
    return make_repo(tmp_path, tmp_path)


def head(repo, env):
    """Return the commit HEAD names."""
    return git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


def test_a_passing_recipe_lets_the_commit_land(scratch):
    """A passing recipe lets the commit through, and the hook ran pre-commit."""
    repo, env, log = scratch
    (repo / "a.txt").write_text("a-new\n")
    git(repo, "add", "a.txt", env=env)
    done = git(repo, "commit", "-m", "chore: edit", env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert "args=pre-commit" in log.read_text()


def test_a_failing_recipe_refuses_the_commit(scratch):
    """A failing recipe refuses the commit and the hook names the cure."""
    repo, env, _ = scratch
    before = head(repo, env)
    (repo / "a.txt").write_text("a-new\n")
    git(repo, "add", "a.txt", env=env)
    done = git(
        repo,
        "commit",
        "-m",
        "chore: edit",
        env={**env, "FAKE_JUST_EXIT": "1"},
        check=False,
    )
    assert done.returncode != 0
    assert head(repo, env) == before
    assert "just fmt" in done.stderr


def test_the_checks_read_the_index_not_the_working_tree(scratch):
    """The export holds the staged content, not the working tree's, outside the repo."""
    repo, env, log = scratch
    (repo / "a.txt").write_text("staged\n")
    git(repo, "add", "a.txt", env=env)
    (repo / "a.txt").write_text("unstaged\n")
    check = 'grep -qx staged a.txt && ! grep -q unstaged a.txt && echo "assert=ok"'
    done = git(
        repo,
        "commit",
        "-m",
        "chore: edit",
        env={**env, "FAKE_JUST_ASSERT": check, "FAKE_JUST_EXIT": "0"},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    text = log.read_text()
    assert "assert=ok" in text
    pwd = next(
        line.removeprefix("pwd=")
        for line in text.splitlines()
        if line.startswith("pwd=")
    )
    assert Path(pwd).resolve() != repo.resolve()
    assert not Path(pwd).resolve().is_relative_to(repo.resolve())


def test_a_partial_commit_checks_only_the_named_paths(scratch):
    """With a partial commit the export holds the named path's new content only."""
    repo, env, log = scratch
    (repo / "a.txt").write_text("a-new\n")
    (repo / "b.txt").write_text("b-new\n")
    git(repo, "add", "a.txt", "b.txt", env=env)
    check = 'grep -qx a-new a.txt && grep -qx b-head b.txt && echo "assert=ok"'
    done = git(
        repo,
        "commit",
        "-m",
        "chore: edit a",
        "--",
        "a.txt",
        env={**env, "FAKE_JUST_ASSERT": check},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "assert=ok" in log.read_text()


def test_a_commit_that_deletes_a_file_passes(scratch):
    """A commit that deletes a file passes, and the file is absent from the export."""
    repo, env, log = scratch
    git(repo, "rm", "b.txt", env=env)
    check = '[ ! -e b.txt ] && [ -e a.txt ] && echo "assert=ok"'
    done = git(
        repo,
        "commit",
        "-m",
        "chore: drop b",
        env={**env, "FAKE_JUST_ASSERT": check},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "assert=ok" in log.read_text()


def test_the_hook_runs_under_a_path_with_spaces(tmp_path):
    """The hook copes with spaces and non-ASCII characters in the repository path."""
    repo, env, log = make_repo(tmp_path / "with space \u2019\u00e9", tmp_path)
    (repo / "a.txt").write_text("a-new\n")
    git(repo, "add", "a.txt", env=env)
    done = git(repo, "commit", "-m", "chore: edit", env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert "args=pre-commit" in log.read_text()


def test_the_hook_runs_in_a_linked_worktree(scratch, tmp_path):
    """In a linked worktree the environment is the worktree's own .venv."""
    repo, env, log = scratch
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-b", "side", str(linked), env=env)
    log.unlink(missing_ok=True)
    (linked / "a.txt").write_text("a-side\n")
    git(linked, "add", "a.txt", env=env)
    done = git(linked, "commit", "-m", "chore: edit", env=env, check=False)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    uv_env = next(line for line in lines if line.startswith("uv_env="))
    assert Path(uv_env.removeprefix("uv_env=")).resolve() == (
        linked.resolve() / ".venv"
    )


def test_the_environment_is_not_synced_from_the_copy(scratch):
    """The hook sets UV_NO_SYNC so nothing is installed from the exported copy."""
    repo, env, log = scratch
    (repo / "a.txt").write_text("a-new\n")
    git(repo, "add", "a.txt", env=env)
    git(repo, "commit", "-m", "chore: edit", env=env)
    assert "uv_no_sync=1" in log.read_text()


def test_no_just_refuses_with_the_cure(scratch, tmp_path):
    """Without just on PATH the commit is refused and the cure is printed."""
    repo, env, _ = scratch
    bare = tmp_path / "bare"
    bare.mkdir()
    for tool in ("git", "bash", "env", "mktemp", "rm", "cat", "dirname", "sh"):
        found = shutil.which(tool)
        assert found is not None, tool
        (bare / tool).symlink_to(found)
    (repo / "a.txt").write_text("a-new\n")
    git(repo, "add", "a.txt", env=env)
    done = git(
        repo,
        "commit",
        "-m",
        "chore: edit",
        env={**env, "PATH": str(bare)},
        check=False,
    )
    assert done.returncode != 0
    assert "brew install just uv" in done.stderr


def test_the_hook_is_committed_executable():
    """The hook is committed with the executable bit, or git silently skips it."""
    done = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/pre-commit"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    assert done.stdout.startswith("100755")
