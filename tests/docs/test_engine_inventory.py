"""Tests of docs/architecture/engine-inventory.md, the native engine's map."""

import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "src" / "sqlearn"
INVENTORY = REPO / "docs" / "architecture" / "engine-inventory.md"
ROW = re.compile(r"^\| `(?P<module>[^`]+\.py)` \| (?P<phase>[^|]*?) \|")


def test_the_inventory_gives_every_module_its_phase():
    """Every module of src/sqlearn has one row, and every row a phase."""
    rows = [
        found
        for line in INVENTORY.read_text().splitlines()
        if (found := ROW.match(line))
    ]
    listed = Counter(row["module"] for row in rows)
    modules = {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")}
    twice = sorted(module for module, count in listed.items() if count > 1)
    assert not twice, f"the inventory lists these modules twice: {twice}"
    missing = sorted(modules - set(listed))
    assert not missing, f"the inventory has no row for: {missing}"
    stale = sorted(set(listed) - modules)
    assert not stale, f"the inventory lists modules that do not exist: {stale}"
    phases = {row["module"]: row["phase"] for row in rows}
    wrong = sorted(f"{m}: {p!r}" for m, p in phases.items() if p not in {"2", "3", "4"})
    assert not wrong, f"these rows' phase is not 2, 3 or 4: {wrong}"
