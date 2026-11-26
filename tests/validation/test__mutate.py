"""Mutation testing of our C++: the survivors Mull reports, the ones
engine/mull.yml keeps with a reason, and the verdict between them."""

import re
from pathlib import Path

import pytest

from validation import _mutate

ENGINE = Path("/e/engine")

REPO = Path(__file__).resolve().parents[2]

VERSION_CPP = REPO / "engine" / "src" / "core" / "version.cpp"
"""Left out of Mull (engine/mull.yml): it must hold nothing Mull could mutate."""

IDENTITY_CALLS = {"build_identity", "describe", "format", "substr"}
"""The two functions version.cpp defines, and the two calls describe() makes."""


def _logic_in(text: str) -> list[str]:
    """Return what in C++ `text` goes beyond the build identity's definitions:
    a branch or loop, an operator, an assignment other than a constant's, a
    call other than those of IDENTITY_CALLS."""
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.DOTALL)
    code = re.sub(r"^\s*#.*?(?<!\\)$", "", code, flags=re.MULTILINE | re.DOTALL)
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
    keywords = r"if|else|for|while|do|switch|case|goto|try|catch|throw"
    found: list[str] = re.findall(rf"\b(?:{keywords})\b", code)
    found += re.findall(r"&&|\|\||[-+*/%<>!?|^~]", code)
    found += [
        m.group(0)
        for m in re.finditer(r"=", code)
        if not re.search(r"\bconstexpr\b[^;=]*$", code[: m.start()])
    ]
    found += [
        c
        for c in re.findall(r"(\w+)\s*\(", code)
        if c not in IDENTITY_CALLS and not re.fullmatch(keywords, c)
    ]
    return found


def _mutant(path: str, line: int, column: int, mutator: str, status: str):
    """Return one mutant as Mull's Elements report writes it."""
    return {
        "id": f"{mutator}:{path}:{line}:{column}:{line}:{column + 1}",
        "mutatorName": mutator,
        "location": {"start": {"line": line, "column": column}},
        "status": status,
    }


def test_a_survivor_is_a_mutant_no_test_killed():
    """Survived and NoCoverage are survivors, named by the path under engine/,
    the line, the column and the mutator; a killed mutant or one that timed
    out is not."""
    a = str(ENGINE / "src/core/a.cpp")
    b = str(ENGINE / "src/raw/b.hpp")
    report = {
        "files": {
            a: {
                "mutants": [
                    _mutant(a, 3, 7, "cxx_add_to_sub", "Survived"),
                    _mutant(a, 4, 1, "cxx_eq_to_ne", "Killed"),
                    _mutant(a, 5, 2, "cxx_lt_to_le", "Timeout"),
                ]
            },
            b: {"mutants": [_mutant(b, 9, 4, "cxx_remove_void_call", "NoCoverage")]},
        }
    }
    assert _mutate.survivors(report, ENGINE) == {
        "src/core/a.cpp:3:7:cxx_add_to_sub",
        "src/raw/b.hpp:9:4:cxx_remove_void_call",
    }


def test_the_recorded_survivors_are_read_with_their_reasons():
    """Each entry of mull.yml's survivors list, its mutant and its reason."""
    text = (
        "mutators:\n  - cxx_all\n"
        "# survivors: a comment, never an entry\n"
        "survivors:\n"
        "  - mutant: src/core/a.cpp:3:7:cxx_add_to_sub\n"
        "    reason: the sum is never read\n"
        "  - mutant: src/raw/b.hpp:9:4:cxx_remove_void_call\n"
        "    reason: a hint to the allocator, with no effect a test can see\n"
    )
    assert _mutate.recorded(text) == {
        "src/core/a.cpp:3:7:cxx_add_to_sub": "the sum is never read",
        "src/raw/b.hpp:9:4:cxx_remove_void_call": (
            "a hint to the allocator, with no effect a test can see"
        ),
    }
    assert _mutate.recorded("survivors: []\n") == {}


@pytest.mark.parametrize(
    "text",
    [
        "survivors:\n  - mutant: src/a.cpp:1:1:cxx_add_to_sub\n",
        "survivors:\n  - mutant: src/a.cpp:1:1:cxx_add_to_sub\n    reason:\n",
        "survivors:\n  - mutant: src/a.cpp:1:1:x\n    reason: r\n"
        "  - mutant: src/a.cpp:1:1:x\n    reason: again\n",
        "survivors:\n  - src/a.cpp:1:1:x\n",
        "mutators:\n  - cxx_all\n",
    ],
    ids=["no reason", "empty reason", "twice", "not an entry", "no list"],
)
def test_an_entry_without_its_reason_is_refused(text):
    """A mutant kept with no reason, twice, a line that is no entry, or a
    config without the list: each is refused, naming the fix."""
    with pytest.raises(ValueError, match="Fix:"):
        _mutate.recorded(text)


def test_the_verdict_names_unrecorded_survivors_and_stale_entries():
    """A survivor with no entry fails; so does an entry whose mutant no
    longer survives (the code or the tests changed), so the list stays true."""
    found = {"a:1:1:m", "b:2:2:m"}
    kept = {"b:2:2:m": "why", "c:3:3:m": "why"}
    assert _mutate.verdict(found, kept) == (["a:1:1:m"], ["c:3:3:m"])
    assert _mutate.verdict({"b:2:2:m"}, {"b:2:2:m": "why"}) == ([], [])


def test_the_file_left_out_of_mull_holds_only_the_build_identity():
    """engine/mull.yml leaves core/version.cpp out, since it has nothing to
    mutate: the file keeps no branch, operator or call beyond describe()'s
    format and substr, so the exclusion hides no logic."""
    assert "engine/src/core/version" in (REPO / "engine" / "mull.yml").read_text()
    assert _logic_in(VERSION_CPP.read_text()) == []


@pytest.mark.parametrize(
    ("added", "found"),
    [
        ("if (identity.compiler.empty()) {}", ["if", "empty"]),
        ("int n = identity.build_type.size() + 1;", ["+", "=", "size"]),
        ("auto x = std::max(1, 2);", ["=", "max"]),
    ],
)
def test_logic_added_to_the_build_identity_is_found(added, found):
    """A branch, an operator or another call added to version.cpp is found,
    each by what it adds."""
    text = VERSION_CPP.read_text().replace(
        "std::string describe(const BuildIdentity &identity) {",
        "std::string describe(const BuildIdentity &identity) {\n    " + added,
    )
    assert sorted(_logic_in(text)) == sorted(found)
