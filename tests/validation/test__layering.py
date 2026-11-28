"""The layering check: each group's ``DEPENDS`` against what it includes.

On a scratch tree of ``engine/src/<group>/`` and ``engine/tests/<group>/``
files, with the groups written by hand, as the manifest would hold them.
"""

import json
from pathlib import Path

import pytest

from validation import _groups, _layering

REPO = Path(__file__).resolve().parents[2]

SHARED = ("engine/src/bindings", "engine/extension")
"""The manifest's shared directories."""


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


def _write(root, files):
    """Write each of `files`, a path relative to `root` and its text."""
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_an_include_of_a_group_not_depended_on_is_refused(tmp_path):
    """``raw`` reaching ``crash``'s header without naming it is one problem."""
    _write(
        tmp_path,
        {
            "engine/src/core/x.hpp": "#pragma once\n",
            "engine/src/crash/h.hpp": "#pragma once\n",
            "engine/src/raw/a.cpp": '#include "core/x.hpp"\n#include "crash/h.hpp"\n',
        },
    )
    groups = {
        "core": _group("core"),
        "raw": _group("raw", ["core"]),
        "crash": _group("crash"),
    }
    found = _layering.problems(tmp_path, groups, shared=SHARED)
    assert len(found) == 1
    assert "raw" in found[0]
    assert "crash" in found[0]
    assert 'engine/src/raw/a.cpp:2: #include "crash/h.hpp"' in found[0]
    assert "Fix: add crash to DEPENDS" in found[0]


def test_an_include_of_a_group_not_depended_on_in_its_tests_is_refused(tmp_path):
    """A group's tests include only what the group may."""
    _write(
        tmp_path,
        {
            "engine/src/raw/a.cpp": "int a() { return 1; }\n",
            "engine/tests/raw/test_a.cpp": '#include "crash/h.hpp"\n',
        },
    )
    groups = {"raw": _group("raw"), "crash": _group("crash")}
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "engine/tests/raw/test_a.cpp:1" in found
    assert "Fix: add crash to DEPENDS" in found


def test_an_angle_include_counts(tmp_path):
    """``<core/x.hpp>`` names ``core`` as ``"core/x.hpp"`` does."""
    path = tmp_path / "a.cpp"
    path.write_text("#include <core/x.hpp>\n#include <vector>\n", encoding="utf-8")
    assert _layering.included(path, ["core", "raw"]) == {"core"}


def test_an_include_in_a_comment_counts(tmp_path):
    """A commented-out include still names its group: it fails safe."""
    path = tmp_path / "a.cpp"
    path.write_text('// #include "core/x.hpp"\n', encoding="utf-8")
    assert _layering.included(path, ["core"]) == {"core"}


def test_an_include_naming_no_group_is_ignored(tmp_path):
    """The standard library's, third parties' and generated headers name none."""
    path = tmp_path / "a.cpp"
    path.write_text(
        "#include <catch2/catch_test_macros.hpp>\n"
        "#include <cpptrace/basic.hpp>\n"
        '#include "build_identity.hpp"\n'
        "#  include <string>\n",
        encoding="utf-8",
    )
    assert _layering.included(path, ["core", "raw"]) == set()


def test_a_dependency_of_a_dependency_must_be_named(tmp_path):
    """``crash`` on ``raw`` on ``core`` names ``core`` too."""
    _write(
        tmp_path,
        {
            "engine/src/core/x.hpp": "#pragma once\n",
            "engine/src/raw/r.hpp": '#include "core/x.hpp"\n',
            "engine/src/crash/c.cpp": '#include "raw/r.hpp"\n',
        },
    )
    groups = {
        "core": _group("core"),
        "raw": _group("raw", ["core"]),
        "crash": _group("crash", ["raw"]),
    }
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "Fix: add core to DEPENDS of crash" in found


def test_a_dependency_nothing_includes_is_stale(tmp_path):
    """``raw`` naming ``core`` while including nothing of it is stale."""
    _write(
        tmp_path,
        {
            "engine/src/core/x.hpp": "#pragma once\n",
            "engine/src/raw/a.cpp": '#include "raw/a.hpp"\n',
            "engine/src/raw/a.hpp": "#pragma once\n",
        },
    )
    groups = {"core": _group("core"), "raw": _group("raw", ["core"])}
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "stale" in found
    assert "Fix:" in found


def test_a_dependency_only_the_tests_include_is_stale(tmp_path):
    """The archive links ``DEPENDS`` for the group's code: tests do not count."""
    _write(
        tmp_path,
        {
            "engine/src/raw/a.cpp": "int a() { return 1; }\n",
            "engine/tests/raw/test_a.cpp": '#include "core/x.hpp"\n',
        },
    )
    groups = {"core": _group("core"), "raw": _group("raw", ["core"])}
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "stale" in found


def test_a_cycle_is_refused(tmp_path):
    """``a`` on ``b`` on ``a`` is one problem naming both."""
    _write(
        tmp_path,
        {
            "engine/src/a/a.cpp": '#include "b/b.hpp"\n',
            "engine/src/b/b.hpp": '#include "a/a.hpp"\n',
            "engine/src/a/a.hpp": "#pragma once\n",
        },
    )
    groups = {"a": _group("a", ["b"]), "b": _group("b", ["a"])}
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "groups a, b depend on one another in a cycle" in found
    assert "Fix:" in found


def test_a_group_including_the_bindings_is_refused(tmp_path):
    """A group never reaches into a shared directory."""
    _write(
        tmp_path,
        {
            "engine/src/bindings/guard.hpp": "#pragma once\n",
            "engine/src/core/x.cpp": '#include "bindings/guard.hpp"\n',
        },
    )
    groups = {"core": _group("core")}
    (found,) = _layering.problems(tmp_path, groups, shared=SHARED)
    assert "engine/src/core/x.cpp:1" in found
    assert "engine/src/bindings" in found
    assert "Fix:" in found


def test_the_bindings_may_include_any_group(tmp_path):
    """The shared directories are no group's files: nothing checks them."""
    _write(
        tmp_path,
        {
            "engine/src/bindings/module.cpp": '#include "core/x.hpp"\n',
            "engine/src/core/x.hpp": "#pragma once\n",
        },
    )
    groups = {"core": _group("core")}
    assert _layering.problems(tmp_path, groups, shared=SHARED) == []


def test_the_real_engine_has_no_problems():
    """The engine's declarations match what its files include."""
    build = REPO / "engine" / "build" / "llvm-dev"
    if not (build / _groups.MANIFEST).is_file():
        pytest.skip(f"no configured build at {build}: just tidy-engine")
    groups, shared = _groups.load(build)
    assert _layering.problems(REPO, groups, shared=shared) == []


def test_the_command_reports_each_problem_and_fails(tmp_path, capsys):
    """``python -m validation._layering`` prints the problems, exit 1."""
    build = tmp_path / "build"
    build.mkdir()
    claims = {"depends": [], "python_tests": [], "validation": [], "bench": []}
    manifest = {
        "groups": [
            {"name": name, "dir": f"engine/src/{name}", **claims}
            for name in ("core", "raw")
        ],
        "shared": list(SHARED),
    }
    (build / _groups.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    _write(tmp_path, {"engine/src/raw/a.cpp": '#include "core/x.hpp"\n'})
    assert _layering.cli(["--root", str(tmp_path), "--build", str(build)]) == 1
    assert "Fix: add core to DEPENDS" in capsys.readouterr().out
    _write(tmp_path, {"engine/src/raw/a.cpp": "int a() { return 1; }\n"})
    assert _layering.cli(["--root", str(tmp_path), "--build", str(build)]) == 0
