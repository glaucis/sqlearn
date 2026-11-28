"""Tests of the recipes that remember the tree that passed, in scratch repositories."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# What done runs, in order: the instant checks, then every task.
RUNS = (
    "check-lockfile",
    "check-no-devdata",
    "format",
    "lint",
    "links",
    "docstrings",
    "types",
    "tidy",
    "test",
    "sql",
    "validate",
    "docs",
)

# What verify runs after the instant checks: every task in full, then the
# C++ tools of the release tier and the tests on every Python.
TASKS = (
    "format",
    "lint",
    "links",
    "docstrings",
    "types",
    "tidy",
    "test",
    "sql",
    "validate",
    "docs",
)
RELEASE = (
    "audit-groups",
    "sanitize",
    "leaks-engine",
    "fuzz-60",
    "coverage-engine",
    "mutate-engine",
    "check-licences",
    "test-all",
    "test-python-versions",
)

# Stand-ins for what done runs; the real justfile is imported under them. The
# place the checks run in is the file `place`, or "here" without one.
OVERRIDES = (
    "set allow-duplicate-recipes\nimport 'real.just'\n"
    + "".join(f"\n{name}:\n    @echo {name} >> calls.log\n" for name in RUNS)
    + "\nplace:\n    @cat place 2>/dev/null || echo here\n"
    # The stamp is git-ignored in the real tree; here it would dirty it.
    + "\ncompiler-stamp:\n    @true\n"
    # The sweep's warning, on stdout only: calls.log stays what runs.
    + "\nsweep-stale:\n    @echo sweep-warning\n"
    + "\nfull task:\n    @echo full-{{ task }} >> calls.log\n"
    + "\nfuzz seconds:\n    @echo fuzz-{{ seconds }} >> calls.log\n"
    + "".join(
        f"\n{name}:\n    @echo {name} >> calls.log\n"
        for name in RELEASE
        if name != "fuzz-60"
    )
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
    env = {**ambient, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    shutil.copy(REPO / "justfile", repo / "real.just")
    (repo / "justfile").write_text(OVERRIDES)
    (repo / ".gitignore").write_text("calls.log\nplace\n")
    (repo / "a.py").write_text("a = 1\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    return repo, env


def calls(repo):
    """Return the stand-in tiers that have run, in order."""
    log = repo / "calls.log"
    return log.read_text().split() if log.exists() else []


def remembered(repo, env):
    """Return the (tree, place) pairs remembered for the scratch repository."""
    common = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env)
    )
    file = common / "sqlearn-passed"
    lines = file.read_text().splitlines() if file.exists() else []
    return [tuple(line.split(" ", 1)) for line in lines]


def passed(repo, env):
    """Return the trees remembered for the scratch repository."""
    return [tree for tree, _ in remembered(repo, env)]


def test_a_clean_tree_that_passed_is_remembered(tmp_path):
    """done runs the instant checks, then every task, then remembers."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    assert calls(repo) == list(RUNS)
    assert passed(repo, env) == [git(repo, "rev-parse", "HEAD^{tree}", env=env)]


