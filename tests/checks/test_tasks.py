"""Tests of the task recipes (``just lint``, ``just test``) in scratch repositories.

The real justfile is imported under stand-ins for ``build-docs``,
``validate-all`` and ``test-engine-changed`` (the C++ groups, tested on a
scratch engine in ``test_engine_groups.py``); the tools are
stand-ins on ``PATH`` that log their arguments, so no real check runs.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

OVERRIDES = """set allow-duplicate-recipes
import 'real.just'

build-docs:
    @echo '["build-docs"]' >> "$CALLS"

validate-all:
    @echo '["validate-all"]' >> "$CALLS"

test-engine-changed *args:
    @echo '["test-engine-changed {{ args }}"]' >> "$CALLS"
"""

TOOL = """#!{python}
import json, os, sys
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
"""

FILES = {
    ".gitignore": "calls.log\n",
    ".python-version": "3.12\n",
    "pyproject.toml": "[project]\nname = 'scratch'\n",
    "uv.lock": "lock\n",
    "commitlint.config.mjs": "export default {};\n",
    ".githooks/pre-commit": "#!/bin/sh\n",
    "src/sqlearn/a.py": "a = 1\n",
    "src/sqlearn/b.py": "b = 2\n",
    "tests/test_a.py": "def test_a():\n    pass\n",
    "devdata/data/iris.csv": "x\n1\n",
    "docs/guide/notes.md": "# Notes\n",
    "docs/conf.py": "project = 'scratch'\n",
    "docs/architecture/engine-inventory.md": "| `a.py` | 1 |\n",
}


def git(cwd, *args, env):
    """Run git in cwd."""
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


@pytest.fixture
def scratch(tmp_path):
    """A committed scratch repository, its environment, and its tools' log."""
    repo = tmp_path / "repo"
    for name, text in FILES.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    shutil.copy(REPO / "justfile", repo / "real.just")
    (repo / "justfile").write_text(OVERRIDES)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("ruff", "typos", "rumdl", "numpydoc", "ty", "mypy", "pytest"):
        (bin_dir / tool).write_text(TOOL.format(python=sys.executable))
        (bin_dir / tool).chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    ambient = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env = {
        **ambient,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": f"{bin_dir}{os.pathsep}{ambient['PATH']}",
        "PYTHONPATH": str(REPO),
        "CALLS": str(tmp_path / "calls.log"),
    }
    git(repo, "init", "-b", "main", env=env)
    git(repo, "add", "-A", env=env)
    who = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(repo, *who, "commit", "-qm", "start", env=env)
    return repo, env


def just(repo, env, *args):
    """Run just in the scratch repository, the helper from this environment."""
    checks = f"{sys.executable} -m validation._checks"
    done = subprocess.run(
        ["just", "--set", "checks", checks, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def calls(env):
    """Return and forget the tools' calls since the last look, argv each."""
    log = Path(env["CALLS"])
    if not log.exists():
        return []
    lines = log.read_text().splitlines()
    log.unlink()
    return [json.loads(line) for line in lines]


def test_a_docs_only_change_runs_no_test(scratch):
    """An edited guide page rebuilds the docs and runs no test."""
    repo, env = scratch
    just(repo, env, "test")
    just(repo, env, "docs")
    assert [c[0] for c in calls(env)] == [
        "test-engine-changed dev",
        *["pytest"] * 4,
        "build-docs",
    ]
    (repo / "docs" / "guide" / "notes.md").write_text("# Notes, edited\n")
    assert "test: unchanged since a passed run" in just(repo, env, "test")
    # The C++ step keeps records of its own and decides for itself.
    assert calls(env) == [["test-engine-changed dev"]]
    just(repo, env, "docs")
    assert calls(env) == [["build-docs"]]


def test_a_change_to_one_python_file_lints_only_that_file(scratch):
    """One edited module: each lint tool that takes Python checks it alone."""
    repo, env = scratch
    just(repo, env, "lint")
    just(repo, env, "format")
    first = calls(env)
    assert [c[:3] for c in first] == [
        ["ruff", "check", "--force-exclude"],
        ["typos", "--force-exclude", ".githooks/pre-commit"],
        ["rumdl", "check", "docs/architecture/engine-inventory.md"],
        ["ruff", "format", "--check"],
        ["rumdl", "fmt", "--check"],
    ]
    assert {"src/sqlearn/a.py", "src/sqlearn/b.py"} <= set(first[0])
    (repo / "src" / "sqlearn" / "a.py").write_text("a = 10\n")
    just(repo, env, "lint")
    just(repo, env, "format")
    assert calls(env) == [
        ["ruff", "check", "--force-exclude", "src/sqlearn/a.py"],
        ["typos", "--force-exclude", "src/sqlearn/a.py"],
        ["ruff", "format", "--check", "--force-exclude", "src/sqlearn/a.py"],
    ]


@pytest.mark.parametrize(
    "data",
    [
        "devdata/data/iris.csv",
        "docs/architecture/engine-inventory.md",
        "docs/conf.py",
        ".githooks/pre-commit",
        "commitlint.config.mjs",
        "tests/conftest.py",
    ],
)
def test_a_data_file_change_reruns_the_tests(scratch, data):
    """A file the tests read as data, changed or new, reruns every test pass."""
    repo, env = scratch
    just(repo, env, "test")
    calls(env)
    path = repo / data
    path.write_text((path.read_text() if path.exists() else "") + "# changed\n")
    just(repo, env, "test")
    passes = [
        ["-n", "auto", "-m", "not slow and not serial", "--ignore=tests/githooks"],
        ["-p", "no:xdist", "-m", "serial and not slow", "--ignore=tests/githooks"],
        ["-p", "no:xdist", "-m", "slow", "--ignore=tests/githooks"],
        ["-n", "auto", "-m", "", "tests/githooks"],
    ]
    report = ["pytest", "-p", "validation._tests_report"]
    assert calls(env) == [
        ["test-engine-changed dev"],
        *([*report, *p] for p in passes),
    ]


def test_full_test_runs_every_cxx_group(scratch):
    """``just full test`` hands the C++ step ``--all``; ``just test`` does not."""
    repo, env = scratch
    just(repo, env, "test")
    just(repo, env, "full", "test")
    groups = [c for c in calls(env) if c[0].startswith("test-engine-changed")]
    assert groups == [["test-engine-changed dev"], ["test-engine-changed dev --all"]]


def test_full_validate_runs_every_runner(scratch):
    """``just full validate`` is ``validate-all``, outside the task table."""
    repo, env = scratch
    just(repo, env, "full", "validate")
    assert calls(env) == [["validate-all"]]
