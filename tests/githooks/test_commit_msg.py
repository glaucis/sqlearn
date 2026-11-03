"""Tests of .githooks/commit-msg: real commits in scratch repositories."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "commit-msg"
RULES = REPO / "commitlint.config.mjs"

needs_commitlint = pytest.mark.skipif(
    shutil.which("commitlint") is None,
    reason="commitlint is not installed: brew install commitlint",
)

REFUSED = "does not follow the commit conventions"


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
    """Build a scratch repository with the hook, the rules and one commit."""
    repo = base / "repo"
    repo.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    ambient = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "UV_"))}
    env = {**ambient, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    git(repo, "init", "-b", "main", env=env)
    git(repo, "config", "user.name", "Test", env=env)
    git(repo, "config", "user.email", "test@example.com", env=env)
    git(repo, "config", "commit.gpgsign", "false", env=env)
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks" / "commit-msg")
    (repo / ".githooks" / "commit-msg").chmod(0o755)
    shutil.copy(RULES, repo / "commitlint.config.mjs")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-m", "chore: start", env=env)
    git(repo, "config", "core.hooksPath", ".githooks", env=env)
    return repo, env


@pytest.fixture
def scratch(tmp_path):
    """A scratch repository: (path, env)."""
    return make_repo(tmp_path, tmp_path)


def head(repo, env):
    """Return the commit HEAD names."""
    return git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


def commit(repo, env, message, *extra, cwd=None):
    """Change a.txt, stage it and try to commit it with the message."""
    with (repo / "a.txt").open("a") as handle:
        handle.write("more\n")
    git(repo, "add", "a.txt", env=env)
    return git(cwd or repo, "commit", *extra, "-m", message, env=env, check=False)


@needs_commitlint
def test_a_good_message_lands(scratch):
    """A conforming message lands."""
    repo, env = scratch
    done = commit(repo, env, "docs: clarify the setup steps")
    assert done.returncode == 0, done.stderr


@needs_commitlint
@pytest.mark.parametrize(
    "message",
    [
        "Updated stuff.",
        "feat: add x.",
        "FEAT: add x",
        "feat(Auth): add x",
        "feat: " + "x" * 67,
        "wip: add x",
    ],
)
def test_a_rule_at_level_two_refuses(scratch, message):
    """Each level-2 rule refuses the commit and says so."""
    repo, env = scratch
    before = head(repo, env)
    done = commit(repo, env, message)
    assert done.returncode != 0
    assert head(repo, env) == before
    assert REFUSED in done.stderr


@needs_commitlint
@pytest.mark.parametrize(
    ("message", "rule"),
    [
        (" feat: add x", "header-trim"),
        ("feat: add x ", "header-trim"),
        ("feat(" + "s" * 25 + "): add x", "scope-max-length"),
        ("feat: add x\nBody directly under the header.\n", "body-leading-blank"),
    ],
)
def test_a_rule_refuses_and_is_named(scratch, tmp_path, message, rule):
    """A verbatim message that breaks one rule is refused, and the rule is named."""
    repo, env = scratch
    before = head(repo, env)
    with (repo / "a.txt").open("a") as handle:
        handle.write("more\n")
    git(repo, "add", "a.txt", env=env)
    file = tmp_path / "message.txt"
    file.write_text(message)
    done = git(
        repo, "commit", "-F", str(file), "--cleanup=verbatim", env=env, check=False
    )
    assert done.returncode != 0
    assert head(repo, env) == before
    assert REFUSED in done.stderr
    assert rule in done.stderr


@needs_commitlint
def test_a_warning_lets_the_commit_land(scratch):
    """A warning is shown and the commit lands."""
    repo, env = scratch
    done = commit(repo, env, "feat: Add x")
    assert done.returncode == 0, done.stderr
    assert "warning never refuses" in done.stderr


@needs_commitlint
def test_a_breaking_change_needs_its_footer(scratch):
    """A `!` in the header needs the BREAKING CHANGE footer."""
    repo, env = scratch
    before = head(repo, env)
    done = commit(repo, env, "feat!: drop x")
    assert done.returncode != 0
    assert head(repo, env) == before
    message = "feat!: drop x\n\nThe old call is removed.\n\nBREAKING CHANGE: x is gone"
    done = commit(repo, env, message)
    assert done.returncode == 0, done.stderr


@needs_commitlint
def test_an_empty_message_is_refused(scratch):
    """An empty message is refused by the hook itself."""
    repo, env = scratch
    before = head(repo, env)
    done = commit(repo, env, "", "--allow-empty-message")
    assert done.returncode != 0
    assert head(repo, env) == before
    assert "the commit message is empty" in done.stderr


@needs_commitlint
def test_a_merge_with_gits_own_message_lands(scratch):
    """A merge keeps git's own message, which is not `type: subject`."""
    repo, env = scratch
    git(repo, "switch", "-c", "side", env=env)
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt", env=env)
    git(repo, "commit", "-m", "feat: add b", env=env)
    git(repo, "switch", "main", env=env)
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "c.txt", env=env)
    git(repo, "commit", "-m", "feat: add c", env=env)
    done = git(repo, "merge", "--no-edit", "side", env=env, check=False)
    assert done.returncode == 0, done.stderr
    subject = git(repo, "log", "-1", "--format=%s", env=env).stdout.strip()
    assert subject.startswith("Merge branch")


def scissors_message(path, char):
    """Write a valid subject, comment lines and a scissors section that would refuse."""
    path.write_text(
        "feat: add the thing\n"
        "\n"
        f"{char} Please enter the commit message.\n"
        f"{char} ------------------------ >8 ------------------------\n"
        f"{char} Do not modify or remove the line above.\n"
        "diff --git a/a.txt b/a.txt\n"
        "BREAKING CHANGE: x is gone\n"
    )