def test_a_failing_check_remembers_nothing(tmp_path):
    """done runs every task past a failure, exits with the first one's code, and
    leaves the record as it was, so one task's failure hides no other's findings."""
    repo, env = make_repo(tmp_path)
    (repo / "justfile").write_text(
        OVERRIDES.replace(
            "@echo lint >> calls.log", "@echo lint >> calls.log\n    @exit 3"
        ).replace("@echo docs >> calls.log", "@echo docs >> calls.log\n    @exit 4")
    )
    git(repo, "commit", "-qam", "chore: failing check", env=env)
    failed = subprocess.run(
        ["just", "done"], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert failed.returncode == 3
    assert calls(repo) == list(RUNS)
    assert passed(repo, env) == []


def test_a_remembered_tree_runs_nothing(tmp_path):
    """A second done on the same tree says it passed and runs no tier."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    (repo / "calls.log").unlink()
    out = just(repo, "done", env=env)
    assert "already passed" in out
    assert calls(repo) == []


def test_a_passed_tree_in_a_new_place_runs_everything(tmp_path):
    """The same tree on another Python, platform or machine runs every check
    again, and both places are remembered."""
    repo, env = make_repo(tmp_path)
    just(repo, "done", env=env)
    (repo / "calls.log").unlink()
    (repo / "place").write_text("elsewhere\n")
    out = just(repo, "done", env=env)
    assert "already passed" not in out
    assert calls(repo) == list(RUNS)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    assert remembered(repo, env) == [(tree, "here"), (tree, "elsewhere")]
    (repo / "calls.log").unlink()
    assert "already passed" in just(repo, "done", env=env)
    assert calls(repo) == []


def test_a_place_changed_while_the_checks_ran_is_not_remembered(tmp_path):
    """A tree is remembered only for the place it was checked in."""
    repo, env = make_repo(tmp_path)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "place").write_text("elsewhere\n")
    assert "Not remembered" in just(repo, "remember-tree", tree, "here", env=env)
    assert passed(repo, env) == []


def test_an_uncommitted_markdown_file_makes_the_tree_uncheckable(tmp_path):
    """Markdown is an input of format, lint and docs: edited or new, it must be
    committed before a tree can be remembered."""
    repo, env = make_repo(tmp_path)
    notes = repo / "docs" / "notes.md"
    notes.parent.mkdir()
    notes.write_text("one\n")
    assert just(repo, "checkable-tree", env=env) == ""
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "docs: notes", env=env)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    assert just(repo, "checkable-tree", env=env) == tree
    notes.write_text("two\n")
    assert just(repo, "checkable-tree", env=env) == ""


def test_a_dirty_tree_is_not_remembered(tmp_path):
    """An untracked Python file makes the tree uncheckable and not remembered."""
    repo, env = make_repo(tmp_path)
    tree = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "x.py").write_text("x = 1\n")
    assert just(repo, "checkable-tree", env=env) == ""
    assert "Not remembered" in just(repo, "remember-tree", tree, "here", env=env)
    assert passed(repo, env) == []


def test_a_commit_during_the_checks_is_not_remembered(tmp_path):
    """A tree that stopped being HEAD's tree while the checks ran is refused."""
    repo, env = make_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD^{tree}", env=env)
    (repo / "a.py").write_text("a = 2\n")
    git(repo, "commit", "-am", "fix: change", env=env)
    assert "Not remembered" in just(repo, "remember-tree", before, "here", env=env)
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


def test_verify_runs_every_task_in_full_and_the_release_tools(tmp_path):
    """verify runs the instant checks, every task in full (tidy and sql among
    them), then the audit of the groups' claims, the sanitizers, the leak
    check of the release build, a minute of fuzzing, coverage, mutation
    testing, the licence check and the tests on every Python, and remembers.
    The steady-memory test runs in ``full test``'s slow tier."""
    repo, env = make_repo(tmp_path)
    just(repo, "verify", env=env)
    assert calls(repo) == [
        "check-lockfile",
        "check-no-devdata",
        *(f"full-{task}" for task in TASKS),
        *RELEASE,
    ]
    assert passed(repo, env) == [git(repo, "rev-parse", "HEAD^{tree}", env=env)]


def test_done_warns_of_an_old_sweep_first_even_on_a_passed_tree(tmp_path):
    """The sweep's warning comes before anything else, the shortcut included."""
    repo, env = make_repo(tmp_path)
    assert just(repo, "done", env=env).startswith("sweep-warning")
    again = just(repo, "done", env=env).splitlines()
    assert again[0] == "sweep-warning"
    assert "already passed" in again[1]


def test_a_failing_sweep_warning_changes_nothing_done_runs(tmp_path):
    """A warning that fails stops no check and leaves the exit code as it was."""
    repo, env = make_repo(tmp_path)
    (repo / "justfile").write_text(
        OVERRIDES.replace("@echo sweep-warning", "@echo sweep-warning\n    @exit 5")
    )
    git(repo, "commit", "-qam", "chore: failing warning", env=env)
    just(repo, "done", env=env)
    assert calls(repo) == list(RUNS)
    assert len(passed(repo, env)) == 1
