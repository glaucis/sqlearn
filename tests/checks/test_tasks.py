"""Tests of the task recipes (``just lint``, ``just test``) in scratch repositories.

The real justfile is imported under stand-ins for ``build-docs``,
``validate-all`` and ``test-engine-changed`` (the C++ groups, tested on a
scratch engine in ``test_engine_groups.py``); the tools are
stand-ins on ``PATH`` that log their arguments, so no real check runs.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from validation import _checks, _groups

REPO = Path(__file__).resolve().parents[2]

OVERRIDES = """set allow-duplicate-recipes
import 'real.just'

build-docs:
    @echo '["build-docs"]' >> "$CALLS"

validate-all:
    @echo '["validate-all"]' >> "$CALLS"

test-engine-changed *args:
    @echo '["test-engine-changed {{ args }}"]' >> "$CALLS"

test-sql *args:
    @echo '["test-sql {{ args }}"]' >> "$CALLS"

check-docstring-args *files:
    @echo '["check-docstring-args"]' >> "$CALLS"
"""

TOOL = """#!{python}
import json, os, sys
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
"""

NINJA = """#!/bin/sh
# Called as: ninja -C <build> -t commands _duckdb, or -t deps <object>.
[ "$4" = deps ] && exit 1
printf 'echo first\\n'
cat "$2/link.txt"
"""

FILES = {
    ".gitignore": "calls.log\nbuild/\n",
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
    "engine/extension/src/sqlearn_extension.cpp": "// the extension\n",
    "engine/extension/test/sql/sqlearn_version.test": "require sqlearn\n",
    "engine/src/core/version.cpp": "// core\n",
    "engine/sqllogic/CMakeLists.txt": "# the runner's build\n",
    "engine/cmake/sql_tests.cmake": "# a helper\n",
}


def build(repo):
    """Write the wheel's build of the scratch engine: group ``core``.

    ``sq_groups.json``, ``compile_commands.json`` naming the real compiler
    and ``link.txt``, which the ``ninja`` stand-in prints (git-ignored).
    """
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("c++ is needed: just doctor")
    out = repo / _groups.WHEEL_BUILD
    out.mkdir(parents=True)
    source = repo / "engine" / "src" / "core" / "version.cpp"
    manifest = {
        "groups": [
            {
                "name": "core",
                "dir": "engine/src/core",
                "depends": [],
                "python_tests": [],
                "validation": [],
                "bench": [],
            }
        ],
        "shared": ["engine/extension"],
    }
    (out / "sq_groups.json").write_text(json.dumps(manifest))
    argv = [compiler, "-std=c++23", "-o", "version.o", "-c", str(source)]
    entry = {
        "directory": str(out),
        "command": shlex.join(argv),
        "file": str(source),
        "output": str(out / "version.o"),
    }
    (out / "compile_commands.json").write_text(json.dumps([entry]))
    (out / "link.txt").write_text(f"{compiler} -bundle -o _duckdb.so version.o\n")


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
    (bin_dir / "ninja").write_text(NINJA)
    (bin_dir / "ninja").chmod(0o755)
    build(repo)
    for tool in ("ruff", "typos", "rumdl", "numpydoc", "ty", "mypy", "uv"):
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


SETS = ["uv", "run", "--locked", "python", "-m", "validation._pytest_sets"]
"""The Python tests' step: it keeps records of each set and decides itself."""


def test_a_docs_only_change_runs_no_test(scratch):
    """An edited guide page rebuilds the docs; the test task is unchanged, and
    only its two steps that keep records of their own run."""
    repo, env = scratch
    just(repo, env, "test")
    just(repo, env, "docs")
    assert calls(env) == [["test-engine-changed dev"], SETS, ["build-docs"]]
    (repo / "docs" / "guide" / "notes.md").write_text("# Notes, edited\n")
    assert "test: unchanged since a passed run" in just(repo, env, "test")
    assert calls(env) == [["test-engine-changed dev"], SETS]
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


def test_the_test_task_is_the_cxx_groups_then_the_python_sets():
    """Both steps keep records of their own, so both run every time."""
    steps = _checks.TASKS["test"].steps
    assert [s.command for s in steps] == [
        ("just", "test-engine-changed", "dev"),
        tuple(SETS),
    ]
    assert all(s.always and s.everything == ("--all",) for s in steps)


