"""The audit of the groups' claims: what a set or runner ran against what it
declares.

On llvm-cov exports written by hand (no coverage build in the fast tests),
for groups ``a``, ``b`` built on it, and ``c``; ``a`` and ``b`` claim the
tests under ``tests/src/a`` and ``tests/src/b``.
"""

from validation import _audit, _groups, _pytest_sets

ROOT = "/repo"


def _group(name, depends=(), python_tests=()):
    """Return the group `name` of ``engine/src/<name>``."""
    return _groups.Group(
        name=name,
        dir=f"engine/src/{name}",
        depends=tuple(depends),
        python_tests=tuple(python_tests),
        validation=(),
        bench=(),
    )


GROUPS = {
    "a": _group("a", python_tests=["tests/src/a"]),
    "b": _group("b", depends=["a"], python_tests=["tests/src/b"]),
    "c": _group("c"),
}


def _export(files):
    """Return an ``llvm-cov export -summary-only`` of `files`: each path,
    relative to the root, with its covered and count of regions."""

    def summary(covered, count):
        return {"count": count, "covered": covered, "percent": 0.0}

    return {
        "type": "llvm.coverage.json.export",
        "data": [
            {
                "files": [
                    {
                        "filename": f"{ROOT}/{name}",
                        "summary": {
                            "regions": summary(*regions),
                            "lines": summary(*regions),
                        },
                    }
                    for name, regions in files.items()
                ],
                "totals": {},
            }
        ],
    }


def test_a_set_running_an_undeclared_group_is_a_finding():
    """``b``'s set and a runner ``b`` claims ran ``c``: each is named with the
    group to add; a file whose regions never ran counts for no group."""
    export = _export(
        {
            "engine/src/b/b.cpp": (3, 4),
            "engine/src/c/c.hpp": (1, 9),
            "engine/src/a/a.cpp": (0, 5),
        }
    )
    seen = _audit.ran(export, GROUPS)
    assert seen == {"b", "c"}
    found = _audit.findings(
        {"group:b": {"b"}, "validate_b": {"b"}},
        {"group:b": seen, "validate_b": seen},
        set(),
        set(),
        GROUPS,
    )
    assert found == [
        "group:b ran c: Fix: add it to sq_add_group(c PYTHON_TESTS tests/src/b)",
        "validate_b ran c: Fix: add it to sq_add_group(c VALIDATION validate_b)",
    ]


def test_startup_groups_are_no_finding():
    """What a bare ``import sqlearn`` runs is no finding when it is shared."""
    start = _audit.startup(_export({"engine/src/c/c.cpp": (2, 2)}), GROUPS)
    assert start == {"c"}
    seen = _audit.ran(
        _export({"engine/src/a/a.cpp": (1, 2), "engine/src/c/c.cpp": (2, 2)}), GROUPS
    )
    found = _audit.findings({"group:a": {"a"}}, {"group:a": seen}, start, {"c"}, GROUPS)
    assert found == []


def test_a_startup_group_outside_the_shared_part_is_a_finding():
    """``c`` runs at import but the bindings do not read it, so a change to it
    reruns nothing: it is named, and a set running it is not excused."""
    start = {"c"}
    found = _audit.findings(
        {"group:a": {"a"}}, {"group:a": {"a", "c"}}, start, set(), GROUPS
    )
    assert found == [
        "c runs at import but is not shared: Fix: include its header in the "
        "bindings (engine/src/bindings/), so it is in the shared part, or keep "
        "it from running at import",
        "group:a ran c: Fix: add it to sq_add_group(c PYTHON_TESTS tests/src/a)",
    ]


def test_groups_claiming_one_path_declare_its_set_jointly():
    """``b`` and ``c`` both claim ``tests/src/x``, and ``a`` claims the whole of
    ``tests/src``: each set's audit declares every group claiming a path
    equal to, above or below its own, so the claims that exist clear it."""
    groups = {
        "a": _group("a", python_tests=["tests/src"]),
        "b": _group("b", python_tests=["tests/src/x"]),
        "c": _group("c", python_tests=["tests/src/x/"]),
        "d": _group("d", python_tests=["tests/src/xy"]),
    }
    sets: _pytest_sets.Sets = {
        "tooling": (("tests/checks",), None),
        "group:b": (("tests/src/x",), {"b"}),
        "group:d": (("tests/src/xy",), {"d"}),
        "unclaimed": (("tests/src/z",), None),
    }
    declared = _audit.declarations(sets, groups)
    assert declared == {
        "tooling": None,
        "group:b": {"a", "b", "c"},
        "group:d": {"a", "d"},
        "unclaimed": None,
    }
    found = _audit.findings(declared, {"group:b": {"b", "c"}}, set(), set(), groups)
    assert found == []


def test_an_unclaimed_set_is_never_a_finding():
    """What no group claims uses every group, so whatever it ran is declared."""
    seen = {"a", "b", "c"}
    declared = {"unclaimed": None, "tooling": None, "validate_x": None}
    found = _audit.findings(
        declared, dict.fromkeys(declared, seen), set(), set(), GROUPS
    )
    assert found == []


def test_a_dependency_of_a_declared_group_is_no_finding():
    """``b`` is built on ``a``: a set claiming ``b`` may run ``a``."""
    seen = _audit.ran(
        _export({"engine/src/a/a.cpp": (1, 1), "engine/src/b/b.cpp": (1, 1)}), GROUPS
    )
    found = _audit.findings({"group:b": {"b"}}, {"group:b": seen}, set(), set(), GROUPS)
    assert found == []


def test_paths_spelt_differently_overlap():
    """``a/./b`` and ``a//b/`` are one path, and a sibling is not."""
    assert _audit._overlap("a/./b", "a//b/")
    assert _audit._overlap("a/b/../b", "a")
    assert not _audit._overlap("a/b", "a/bc")


def test_a_covered_file_in_no_group_is_named():
    """A covered file under ``engine/src`` that no group owns, and no shared
    directory holds, is named; a file that never ran, or a shared one, is not."""
    export = _export(
        {
            "engine/src/stray.cpp": (2, 3),
            "engine/src/bindings/x.cpp": (1, 1),
            "engine/src/a/a.cpp": (1, 1),
            "engine/src/other/never.cpp": (0, 4),
        }
    )
    assert _audit.strays(export, GROUPS, ["engine/src/bindings"]) == [
        "engine/src/stray.cpp"
    ]
