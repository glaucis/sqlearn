"""Mutation testing of our C++: the survivors Mull reports, the ones
engine/mull.yml keeps with a reason, and the verdict between them."""

import re
from pathlib import Path

import pytest

from validation import _mutate

ENGINE = Path("/e/engine")

REPO = Path(__file__).resolve().parents[2]


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


def test_mull_leaves_out_only_the_bindings():
    """engine/mull.yml mutates every source of engine/src but the bindings,
    which are built only in the wheel and run from Python, so no group's
    code escapes Mull."""
    text = (REPO / "engine" / "mull.yml").read_text()
    block = re.search(r"^excludePaths:\n((?:  .*\n)+)", text, re.MULTILINE)
    assert block is not None
    paths = [
        line.strip().removeprefix("- ").strip('"')
        for line in block.group(1).splitlines()
        if line.strip().startswith("- ")
    ]
    assert paths == [".*/engine/src/bindings/.*"]


def test_a_mutant_outside_the_engine_is_refused_with_a_fix():
    """A report naming a file outside engine/ gives a Fix line, not a bare
    ValueError from the path arithmetic."""
    other = "/elsewhere/x.cpp"
    report = {"files": {other: {"mutants": [_mutant(other, 1, 1, "m", "Survived")]}}}
    with pytest.raises(ValueError, match="Fix:"):
        _mutate.survivors(report, ENGINE)
