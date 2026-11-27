"""The module's fingerprints, per C++ group, and the shared part.

On a scratch repository of two groups, ``a`` and ``b`` built on it, with a
hand-written manifest and ``compile_commands.json`` naming real files, the
real compiler and the real clang. ``ninja`` is a script printing the build's
``link.txt``, the module's link command.
"""

import json
import os
import re
import shlex
import shutil
import subprocess

import pytest

from validation import _ctest, _groups

NINJA = """#!/bin/sh
# Called as: ninja -C <build> -t commands _duckdb
printf 'echo first\\n'
cat "$2/link.txt"
"""

PYPROJECT = """[project]
name = "scratch"

[build-system]
requires = ["scikit-build-core==1.1.2"]

[tool.scikit-build]
cmake.source-dir = "engine"
"""


class Scratch:
    """A scratch repository with groups ``a`` and ``b``, and its build."""

    def __init__(self, root, compiler):
        self.root = root
        self.build = root / "build" / "cpython-312"
        self.src = root / "engine" / "src"
        self.compiler = compiler
        self.flags = {"a/one.cpp": [], "b/two.cpp": []}

    def write(self, relative, text):
        """Write `text` to `relative`, a path under ``engine/src``."""
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def entries(self):
        """Write ``compile_commands.json`` for the sources of ``self.flags``."""
        entries = []
        for source, extra in self.flags.items():
            path = self.src / source
            argv = [
                self.compiler,
                "-std=c++23",
                f"-I{self.src}",
                *extra,
                "-o",
                f"CMakeFiles/sq.dir/{source}.o",
                "-c",
                str(path),
            ]
            entries.append(
                {
                    "directory": str(self.build),
                    "command": shlex.join(argv),
                    "file": str(path),
                    "output": str(self.build / f"CMakeFiles/sq.dir/{source}.o"),
                }
            )
        (self.build / "compile_commands.json").write_text(json.dumps(entries))

    def link(self, text):
        """Write the module's link command that ``ninja -t commands`` prints."""
        (self.build / "link.txt").write_text(text + "\n")

    def prints(self):
        """Return the scratch repository's fingerprints."""
        return _groups.fingerprints(self.root, self.build)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """The scratch repository, ``ninja`` faked on ``PATH``."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("c++ is needed: just doctor")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ninja = bin_dir / "ninja"
    ninja.write_text(NINJA)
    ninja.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    made = Scratch(root, compiler)
    made.build.mkdir(parents=True)
    made.write("a/one.hpp", "#pragma once\nint one();\n")
    made.write("a/one.cpp", '#include "a/one.hpp"\n// x\nint one() { return 1; }\n')
    made.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return one(); }\n')
    made.write("bindings/module.cpp", "int module() { return 0; }\n")
    (root / "engine" / "extension").mkdir()
    (root / "engine" / "extension" / "CMakeLists.txt").write_text("# none\n")
    manifest = {
        "groups": [
            {
                "name": "a",
                "dir": "engine/src/a",
                "depends": [],
                "python_tests": [],
                "validation": [],
                "bench": [],
            },
            {
                "name": "b",
                "dir": "engine/src/b",
                "depends": ["a"],
                "python_tests": ["tests/test_b.py"],
                "validation": [],
                "bench": [],
            },
        ],
        "shared": ["engine/src/bindings", "engine/extension"],
    }
    (made.build / "sq_groups.json").write_text(json.dumps(manifest))
    made.entries()
    made.link(f"{compiler} -bundle -o _duckdb.abi3.so one.o two.o")
    return made


def _changed(before, after):
    """Return the parts that differ: ``shared`` and the groups' names."""
    names = {n for n in before.groups if before.groups[n] != after.groups[n]}
    return names | ({"shared"} if before.shared != after.shared else set())


def test_a_comment_edited_within_its_line_keeps_every_fingerprint(scratch):
    """``// x`` becoming ``// y`` moves no line: nothing reruns."""
    before = scratch.prints()
    scratch.write("a/one.cpp", '#include "a/one.hpp"\n// y\nint one() { return 1; }\n')
    assert scratch.prints() == before


