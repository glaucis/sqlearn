"""Tests of the recipes that pick the tests a change affects, on scratch projects."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JUSTFILE = REPO / "justfile"
NO_TESTS_RAN = 0  # pytest exits 5, which the recipe counts as success


def just(*args):
    """Run just on the repository's justfile and return its stdout."""
    done = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def make_project(root):
    """Write the scratch project: two modules and their tests in tests/, a conftest."""
    tests = root / "tests"
    tests.mkdir()
    (tests / "a.py").write_text("def one():\n    return 1\n")
    (tests / "b.py").write_text("def two():\n    return 2\n")
    (tests / "test_a.py").write_text(
        "from a import one\n\n\ndef test_a():\n    assert one() >= 1\n"
    )
    (tests / "test_b.py").write_text(
        "from b import two\n\n\ndef test_b():\n    assert two() == 2\n"
    )
    (root / "conftest.py").write_text("")
    (root / "uv.lock").write_text("lock\n")
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    slow: slow\n    serial: serial\n"
    )


def run_affected(root, recipe="test"):
    """Run the recipe on the scratch project, pytest from this environment."""
    return subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "--working-directory",
            str(root),
            "--set",
            "pytest",
            f"{sys.executable} -m pytest -p no:cacheprovider",
            "--set",
            "report",
            "",
            recipe,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def first_run(root):
    """Run the scratch project once, so testmon's data holds every test."""
    first = run_affected(root)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "2 passed" in first.stdout


@pytest.fixture
def project(tmp_path):
    """A scratch project whose first run has already filled testmon's data."""
    make_project(tmp_path)
    first_run(tmp_path)
    return tmp_path


def test_a_one_line_change_reruns_only_its_tests(project):
    """Editing a.py must rerun a's test and leave b's alone, or the saving is lost."""
    (project / "tests" / "a.py").write_text("def one():\n    return 1 + 0\n")
    second = run_affected(project)
    assert "1 passed" in second.stdout, second.stdout


def test_nothing_changed_runs_nothing_and_succeeds(project):
    """With no change nothing is selected and the run still succeeds."""
    second = run_affected(project)
    assert second.returncode == NO_TESTS_RAN, second.stdout
    assert "no tests ran" in second.stdout


def test_a_markdown_change_runs_nothing(project):
    """A new README.md is not code, so it must not rerun any test."""
    (project / "README.md").write_text("# notes\n")
    second = run_affected(project)
    assert second.returncode == NO_TESTS_RAN, second.stdout
    assert "no tests ran" in second.stdout


@pytest.mark.parametrize(
    "declared",
    [
        "uv.lock",
        "conftest.py",
        "devdata/data/table.csv",
        "docs/architecture/engine-inventory.md",
        ".githooks/pre-commit",
        "commitlint.config.mjs",
    ],
)
def test_a_declared_dependency_reruns_every_test(project, declared):
    """A change to a declared file must change test-env and rerun every test."""
    before = just("test-env", str(project))
    path = project / declared
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.read_text() + "# changed\n" if path.exists() else "x\n")
    assert just("test-env", str(project)) != before
    second = run_affected(project)
    assert "2 passed" in second.stdout, second.stdout


def test_test_env_is_the_same_twice(tmp_path):
    """The digest must be stable, or every run would count as a change."""
    make_project(tmp_path)
    first = just("test-env", str(tmp_path))
    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert just("test-env", str(tmp_path)) == first


def test_a_new_empty_conftest_changes_test_env(tmp_path):
    """An empty conftest.py adds no bytes, so its path must be hashed."""
    make_project(tmp_path)
    before = just("test-env", str(tmp_path))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "conftest.py").write_text("")
    assert just("test-env", str(tmp_path)) != before