@pytest.mark.parametrize(
    "changed",
    [
        "engine/extension/src/sqlearn_extension.cpp",
        "engine/extension/test/sql/sqlearn_version.test",
        "engine/extension/test/sql/new.test",
        "engine/src/core/version.cpp",
        "engine/sqllogic/CMakeLists.txt",
        "engine/cmake/sql_tests.cmake",
    ],
)
def test_a_change_to_the_extension_reruns_its_sql_tests(scratch, changed):
    """``just sql`` runs the SQL tests once, skips them on a docs edit, and
    runs them again when the extension's or our C++ code, a .test file or the
    runner's build changed (a C++ comment alone does not: see below)."""
    repo, env = scratch
    just(repo, env, "sql")
    assert calls(env) == [["test-sql "]]
    (repo / "docs" / "guide" / "notes.md").write_text("# Notes, edited\n")
    assert "sql: unchanged since a passed run" in just(repo, env, "sql")
    assert calls(env) == []
    path = repo / changed
    added = "int changed;\n" if path.suffix == ".cpp" else "// changed\n"
    path.write_text((path.read_text() if path.exists() else "") + added)
    just(repo, env, "sql")
    assert calls(env) == [["test-sql "]]


def test_a_duckdb_bump_reruns_the_sql_tests(scratch):
    """A new commit of duckdb-python's gitlink, which pins DuckDB's, reruns
    ``just sql``."""
    repo, env = scratch

    def pin(commit):
        git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{commit},engine/duckdb-python",
            env=env,
        )

    pin("1" * 40)
    just(repo, env, "sql")
    assert calls(env) == [["test-sql "]]
    assert "sql: unchanged since a passed run" in just(repo, env, "sql")
    pin("2" * 40)
    just(repo, env, "sql")
    assert calls(env) == [["test-sql "]]


def _pin(repo, env, commit):
    """Pin duckdb-python's gitlink at `commit` in the scratch index."""
    git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{commit},engine/duckdb-python",
        env=env,
    )


@pytest.mark.parametrize(
    ("task", "first"),
    [("docs", "build-docs"), ("types", "ty"), ("docstrings", "numpydoc")],
)
def test_a_duckdb_bump_reruns_what_runs_on_the_engine(scratch, task, first):
    """The docs build runs its doctests on the built module and ty and mypy
    read its stubs; the docstring checks are keyed the same way. A new commit
    of duckdb-python's gitlink reruns each."""
    repo, env = scratch
    _pin(repo, env, "1" * 40)
    just(repo, env, task)
    assert calls(env)[0][0] == first
    assert f"{task}: unchanged since a passed run" in just(repo, env, task)
    assert calls(env) == []
    _pin(repo, env, "2" * 40)
    just(repo, env, task)
    assert calls(env)[0][0] == first


@pytest.mark.parametrize(
    ("task", "first"),
    [("docs", "build-docs"), ("types", "ty"), ("docstrings", "numpydoc")],
)
@pytest.mark.parametrize(
    "changed",
    [
        "engine/src/core/version.cpp",
        "engine/extension/src/sqlearn_extension.cpp",
    ],
)
def test_a_core_change_reruns_sql_and_docs(scratch, task, first, changed):
    """A code change in the engine rebuilds the module, so the checks that
    run on it run again; the SQL tests too (below)."""
    repo, env = scratch
    just(repo, env, task)
    calls(env)
    path = repo / changed
    path.write_text(path.read_text() + "int changed;\n")
    just(repo, env, task)
    assert calls(env)[0][0] == first


@pytest.mark.parametrize(
    ("task", "first"),
    [
        ("docs", "build-docs"),
        ("types", "ty"),
        ("docstrings", "numpydoc"),
        ("sql", "test-sql "),
    ],
)
@pytest.mark.parametrize(
    "changed",
    [
        "engine/src/core/version.cpp",
        "engine/extension/src/sqlearn_extension.cpp",
    ],
)
def test_a_cpp_comment_edit_keeps_the_docs_record(scratch, task, first, changed):
    """A comment edited within its line changes no fingerprint: the docs
    build, the type checks, the docstring checks and the SQL tests stay
    unchanged since a passed run."""
    repo, env = scratch
    just(repo, env, task)
    calls(env)
    path = repo / changed
    path.write_text(path.read_text().replace("//", "// edited"))
    assert f"{task}: unchanged since a passed run" in just(repo, env, task)
    assert calls(env) == []


@pytest.mark.parametrize("task", ["docs", "types", "docstrings"])
def test_a_cmake_text_edit_keeps_what_runs_on_the_module(scratch, task):
    """CMake text reaches the module only through what it makes the build do
    (the compile entries, the link command), so a comment there reruns
    none of them."""
    repo, env = scratch
    just(repo, env, task)
    calls(env)
    path = repo / "engine" / "cmake" / "sql_tests.cmake"
    path.write_text(path.read_text() + "# changed\n")
    assert f"{task}: unchanged since a passed run" in just(repo, env, task)


