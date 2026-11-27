"""The Python tests by set: what reruns each, and what is refused.

On the scratch repository of the validation tests' conftest, its groups
``a`` and ``b`` (built on ``a``) claiming ``tests/src/a`` and
``tests/src/b``. ``pytest`` is a stand-in on ``PATH`` that logs its argv, so
no real test runs.
"""

import json
import sys
from pathlib import Path

import pytest

from validation import _groups, _pytest_sets

PYTEST = """#!{python}
import json, os, pathlib, sys
argv = sys.argv[1:]
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps(argv) + "\\n")
rules = pathlib.Path(os.environ["CALLS"] + ".rules")
for word, code, edit in json.loads(rules.read_text()) if rules.exists() else []:
    if word in " ".join(argv):
        if edit:
            path = pathlib.Path(edit)
            path.write_text(path.read_text() + "# edited while it ran\\n")
        sys.exit(code)
"""

FILES = {
    "tests/conftest.py": "",
    "tests/checks/test_tool.py": "def test_tool():\n    pass\n",
    "tests/src/sqlearn/test_lib.py": "def test_lib():\n    pass\n",
    "tests/src/a/test_a.py": "def test_a():\n    pass\n",
    "tests/src/b/test_b.py": "def test_b():\n    pass\n",
    "src/sqlearn/__init__.py": "x = 1\n",
    "engine/mull.yml": "mutators: []\n",
    "engine/CMakeLists.txt": "# the build\n",
}