def test_a_comment_inside_a_string_is_code(scratch):
    """What looks like a comment in a literal, raw or not, is the literal's."""
    scratch.write("a/one.cpp", 'const char *s = "// x";\nauto r = R"(/* x */)";\n')
    before = scratch.prints()
    scratch.write("a/one.cpp", 'const char *s = "// y";\nauto r = R"(/* x */)";\n')
    middle = scratch.prints()
    scratch.write("a/one.cpp", 'const char *s = "// y";\nauto r = R"(/* y */)";\n')
    assert _changed(before, middle) == {"a", "b"}
    assert _changed(middle, scratch.prints()) == {"a", "b"}


def test_a_comment_line_added_changes_its_group_and_those_built_on_it(scratch):
    """A line moved reaches users through a ``PreconditionError``'s line."""
    before = scratch.prints()
    scratch.write(
        "a/one.cpp", '#include "a/one.hpp"\n// x\n// more\nint one() { return 1; }\n'
    )
    assert _changed(before, scratch.prints()) == {"a", "b"}


def test_a_code_change_in_b_leaves_a_alone(scratch):
    """Only the group whose code changed, and none it is built on."""
    before = scratch.prints()
    scratch.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return 2; }\n')
    assert _changed(before, scratch.prints()) == {"b"}


def test_a_header_of_a_read_by_b_changes_both_once(scratch, monkeypatch):
    """The header counts for ``a`` alone, and reaches ``b`` through ``a``."""
    before = scratch.prints()
    scratch.write("a/one.hpp", "#pragma once\nint one();\nint other();\n")
    real = _groups.stripped
    seen = []

    def counted(path):
        seen.append(path.name)
        return real(path)

    monkeypatch.setattr(_groups, "stripped", counted)
    after = scratch.prints()
    assert _changed(before, after) == {"a", "b"}
    assert seen.count("one.hpp") == 1


def test_a_header_of_a_group_not_depended_on_still_reaches_its_reader(scratch):
    """Fail safe: a header read across groups adds the group it belongs to."""
    manifest = scratch.build / "sq_groups.json"
    data = json.loads(manifest.read_text())
    data["groups"][1]["depends"] = []
    manifest.write_text(json.dumps(data))
    before = scratch.prints()
    scratch.write("a/one.hpp", "#pragma once\nint one();\nint other();\n")
    assert _changed(before, scratch.prints()) == {"a", "b"}


def test_a_header_in_no_group_counts_for_each_group_reading_it(scratch):
    """Fail safe: a header under ``engine/src`` that no group holds."""
    scratch.write("loose.hpp", "int loose();\n")
    scratch.write("b/two.cpp", '#include "loose.hpp"\nint two() { return 2; }\n')
    before = scratch.prints()
    scratch.write("loose.hpp", "int loose();\nint more();\n")
    assert _changed(before, scratch.prints()) == {"b"}


def test_a_compile_flag_changes_the_group(scratch):
    """A flag of ``b``'s compile entry reruns ``b``, not ``a`` nor everything."""
    before = scratch.prints()
    scratch.flags["b/two.cpp"] = ["-DSQ_EXTRA=1"]
    scratch.entries()
    assert _changed(before, scratch.prints()) == {"b"}


def test_the_link_command_changes_the_shared_part(scratch):
    """The module's link command, not a group's, carries flags of no source."""
    before = scratch.prints()
    scratch.link(f"{scratch.compiler} -bundle -Wl,-dead_strip -o _duckdb.abi3.so")
    assert _changed(before, scratch.prints()) == {"shared"}


