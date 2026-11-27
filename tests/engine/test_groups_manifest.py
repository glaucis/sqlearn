"""The groups' manifest the wheel's build writes at configure.

`build/<tag>/sq_groups.json` names each C++ group, its directory, the groups
it depends on and what it claims (Python tests, validation runners,
benchmarks), so the checks rerun only what a change to a group affects.
"""

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "build" / "cpython-312" / "sq_groups.json"


def _manifest() -> dict[str, Any]:
    """Return the manifest the wheel's build wrote."""
    return json.loads(MANIFEST.read_text())  # type: ignore[no-any-return]


def test_the_manifest_names_every_group() -> None:
    """Each group is listed in definition order, with its dependencies."""
    groups = _manifest()["groups"]
    assert [g["name"] for g in groups] == ["core", "raw", "crash"]
    by_name = {g["name"]: g for g in groups}
    assert by_name["core"]["depends"] == []
    assert by_name["raw"]["depends"] == ["core"]
    assert by_name["crash"]["depends"] == ["core", "raw"]
    for group in groups:
        assert group["dir"] == f"engine/src/{group['name']}"
        for claim in ("python_tests", "validation", "bench"):
            assert group[claim] == []


def test_every_source_directory_is_a_group_or_shared() -> None:
    """A directory under engine/src is a group's or a shared one."""
    manifest = _manifest()
    known = {g["dir"] for g in manifest["groups"]} | set(manifest["shared"])
    on_disk = {
        f"engine/src/{p.name}"
        for p in (REPO / "engine" / "src").iterdir()
        if p.is_dir()
    }
    assert on_disk <= known
    assert manifest["shared"] == ["engine/src/bindings", "engine/extension"]
