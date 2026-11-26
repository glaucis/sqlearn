"""No nanobind type of sqlearn's own is bound yet, so nanobind's leak report
has nothing of ours to report (docs/architecture/testing.md)."""

import re
from pathlib import Path

BINDINGS = Path(__file__).resolve().parents[2] / "engine" / "src" / "bindings"

BOUND_TYPE = re.compile(r"\bnb::(?:class_|enum_|exception)\b")
"""How the bindings would bind a type of their own."""


def test_the_bindings_bind_no_type_of_their_own():
    """When a type is bound, its leaks need a check: this fails until then."""
    sources = sorted(BINDINGS.rglob("*.[ch]pp"))
    assert sources, f"no C++ file under {BINDINGS}: the test would check nothing"
    found = [
        f"{path.relative_to(BINDINGS.parents[2])}:{n}"
        for path in sources
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if BOUND_TYPE.search(line)
    ]
    assert found == [], (
        f"engine/src/bindings binds a nanobind type of its own ({', '.join(found)}).\n"
        "Fix: add a leak check for it (nanobind's leak report for sqlearn's "
        "types, docs/architecture/testing.md), then remove this test"
    )