def test_a_pin_build_table_or_compiler_changes_the_shared_part(scratch, monkeypatch):
    """A submodule's pin, ``[tool.scikit-build]`` and the compiler: shared."""
    first = scratch.prints()
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{'1' * 40},engine/duckdb",
        ],
        cwd=scratch.root,
        check=True,
    )
    second = scratch.prints()
    assert _changed(first, second) == {"shared"}
    pyproject = scratch.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + 'build-dir = "build/{cache_tag}"\n')
    third = scratch.prints()
    assert _changed(second, third) == {"shared"}
    real = _ctest.compiler
    monkeypatch.setattr(_ctest, "compiler", lambda build: real(build) + " (another)")
    assert _changed(third, scratch.prints()) == {"shared"}


def test_a_project_table_left_out_keeps_the_shared_part(scratch):
    """Only the build tables of ``pyproject.toml`` count, not its others."""
    before = scratch.prints()
    pyproject = scratch.root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace('name = "scratch"', 'name = "other"')
    )
    assert scratch.prints() == before


def test_a_source_no_compile_entry_lists_is_unreadable(scratch):
    """A source the build does not compile cannot be fingerprinted: refused."""
    scratch.write("a/three.cpp", "int three() { return 3; }\n")
    with pytest.raises(_groups.Unreadable, match=re.escape("a/three.cpp")):
        scratch.prints()


def test_a_missing_manifest_or_compile_database_is_unreadable(scratch):
    """Without what it reads, the fingerprint says what is missing."""
    (scratch.build / "compile_commands.json").unlink()
    with pytest.raises(_groups.Unreadable, match=re.escape("compile_commands.json")):
        scratch.prints()
    (scratch.build / "sq_groups.json").write_text('{"groups": [')
    with pytest.raises(_groups.Unreadable, match=re.escape("sq_groups.json")):
        _groups.load(scratch.build)
    (scratch.build / "sq_groups.json").unlink()
    with pytest.raises(_groups.Unreadable, match=re.escape("sq_groups.json")):
        _groups.load(scratch.build)


def test_the_manifest_loads_as_groups(scratch):
    """``load`` gives each group with its claims, and the shared directories."""
    groups, shared = _groups.load(scratch.build)
    assert groups["b"] == _groups.Group(
        name="b",
        dir="engine/src/b",
        depends=("a",),
        python_tests=("tests/test_b.py",),
        validation=(),
        bench=(),
    )
    assert shared == ("engine/src/bindings", "engine/extension")


def _group(name, depends=()):
    """Return a group of `name` built on `depends`, claiming nothing."""
    return _groups.Group(
        name=name,
        dir=f"engine/src/{name}",
        depends=tuple(depends),
        python_tests=(),
        validation=(),
        bench=(),
    )


def test_closure_follows_depends():
    """The groups named and every group they are built on, transitively."""
    groups = {
        "core": _group("core"),
        "raw": _group("raw", ["core"]),
        "crash": _group("crash", ["raw"]),
        "other": _group("other"),
    }
    assert _groups.closure(groups, ["crash"]) == {"crash", "raw", "core"}
    assert _groups.closure(groups, []) == set()
    with pytest.raises(_groups.Unreadable, match="nowhere"):
        _groups.closure(groups, ["nowhere"])


def test_identity_of_no_uses_covers_every_group():
    """``None`` uses every group; a use covers its closure only."""
    groups = {"a": _group("a"), "b": _group("b", ["a"]), "c": _group("c")}
    prints = _groups.Fingerprints(shared="s", groups={"a": "1", "b": "2", "c": "3"})
    every = _groups.identity(prints, groups, None)
    assert every == _groups.identity(prints, groups, ["a", "b", "c"])
    assert every != _groups.identity(prints, groups, ["b"])
    c_changed = _groups.Fingerprints(shared="s", groups={"a": "1", "b": "2", "c": "4"})
    assert _groups.identity(prints, groups, ["b"]) == _groups.identity(
        c_changed, groups, ["b"]
    )
    assert _groups.identity(c_changed, groups, None) != every
    shared_changed = _groups.Fingerprints(shared="t", groups=prints.groups)
    assert _groups.identity(shared_changed, groups, ["b"]) != _groups.identity(
        prints, groups, ["b"]
    )
