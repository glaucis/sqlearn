"""Tests of the recipes that remember the tree that passed, in scratch repositories."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Stand-ins for the three tiers; the real justfile is imported under them.
OVERRIDES = """set allow-duplicate-recipes
import 'real.just'

check:
    @echo check >> calls.log

test:
    @echo test >> calls.log

validate:
    @echo validate >> calls.log
"""


def git(cwd, *args, env):
    """Run git in cwd and return its stdout."""
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def just(cwd, *args, env):
    """Run just in cwd and return its stdout."""
    return subprocess.run(
        ["just", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(tmp_path):
    """Build a scratch repository with the justfile's recipes over stand-in tiers."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    ambient = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env = {**ambient, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    shutil.copy(REPO / "justfile", repo / "real.just")
    (repo / "justfile").write_text(OVERRIDES)
    (repo / ".gitignore").write_text("calls.log\n")
    (repo / "a.py").write_text("a = 1\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    return repo, env


def calls(repo):
    """Return the stand-in tiers that have run, in order."""
    log = repo / "calls.log"
    return log.read_text().split() if log.exists() else []


def passed(repo, env):
    """Return the trees remembered for the scratch repository."""
    common = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env)
    )
    file = common / "sqlearn-passed"
    return file.read_text().split() if file.exists() else []


def test_a_clean_tree_that_passed_is_remembered(tmp_path):
    """done runs the three tiers, then remembers the tree."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    assert calls(repo) == ["check", "test", "validate"]
    assert passed(repo, env) == [git(repo, "rev-parse", "HEAD^{tree}", env=env)]


def test_a_remembered_tree_runs_nothing(tmp_path):
    """A second done on the same tree says it passed and runs no tier."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    (repo / "calls.log").unlink()
    out = just(repo, "done", env=env)
    assert "already passed" in out
    assert calls(repo) == []


def test_a_markdown_change_keeps_the_tree_checkable(tmp_path):
    """An edited or new Markdown file leaves the checkable tree as HEAD's."""
    repo, env = make_repo(tmp_path)
    (repo / "notes.md").write_text("new\n")
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    assert just(repo, "checkable-tree", env=env) == tree


def test_a_dirty_tree_is_not_remembered(tmp_path):
    """An untracked Python file makes the tree uncheckable and not remembered."""
    repo, env = make_repo(tmp_path)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "x.py").write_text("x = 1\n")
    assert just(repo, "checkable-tree", env=env) == ""
    assert "Not remembered" in just(repo, "remember-tree", tree, env=env)
    assert passed(repo, env) == []


def test_a_commit_during_the_checks_is_not_remembered(tmp_path):
    """A tree that stopped being HEAD's tree while the checks ran is refused."""
    repo, env = make_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "a.py").write_text("a = 2\n")
    git(repo, "commit", "-am", "fix: change", env=env)
    assert "Not remembered" in just(repo, "remember-tree", before, env=env)
    assert passed(repo, env) == []


def test_a_fast_forward_to_a_passed_tree_runs_nothing(tmp_path):
    """A branch that passed done, merged by fast-forward or --no-ff, runs nothing."""
    for flags in (["--ff-only"], ["--no-ff", "-m", "merge"]):
        repo, env = make_repo(tmp_path / flags[0].strip("-"))
        git(repo, "switch", "-c", "work", env=env)
        (repo / "a.py").write_text("a = 2\n")
        git(repo, "commit", "-am", "feat: change", env=env)
        just(repo, "done", env=env)
        git(repo, "switch", "main", env=env)
        git(repo, "merge", *flags, "work", env=env)
        (repo / "calls.log").unlink()
        assert "already passed" in just(repo, "done", env=env)
        assert calls(repo) == []


def test_a_rewritten_results_file_keeps_the_tree_checkable(tmp_path):
    """done remembers the tree when the checks rewrote only their own outputs."""
    repo, env = make_repo(tmp_path)
    (repo / "validation" / "sqlearn").mkdir(parents=True)
    for name in ("sqlearn/x.results.json", "tests.json", "environment.json"):
        (repo / "validation" / name).write_text("{}\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: outputs", env=env)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "justfile").write_text(
        OVERRIDES.replace(
            "@echo validate >> calls.log",
            "@echo validate >> calls.log\n"
            "    @echo '{\"n\": 1}' > validation/sqlearn/x.results.json\n"
            "    @echo '{\"n\": 1}' > validation/tests.json\n"
            "    @echo '{\"n\": 1}' > validation/environment.json\n"
            "    @echo '{}' > validation/sqlearn/new.results.json",
        )
    )
    git(repo, "commit", "-qam", "chore: rewrite", env=env)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    just(repo, "done", env=env)
    assert passed(repo, env) == [tree]
