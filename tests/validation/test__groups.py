"""The module's fingerprints, per C++ group, and the shared part.

On a scratch repository of two groups, ``a`` and ``b`` built on it, with a
hand-written manifest and ``compile_commands.json`` naming real files, the
real compiler and the real clang. ``ninja`` is a script printing the build's
``link.txt``, the module's link command.
"""

import json
import re
import subprocess

import pytest

from validation import _ctest, _groups


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


def test_a_header_outside_engine_src_counts_for_its_reader(scratch):
    """A header the compiler reads anywhere in the tree, outside a submodule."""
    include = scratch.root / "engine" / "include" / "sq"
    include.mkdir(parents=True)
    (include / "x.hpp").write_text("int x();\n")
    scratch.write("b/two.cpp", '#include "sq/x.hpp"\nint two() { return 2; }\n')
    before = scratch.prints()
    (include / "x.hpp").write_text("int x();\nint y();\n")
    assert _changed(before, scratch.prints()) == {"b"}


def test_a_header_in_a_submodule_is_left_to_its_pin(scratch):
    """A submodule's files change with its pin, which the shared part holds."""
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{'1' * 40},engine/include",
        ],
        cwd=scratch.root,
        check=True,
    )
    include = scratch.root / "engine" / "include"
    include.mkdir()
    (include / "dep.hpp").write_text("int dep();\n")
    scratch.write("b/two.cpp", '#include "dep.hpp"\nint two() { return 2; }\n')
    before = scratch.prints()
    (include / "dep.hpp").write_text("int dep();\nint other();\n")
    assert scratch.prints() == before


def test_a_file_of_any_suffix_another_group_holds_counts_for_its_reader(scratch):
    """``b`` reads ``a/table.def``, which none of ``a``'s sources read."""
    scratch.write("a/table.def", "X(1)\n")
    scratch.write(
        "b/two.cpp",
        '#define X(n) int f##n();\n#include "a/table.def"\nint two() { return 2; }\n',
    )
    before = scratch.prints()
    scratch.write("a/table.def", "X(1)\nX(2)\n")
    assert "b" in _changed(before, scratch.prints())


def test_a_file_of_any_suffix_a_shared_entry_reads_changes_the_shared_part(scratch):
    """A shared directory's file counts when the compiler reads it."""
    scratch.write("bindings/table.def", "X(1)\n")
    scratch.write(
        "bindings/module.cpp",
        '#define X(n) int f##n();\n#include "bindings/table.def"\n',
    )
    before = scratch.prints()
    scratch.write("bindings/table.def", "X(1)\nX(2)\n")
    assert _changed(before, scratch.prints()) == {"shared"}


def test_a_flag_of_an_entry_in_no_group_changes_the_shared_part(scratch):
    """Spec 5.1: every compile flag that is not a group's is shared."""
    before = scratch.prints()
    scratch.flags["bindings/module.cpp"] = ["-DSQ_EXTRA=1"]
    scratch.entries()
    assert _changed(before, scratch.prints()) == {"shared"}


def test_a_generated_source_or_its_flags_change_the_shared_part(scratch):
    """A source the build writes (a unity file, say), outside every group."""
    unity = scratch.build / "unity" / "unity.cpp"
    unity.parent.mkdir()
    unity.write_text("int unity() { return 0; }\n")
    scratch.flags[str(unity)] = []
    scratch.entries()
    first = scratch.prints()
    unity.write_text("int unity() { return 1; }\n")
    second = scratch.prints()
    assert _changed(first, second) == {"shared"}
    scratch.flags[str(unity)] = ["-O3"]
    scratch.entries()
    assert _changed(second, scratch.prints()) == {"shared"}


