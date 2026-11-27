"""The audit of the groups' claims: what a set or runner ran against what it
declares.

On llvm-cov exports written by hand (no coverage build in the fast tests),
for groups ``a``, ``b`` built on it, and ``c``; ``a`` and ``b`` claim the
tests under ``tests/src/a`` and ``tests/src/b``.
"""

from validation import _audit, _groups

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
        GROUPS,
    )
    assert found == [
        "group:b ran c: Fix: add it to sq_add_group(c PYTHON_TESTS tests/src/b)",
        "validate_b ran c: Fix: add it to sq_add_group(c VALIDATION validate_b)",
    ]


def test_startup_groups_are_no_finding():
    """What a bare ``import sqlearn`` ran belongs to the shared part."""
    start = _audit.startup(_export({"engine/src/c/c.cpp": (2, 2)}), GROUPS)
    assert start == {"c"}
    seen = _audit.ran(
        _export({"engine/src/a/a.cpp": (1, 2), "engine/src/c/c.cpp": (2, 2)}), GROUPS
    )
    assert _audit.findings({"group:a": {"a"}}, {"group:a": seen}, start, GROUPS) == []


def test_an_unclaimed_set_is_never_a_finding():
    """What no group claims uses every group, so whatever it ran is declared."""
    seen = {"a", "b", "c"}
    declared = {"unclaimed": None, "tooling": None, "validate_x": None}
    found = _audit.findings(declared, dict.fromkeys(declared, seen), set(), GROUPS)
    assert found == []


def test_a_dependency_of_a_declared_group_is_no_finding():
    """``b`` is built on ``a``: a set claiming ``b`` may run ``a``."""
    seen = _audit.ran(
        _export({"engine/src/a/a.cpp": (1, 1), "engine/src/b/b.cpp": (1, 1)}), GROUPS
    )
    assert _audit.findings({"group:b": {"b"}}, {"group:b": seen}, set(), GROUPS) == []