@needs_commitlint
def test_the_scissors_section_is_ignored(scratch, tmp_path):
    """Comment lines and a scissors section below the subject are not checked."""
    repo, env = scratch
    (repo / "a.txt").write_text("changed\n")
    git(repo, "add", "a.txt", env=env)
    message = tmp_path / "message.txt"
    scissors_message(message, "#")
    done = git(
        repo, "commit", "-F", str(message), "--cleanup=scissors", env=env, check=False
    )
    assert done.returncode == 0, done.stderr


@needs_commitlint
def test_a_subject_starting_with_the_comment_character_is_refused(scratch):
    """A subject git would keep but the hook would strip is refused."""
    repo, env = scratch
    before = head(repo, env)
    (repo / "a.txt").write_text("changed\n")
    git(repo, "add", "a.txt", env=env)
    done = git(
        repo,
        "commit",
        "-m",
        "# Updated stuff.",
        "-m",
        "docs: fine",
        env=env,
        check=False,
    )
    assert done.returncode != 0
    assert head(repo, env) == before
    assert "may not start with '#'" in done.stderr


@needs_commitlint
def test_the_comment_character_follows_core_commentchar(scratch, tmp_path):
    """With core.commentChar set, its scissors section is the one ignored."""
    repo, env = scratch
    git(repo, "config", "core.commentChar", ";", env=env)
    (repo / "a.txt").write_text("changed\n")
    git(repo, "add", "a.txt", env=env)
    message = tmp_path / "message.txt"
    scissors_message(message, ";")
    done = git(
        repo, "commit", "-F", str(message), "--cleanup=scissors", env=env, check=False
    )
    assert done.returncode == 0, done.stderr


@needs_commitlint
def test_a_commit_from_a_subfolder_finds_the_rules(scratch):
    """A commit typed in a subfolder still finds the rules."""
    repo, env = scratch
    (repo / "sub").mkdir()
    done = commit(repo, env, "docs: from a subfolder", cwd=repo / "sub")
    assert done.returncode == 0, done.stderr
    done = commit(repo, env, "Updated stuff.", cwd=repo / "sub")
    assert done.returncode != 0
    assert REFUSED in done.stderr


@needs_commitlint
def test_the_hook_runs_under_a_path_with_spaces(tmp_path):
    """The hook copes with spaces and non-ASCII characters in the path."""
    repo, env = make_repo(tmp_path / "with space \u2019\u00e9", tmp_path)
    done = commit(repo, env, "docs: a good message")
    assert done.returncode == 0, done.stderr
    done = commit(repo, env, "Updated stuff.")
    assert done.returncode != 0
    assert REFUSED in done.stderr


@needs_commitlint
def test_the_hook_runs_in_a_linked_worktree(scratch, tmp_path):
    """In a linked worktree a bad message is refused."""
    repo, env = scratch
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-b", "side", str(linked), env=env)
    (linked / "a.txt").write_text("side\n")
    git(linked, "add", "a.txt", env=env)
    done = git(linked, "commit", "-m", "Updated stuff.", env=env, check=False)
    assert done.returncode != 0
    assert REFUSED in done.stderr
    done = git(linked, "commit", "-m", "docs: side", env=env, check=False)
    assert done.returncode == 0, done.stderr


def test_no_commitlint_refuses_with_the_cure(scratch, tmp_path):
    """Without commitlint the commit is refused and the cure is printed."""
    repo, env = scratch
    bare = tmp_path / "bare"
    bare.mkdir()
    for tool in (
        "git",
        "bash",
        "env",
        "mktemp",
        "rm",
        "cat",
        "dirname",
        "sed",
        "grep",
        "sh",
    ):
        found = shutil.which(tool)
        assert found is not None, tool
        (bare / tool).symlink_to(found)
    before = head(repo, env)
    (repo / "a.txt").write_text("changed\n")
    git(repo, "add", "a.txt", env=env)
    done = git(
        repo,
        "commit",
        "-m",
        "docs: fine",
        env={**env, "PATH": str(bare)},
        check=False,
    )
    assert done.returncode != 0
    assert head(repo, env) == before
    assert "brew install commitlint" in done.stderr
    assert "has not been looked at" in done.stderr


@needs_commitlint
def test_missing_rules_refuse(scratch):
    """A missing rules file refuses the commit and names the path."""
    repo, env = scratch
    (repo / "commitlint.config.mjs").unlink()
    done = commit(repo, env, "docs: fine")
    assert done.returncode != 0
    assert str(repo.resolve() / "commitlint.config.mjs") in done.stderr


@needs_commitlint
def test_rules_that_fail_to_load_are_a_tooling_failure(scratch):
    """Rules that do not load are reported as a tooling failure."""
    repo, env = scratch
    (repo / "commitlint.config.mjs").write_text("export default {")
    done = commit(repo, env, "docs: fine")
    assert done.returncode != 0
    assert "could not check this message" in done.stderr
    assert "Rewording it will not help" in done.stderr


@needs_commitlint
def test_empty_rules_are_a_tooling_failure(scratch):
    """A rules file with no rules is a tooling failure, not a bad message."""
    repo, env = scratch
    (repo / "commitlint.config.mjs").write_text("export default { rules: {} };\n")
    done = commit(repo, env, "docs: fine")
    assert done.returncode != 0
    assert "could not check this message" in done.stderr
    assert REFUSED not in done.stderr


def test_the_hook_is_committed_executable():
    """The hook is committed with the executable bit, or git silently skips it."""
    done = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/commit-msg"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    assert done.stdout.startswith("100755")