class Repo:
    """The scratch repository with test sets, and the stand-in's log."""

    def __init__(self, scratch, calls):
        self.scratch = scratch
        self.root = scratch.root
        self.calls = calls

    def edit(self, relative, text="# edited\n"):
        """Append `text` to the file `relative`, made when absent."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((path.read_text() if path.exists() else "") + text)

    def rule(self, word, code, edit=None):
        """Make the stand-in exit `code` (editing `edit`) when `word` is in its argv."""
        rules = Path(f"{self.calls}.rules")
        found = json.loads(rules.read_text()) if rules.exists() else []
        found.append([word, code, str(self.root / edit) if edit else None])
        rules.write_text(json.dumps(found))

    def sets(self):
        """Return the sets of the scratch repository."""
        groups, _ = _groups.load(self.scratch.build)
        return _pytest_sets.sets(groups, self.root)

    def ran(self):
        """Return and forget the names of the sets run since the last look."""
        if not self.calls.exists():
            return set()
        by_paths = {paths: name for name, (paths, _) in self.sets().items()}
        names = set()
        for line in self.calls.read_text().splitlines():
            paths = tuple(a for a in json.loads(line) if a.startswith("tests"))
            names.add(by_paths[paths])
        self.calls.unlink()
        return names

    def run(self, **options):
        """Run the sets; return the exit code."""
        return _pytest_sets.run(self.root, **options)


@pytest.fixture
def repo(scratch, tmp_path, monkeypatch):
    """The scratch repository with a tooling, two group and an unclaimed set."""
    for name, text in FILES.items():
        path = scratch.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    manifest = scratch.build / "sq_groups.json"
    data = json.loads(manifest.read_text())
    data["groups"][0]["python_tests"] = ["tests/src/a"]
    data["groups"][1]["python_tests"] = ["tests/src/b"]
    manifest.write_text(json.dumps(data))
    bin_dir = tmp_path / "bin"
    stand_in = bin_dir / "pytest"
    stand_in.write_text(PYTEST.format(python=sys.executable))
    stand_in.chmod(0o755)
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("CALLS", str(calls))
    made = Repo(scratch, calls)
    assert made.run() == 0
    assert made.ran() == {"tooling", "group:a", "group:b", "unclaimed"}
    return made


def test_an_unchanged_tree_runs_no_set(repo, capsys):
    """A second run with nothing changed runs nothing and says so for each set."""
    capsys.readouterr()
    assert repo.run() == 0
    assert repo.ran() == set()
    out = capsys.readouterr().out
    for name in ("tooling", "group:a", "group:b", "unclaimed"):
        assert f"{name}: unchanged since a passed run" in out


def test_a_change_under_src_reruns_every_library_set(repo):
    """``import sqlearn`` loads the whole package: every library set reruns."""
    repo.edit("src/sqlearn/__init__.py")
    assert repo.run() == 0
    assert repo.ran() == {"group:a", "group:b", "unclaimed"}


def test_a_group_change_reruns_its_set_and_the_unclaimed_one(repo):
    """A code change in ``b`` reruns ``b``'s set and the unclaimed one, which
    uses every group, and the tooling set, which uses the whole module; ``a``,
    which ``b`` is built on, keeps its pass."""
    repo.scratch.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return 2; }\n')
    assert repo.run() == 0
    assert repo.ran() == {"tooling", "group:b", "unclaimed"}


@pytest.mark.parametrize(
    ("edited", "reran"),
    [
        ("tests/src/b/test_b.py", "group:b"),
        ("tests/src/sqlearn/test_lib.py", "unclaimed"),
        ("tests/checks/test_tool.py", "tooling"),
    ],
)
def test_an_edited_test_file_reruns_its_set_alone(repo, edited, reran):
    """A test file is its own set's input, no other's."""
    repo.edit(edited)
    assert repo.run() == 0
    assert repo.ran() == {reran}


def test_a_tooling_input_reruns_the_tooling_set_alone(repo):
    """``mull.yml``, read by the tooling tests as data, reruns them alone."""
    repo.edit("engine/mull.yml")
    assert repo.run() == 0
    assert repo.ran() == {"tooling"}


EVERY = {"tooling", "group:a", "group:b", "unclaimed"}


@pytest.mark.parametrize(
    ("data", "reran"),
    [
        ("docs/architecture/engine-inventory.md", {"tooling"}),
        ("docs/conf.py", {"tooling"}),
        (".githooks/pre-commit", {"tooling"}),
        ("commitlint.config.mjs", {"tooling"}),
        ("devdata/data/iris.csv", EVERY),
        ("validation/_cases.py", EVERY),
        ("tests/conftest.py", EVERY),
        ("tests/src/helpers.py", {"group:a", "group:b", "unclaimed"}),
        ("uv.lock", EVERY),
    ],
)
def test_a_data_file_reruns_the_sets_that_read_it(repo, data, reran):
    """A file a set reads, changed or new, reruns that set: the tooling tests
    read the docs and hooks as data, the library tests import the validation
    and the test helpers, and every set runs under the locked versions."""
    repo.edit(data)
    assert repo.run() == 0
    assert repo.ran() == reran


@pytest.mark.parametrize(
    "cmake", ["engine/CMakeLists.txt", "engine/extension/CMakeLists.txt"]
)
def test_a_cmake_comment_reruns_the_tooling_set_alone(repo, cmake):
    """The tooling tests read CMake files as text; the fingerprints never do."""
    repo.edit(cmake)
    assert repo.run() == 0
    assert repo.ran() == {"tooling"}


def test_a_new_package_under_tests_src_is_unclaimed(repo):
    """A package no group claims joins the unclaimed set, which uses every group."""
    repo.edit("tests/src/fresh/test_fresh.py", "def test_fresh():\n    pass\n")
    sets = repo.sets()
    paths, uses = sets["unclaimed"]
    assert "tests/src/fresh" in paths
    assert uses is None
    assert sets["group:b"] == (("tests/src/b",), {"b"})
    assert not any(p.startswith("tests/src/b") for p in paths)


def test_a_test_file_in_no_set_is_refused_with_a_fix(repo, capsys):
    """A test file outside the tooling paths and ``tests/src`` would never run."""
    repo.edit("tests/test_loose.py", "def test_loose():\n    pass\n")
    with pytest.raises(ValueError, match=r"tests/test_loose\.py[\s\S]*Fix:"):
        repo.sets()
    capsys.readouterr()
    assert repo.run() != 0
    assert "Fix:" in capsys.readouterr().out
    assert repo.ran() == set()


def test_all_runs_every_set(repo):
    """``--all`` runs every set, recorded or not."""
    assert repo.run(everything=True) == 0
    assert repo.ran() == {"tooling", "group:a", "group:b", "unclaimed"}


def test_a_failing_set_reruns_and_the_others_keep_their_pass(repo):
    """A failed set is never recorded, and its earlier pass is forgotten."""
    repo.edit("tests/src/b/test_b.py")
    repo.edit("tests/src/a/test_a.py")
    repo.rule("tests/src/b", 1)
    assert repo.run() == 1
    assert repo.ran() == {"group:a", "group:b"}
    assert repo.run() == 1
    assert repo.ran() == {"group:b"}


def test_a_failure_cancels_the_pass_of_the_same_identity(repo):
    """A set that passed, then fails under ``--all`` with nothing changed, reruns."""
    repo.rule("tests/src/b", 1)
    assert repo.run(everything=True) == 1
    repo.ran()
    assert repo.run() == 1
    assert repo.ran() == {"group:b"}


def test_only_the_serial_pass_may_collect_nothing(repo):
    """Exit 5 passes the serial pass alone: a broken marker elsewhere must fail."""
    repo.edit("tests/src/b/test_b.py")
    repo.rule("serial and not slow", 5)
    assert repo.run() == 0
    repo.edit("tests/src/b/test_b.py")
    repo.rule("-m slow", 5)
    assert repo.run() == 5


def test_each_set_runs_the_three_passes_on_its_paths(repo):
    """The fast tests in parallel, the serial ones alone, then the slow tier."""
    repo.edit("tests/src/b/test_b.py")
    assert repo.run() == 0
    calls = [json.loads(line) for line in repo.calls.read_text().splitlines()]
    report = ["-p", "validation._tests_report"]
    assert calls == [
        [*report, "-n", "auto", "-m", "not slow and not serial", "tests/src/b"],
        [*report, "-p", "no:xdist", "-m", "serial and not slow", "tests/src/b"],
        [*report, "-p", "no:xdist", "-m", "slow", "tests/src/b"],
    ]


def test_a_set_whose_inputs_changed_while_it_ran_is_not_recorded(repo, capsys):
    """A file edited during the run leaves the set to run again."""
    repo.edit("tests/src/b/test_b.py")
    repo.rule("tests/src/b", 0, edit="tests/src/b/test_b.py")
    capsys.readouterr()
    assert repo.run() == 0
    assert "group:b: not recorded" in capsys.readouterr().out
    Path(f"{repo.calls}.rules").unlink()
    repo.ran()
    assert repo.run() == 0
    assert repo.ran() == {"group:b"}


def test_unreadable_fingerprints_run_every_set_and_record_none(repo, capsys):
    """No ``compile_commands.json``: the reason is printed and every set runs."""
    (repo.scratch.build / "compile_commands.json").unlink()
    capsys.readouterr()
    assert repo.run() == 0
    assert "compile_commands.json" in capsys.readouterr().out
    assert repo.ran() == {"tooling", "group:a", "group:b", "unclaimed"}
    assert repo.run() == 0
    assert repo.ran() == {"tooling", "group:a", "group:b", "unclaimed"}
