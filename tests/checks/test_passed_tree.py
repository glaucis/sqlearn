"""Tests of the recipes that remember the tree that passed, in scratch repositories."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# What done runs, in order: the instant checks, then every task.
RUNS = (
    "check-lockfile",
    "check-mirror",
    "check-no-devdata",
    "format",
    "lint",
    "docstrings",
    "types",
    "test",
    "validate",
    "docs",
)

# Stand-ins for what done runs; the real justfile is imported under them.
OVERRIDES = "set allow-duplicate-recipes\nimport 'real.just'\n" + "".join(
    f"\n{name}:\n    @echo {name} >> calls.log\n" for name in RUNS
)


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
    env = {
        **ambient,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        # checkable-tree reads the declared files from this repository's module.
        "PYTHONPATH": str(REPO),
        "SQLEARN_CHECKS": f"{sys.executable} -m validation._checks",
    }
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
    """done runs the instant checks, then every task, then remembers."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    assert calls(repo) == list(RUNS)
    assert passed(repo, env) == [git(repo, "rev-parse", "HEAD^{tree}", env=env)]


def test_a_failing_check_remembers_nothing(tmp_path):
    """done stops at the first failing task and leaves the record as it was."""
    repo, env = make_repo(tmp_path)
    (repo / "justfile").write_text(
        OVERRIDES.replace(
            "@echo lint >> calls.log", "@echo lint >> calls.log\n    @exit 1"
        )
    )
    git(repo, "commit", "-qam", "chore: failing check", env=env)
    failed = subprocess.run(
        ["just", "done"], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert failed.returncode != 0
    assert calls(repo) == [
        "check-lockfile",
        "check-mirror",
        "check-no-devdata",
        "format",
        "lint",
    ]
    assert passed(repo, env) == []


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


def test_an_edited_declared_markdown_file_makes_the_tree_uncheckable(tmp_path):
    """A Markdown file a test reads as data is an input, so it must be committed."""
    repo, env = make_repo(tmp_path)
    inventory = repo / "docs" / "architecture" / "engine-inventory.md"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("| `a.py` | 2 |\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "docs: inventory", env=env)
    inventory.write_text("| `a.py` | 3 |\n")
    assert just(repo, "checkable-tree", env=env) == ""


def test_a_new_declared_markdown_file_makes_the_tree_uncheckable(tmp_path):
    """An untracked declared Markdown file differs from HEAD like any input."""
    repo, env = make_repo(tmp_path)
    inventory = repo / "docs" / "architecture" / "engine-inventory.md"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("| `a.py` | 2 |\n")
    assert just(repo, "checkable-tree", env=env) == ""


def test_an_edited_markdown_file_the_tests_read_makes_the_tree_uncheckable(tmp_path):
    """A Markdown file under tests/, an input of the test task, must be committed."""
    repo, env = make_repo(tmp_path)
    notes = repo / "tests" / "notes.md"
    notes.parent.mkdir()
    notes.write_text("one\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "docs: notes", env=env)
    notes.write_text("two\n")
    assert just(repo, "checkable-tree", env=env) == ""


def test_a_failing_list_of_declared_files_is_not_a_checkable_tree(tmp_path):
    """When the declared files cannot be listed, checkable-tree fails, never prints."""
    repo, env = make_repo(tmp_path)
    env = {**env, "SQLEARN_CHECKS": "false"}
    done = subprocess.run(
        ["just", "checkable-tree"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert done.stdout == ""


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