def test_a_header_of_a_vanished_build_environment_is_left_to_the_pins(scratch):
    """uv deletes its build environment (nanobind's headers) after a build.

    ``-M`` then fails, so what Ninja recorded at the build is read instead;
    without a record, the entry is unreadable.
    """
    gone = scratch.root.parent / "builds-v0" / ".tmpGone" / "include"
    scratch.flags["bindings/module.cpp"] = ["-isystem", str(gone)]
    module = scratch.src / "bindings" / "module.cpp"
    helper = scratch.root / "engine" / "include" / "helper.hpp"
    helper.parent.mkdir()
    helper.write_text("int helper();\n")
    module.write_text('#include <nanobind/nanobind.h>\n#include "helper.hpp"\n')
    scratch.entries()
    with pytest.raises(_groups.Unreadable, match=re.escape("module.cpp")):
        scratch.prints()
    (scratch.build / "deps.txt").write_text(
        "CMakeFiles/sq.dir/module.cpp.o: #deps 3, deps mtime 1 (VALID)\n"
        f"    {module}\n    {gone}/nanobind/nanobind.h\n    {helper}\n\n"
    )
    before = scratch.prints()
    module.write_text(module.read_text() + "int m();\n")
    second = scratch.prints()
    assert _changed(before, second) == {"shared"}
    helper.write_text("int helper();\nint more();\n")
    assert _changed(second, scratch.prints()) == {"shared"}


def test_a_group_a_shared_entry_reads_is_part_of_the_shared_part(scratch):
    """The bindings read ``a``'s header: any change in ``a`` reruns everything.

    Spec 5.2: what the module runs at start-up is shared.
    """
    scratch.write("bindings/module.cpp", '#include "a/one.hpp"\nint m();\n')
    before = scratch.prints()
    scratch.write("a/one.cpp", '#include "a/one.hpp"\n// x\nint one() { return 7; }\n')
    assert _changed(before, scratch.prints()) == {"a", "b", "shared"}


IDENTITY = """#pragma once

#define SQ_SQLEARN_VERSION "{version}"
#define SQ_DUCKDB_VERSION "2.0.1"
#define SQ_COMPILER "AppleClang 21.0.0.21000401"
"""


def test_a_new_commit_alone_changes_no_fingerprint(scratch):
    """``build_identity.hpp``'s version counts by its release part alone.

    Its dev, local and date parts change with each commit, as
    ``validation._cases.environment`` says of sqlearn's version.
    """
    identity = scratch.build / "generated" / "build_identity.hpp"
    identity.parent.mkdir()
    scratch.flags["a/one.cpp"] = [f"-I{identity.parent}"]
    scratch.write(
        "a/one.cpp", '#include "build_identity.hpp"\nint one() { return 1; }\n'
    )
    scratch.entries()
    identity.write_text(IDENTITY.format(version="0.1.dev719+ge19d484f4.d20261127"))
    before = scratch.prints()
    identity.write_text(IDENTITY.format(version="0.1.dev720+gabcdef012"))
    assert scratch.prints() == before
    identity.write_text(IDENTITY.format(version="0.1"))
    assert scratch.prints() == before
    identity.write_text(IDENTITY.format(version="0.2.dev1+g1234567"))
    assert _changed(before, scratch.prints()) == {"a", "b", "shared"}
    identity.write_text(IDENTITY.format(version="0.1").replace("2.0.1", "2.0.2"))
    assert _changed(before, scratch.prints()) == {"a", "b", "shared"}


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


def test_the_coverage_wheels_override_keeps_the_shared_part(scratch):
    """The audit's override, taken only under ``AUDIT_ENV``, is no setting of
    the normal wheel; an override taken otherwise is."""
    before = scratch.prints()
    pyproject = scratch.root / "pyproject.toml"
    plain = pyproject.read_text()
    pyproject.write_text(
        plain + "\n[[tool.scikit-build.overrides]]\n"
        f"if.env.{_groups.AUDIT_ENV} = true\n"
        'build-dir = "build/coverage-{cache_tag}"\n'
        'cmake.define.SQ_FLAVOR = "coverage"\n'
    )
    assert scratch.prints() == before
    pyproject.write_text(
        plain + "\n[[tool.scikit-build.overrides]]\n"
        'if.platform-system = "^darwin$"\n'
        'cmake.define.SQ_FLAVOR = "coverage"\n'
    )
    assert scratch.prints().shared != before.shared


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
