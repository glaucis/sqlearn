"""Raw memory stays in the raw layer (ADR 0065): no file of the engine outside
engine/src/raw/ and its tests names the raw layer's allocation functions."""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The functions Buffer allocates and frees with; everything else holds a Buffer.
RAW = re.compile(r"\b(allocate_aligned|free_aligned)\b")

ALLOWED = ("engine/src/raw/", "engine/tests/raw/")


def test_the_raw_allocation_is_named_only_in_the_raw_layer():
    """allocate_aligned and free_aligned appear in engine/src/raw/ and its tests
    alone; the submodules are other repositories, so git lists none of them."""
    names = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "engine"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    found = []
    for name in names:
        path = REPO / name
        if name.startswith(ALLOWED) or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found += [f"{name}: {line}" for line in text.splitlines() if RAW.search(line)]
    assert found == []