def test_testmon_ignores_sqlearns_own_version():
    """Each commit changes sqlearn's version, so testmon must ignore it or rerun all."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    ignored = config["tool"]["pytest"]["ini_options"]["testmon_ignore_dependencies"]
    assert {"sqlearn", "pytest-testmon"} <= set(ignored)


def test_a_module_level_constant_change_reruns_every_test(tmp_path):
    """A constant read through a function in another file runs at import, unseen."""
    make_project(tmp_path)
    tests = tmp_path / "tests"
    (tests / "consts.py").write_text("X = 1\n")
    (tests / "a.py").write_text("import consts\n\n\ndef one():\n    return consts.X\n")
    first_run(tmp_path)
    (tests / "consts.py").write_text("X = 2\n")
    second = run_affected(tmp_path)
    assert "2 passed" in second.stdout, second.stdout


def test_a_new_module_reruns_every_test(project):
    """A new module can hold what a test scans for, so it reruns every test."""
    (project / "tests" / "c.py").write_text("X = 3\n")
    second = run_affected(project)
    assert "2 passed" in second.stdout, second.stdout


def test_a_moved_re_export_reruns_every_test(tmp_path):
    """An __init__ re-exporting a name from another module is import-time code."""
    make_project(tmp_path)
    pkg = tmp_path / "tests" / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from pkg._old import f\n")
    (pkg / "_old.py").write_text("def f():\n    return 1\n")
    (pkg / "_new.py").write_text("def f():\n    return 1\n")
    (tmp_path / "tests" / "a.py").write_text(
        "from pkg import f\n\n\ndef one():\n    return f()\n"
    )
    first_run(tmp_path)
    (pkg / "__init__.py").write_text("from pkg._new import f\n")
    second = run_affected(tmp_path)
    assert "2 passed" in second.stdout, second.stdout


@pytest.mark.parametrize(
    "edited",
    [
        "# a note\ndef one():\n    return 1  # the one\n",
        "def one():\n    return 1 + 0\n",
    ],
    ids=["comment", "function-body"],
)
def test_a_comment_or_function_body_edit_keeps_test_env(tmp_path, edited):
    """Only module-level code counts, so testmon keeps its fine selection."""
    make_project(tmp_path)
    before = just("test-env", str(tmp_path))
    (tmp_path / "tests" / "a.py").write_text(edited)
    assert just("test-env", str(tmp_path)) == before


def test_a_module_that_does_not_parse_counts_by_its_bytes(tmp_path):
    """A file with a syntax error must change test-env when edited, not crash it."""
    make_project(tmp_path)
    broken = tmp_path / "tests" / "broken.py"
    broken.write_text("def (:\n")
    before = just("test-env", str(tmp_path))
    assert re.fullmatch(r"[0-9a-f]{16}", before)
    broken.write_text("def ((:\n")
    assert just("test-env", str(tmp_path)) != before


@pytest.mark.parametrize(
    ("marker", "recipe"), [("slow", "test-rest"), ("serial", "test")]
)
def test_a_test_another_pass_runs_reruns_when_its_code_changes(
    tmp_path, marker, recipe
):
    """A test the parallel pass deselects must still rerun in its own pass."""
    make_project(tmp_path)
    tests = tmp_path / "tests"
    (tests / "githooks").mkdir()
    (tests / "githooks" / "test_hook.py").write_text("def test_hook():\n    pass\n")
    (tests / "test_a.py").write_text(
        "import pytest\nfrom a import one\n\n\ndef test_a():\n    pass\n\n\n"
        f"@pytest.mark.{marker}\ndef test_marked():\n    assert one() >= 1\n"
    )
    for _ in range(2):
        for each in ("test", "test-rest"):
            done = run_affected(tmp_path, each)
            assert done.returncode == 0, done.stdout + done.stderr
    (tests / "a.py").write_text("def one():\n    return 1 + 1\n")
    second = run_affected(tmp_path, "test")
    if recipe == "test-rest":
        second = run_affected(tmp_path, recipe)
    assert "1 passed" in second.stdout, second.stdout


def test_an_edit_in_a_post_init_behind_a_module_level_instance_reruns_every_test(
    tmp_path,
):
    """A __post_init__ a module-level instance runs at import, unseen by testmon."""
    make_project(tmp_path)
    tests = tmp_path / "tests"
    metric = (
        "from dataclasses import dataclass\n\n\n@dataclass(frozen=True)\n"
        "class Metric:\n    power: float\n\n    def __post_init__(self):\n"
        "        scale = {}\n        object.__setattr__(self, 'scale', scale)\n\n"
        "    def compute(self):\n        return self.power * self.scale\n\n\n"
        "gamma = Metric(2.0)\n"
    )
    (tests / "metric.py").write_text(metric.format(1))
    (tests / "test_metric.py").write_text(
        "from metric import gamma\n\n\ndef test_gamma():\n"
        "    assert gamma.compute() == 2.0\n"
    )
    first = run_affected(tmp_path)
    assert "3 passed" in first.stdout, first.stdout + first.stderr
    (tests / "metric.py").write_text(metric.format(3))
    second = run_affected(tmp_path)
    assert "1 failed, 2 passed" in second.stdout, second.stdout


def test_an_edit_in_a_function_another_file_calls_at_module_level_reruns_every_test(
    tmp_path,
):
    """X = helper() in one file runs helper's body at import, wherever it is."""
    make_project(tmp_path)
    tests = tmp_path / "tests"
    (tests / "helpers.py").write_text("def helper():\n    return 1\n")
    (tests / "consts.py").write_text("from helpers import helper\n\nX = helper()\n")
    (tests / "a.py").write_text("import consts\n\n\ndef one():\n    return consts.X\n")
    first_run(tmp_path)
    (tests / "helpers.py").write_text("def helper():\n    return 1 + 0\n")
    second = run_affected(tmp_path)
    assert "2 passed" in second.stdout, second.stdout


def test_an_edit_in_a_decorator_applied_at_module_level_reruns_every_test(tmp_path):
    """A decorator's body runs when the function it decorates is defined."""
    make_project(tmp_path)
    tests = tmp_path / "tests"
    (tests / "deco.py").write_text("def register(f):\n    f.tag = 1\n    return f\n")
    (tests / "a.py").write_text(
        "from deco import register\n\n\n@register\ndef one():\n    return one.tag\n"
    )
    first_run(tmp_path)
    (tests / "deco.py").write_text(
        "def register(f):\n    f.tag = 1 + 0\n    return f\n"
    )
    second = run_affected(tmp_path)
    assert "2 passed" in second.stdout, second.stdout


def test_an_edit_in_a_function_nothing_calls_at_import_keeps_test_env(tmp_path):
    """Other bodies stay testmon's, so its fine selection holds."""
    make_project(tmp_path)
    module = (
        "def helper():\n    return 1\n\n\nX = helper()\n\n\n"
        "def other():\n    return {}\n\n\nclass K:\n    def m(self):\n"
        "        return {}\n"
    )
    path = tmp_path / "tests" / "c.py"
    path.write_text(module.format(2, 3))
    before = just("test-env", str(tmp_path))
    path.write_text(module.format("2 + 0", "3 + 0"))
    assert just("test-env", str(tmp_path)) == before