def test_a_cpp_comment_under_engine_src_keeps_the_sql_digest(scratch, monkeypatch):
    """``sql`` reads the C++ through the module's fingerprint: a comment
    changes no digest, a code change in ``core`` changes it."""
    repo, env = scratch
    monkeypatch.setenv("PATH", env["PATH"])
    sql = _checks.TASKS["sql"]
    before = _checks.digest(sql, repo)
    path = repo / "engine" / "src" / "core" / "version.cpp"
    path.write_text(path.read_text().replace("//", "// edited"))
    assert _checks.digest(sql, repo) == before
    path.write_text(path.read_text() + "int changed;\n")
    assert _checks.digest(sql, repo) != before


@pytest.mark.parametrize("task", ["docs", "types", "docstrings", "sql"])
def test_unreadable_fingerprints_rerun_the_task_and_record_nothing_matching(
    scratch, task
):
    """No manifest: the reason is printed and the task runs each time."""
    repo, env = scratch
    (repo / _groups.WHEEL_BUILD / "sq_groups.json").unlink()
    out = just(repo, env, task)
    assert "sq_groups.json" in out
    assert calls(env)
    assert f"{task}: unchanged" not in just(repo, env, task)
    assert calls(env)


def test_every_cache_key_under_engine_reaches_a_fingerprint():
    """pyproject's ``tool.uv.cache-keys`` under ``engine/`` is what uv
    rebuilds the module on. Each reaches a fingerprint: a group's directory
    or a shared one (the real manifest), or the CMake files, which reach it
    through the compile entries and the link command. The pins are the
    shared part's. The compiler stamp is a git-ignored file no digest can
    see: the tasks name the compiler as a tool instead."""
    import tomllib

    from validation import _groups

    keys = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["uv"][
        "cache-keys"
    ]
    paths = {
        k["file"].removesuffix("/**")
        for k in keys
        if "file" in k and k["file"].startswith("engine/")
    }
    paths.discard("engine/.compiler-stamp")
    groups, shared = _groups.load(REPO / _groups.WHEEL_BUILD)
    held = {g.dir for g in groups.values()} | set(shared)
    cmake = {"engine/CMakeLists.txt", "engine/cmake"}

    def reached(path):
        """Whether the fingerprint holds `path`: it is, or sits under, a
        group's or a shared directory, or every directory under it is."""
        if any(path == h or path.startswith(f"{h}/") for h in held):
            return True
        below = [h for h in held if h.startswith(f"{path}/")]
        subdirs = {
            d.relative_to(REPO).as_posix()
            for d in (REPO / path).iterdir()
            if d.is_dir() and any(d.rglob("*.[ch]pp"))
        }
        return bool(below) and subdirs <= held

    assert [p for p in paths - cmake if not reached(p)] == []
    assert cmake <= paths
    links = _checks._gitlinks(("engine",), REPO)
    assert links, "the engine pins its submodules"


def test_full_sql_runs_every_sql_test(scratch):
    """``just full sql`` hands ``test-sql`` its ``--all``."""
    repo, env = scratch
    just(repo, env, "full", "sql")
    assert calls(env) == [["test-sql --all"]]


def test_full_test_runs_every_cxx_group_and_python_set(scratch):
    """``just full test`` hands both steps ``--all``; ``just test`` does not."""
    repo, env = scratch
    just(repo, env, "test")
    just(repo, env, "full", "test")
    assert calls(env) == [
        ["test-engine-changed dev"],
        SETS,
        ["test-engine-changed dev --all"],
        [*SETS, "--all"],
    ]


def test_full_validate_runs_every_runner(scratch):
    """``just full validate`` is ``validate-all``, outside the task table."""
    repo, env = scratch
    just(repo, env, "full", "validate")
    assert calls(env) == [["validate-all"]]


def test_a_cpp_code_edit_while_a_check_runs_is_not_recorded(
    scratch, monkeypatch, capsys
):
    """A step that edits a core code line mid-run: the module moved, so the
    pass is not recorded and the next run runs again."""
    repo, env = scratch
    monkeypatch.setenv("PATH", env["PATH"])
    source = repo / "engine" / "src" / "core" / "version.cpp"
    edit = (
        f"import pathlib; p = pathlib.Path({str(source)!r}); "
        "p.write_text(p.read_text() + 'int moved;\\n')"
    )
    task = _checks.Task(
        name="moves",
        inputs=("docs",),
        config=(),
        steps=(_checks.Step((sys.executable, "-c", edit)),),
        per_file=False,
        module=None,
    )
    monkeypatch.setitem(_checks.TASKS, "moves", task)
    capsys.readouterr()
    assert _checks.run("moves", repo) == 0
    assert "moves: not recorded" in capsys.readouterr().out
    assert _checks.load(_checks.record_dir(repo), "moves") == []
