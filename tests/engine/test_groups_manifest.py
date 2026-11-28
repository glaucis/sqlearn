"""The groups' manifest the wheel's build writes at configure.

`build/<tag>/sq_groups.json` names each C++ group, its directory, the groups
it depends on and what it claims (Python tests, validation runners,
benchmarks), so the checks rerun only what a change to a group affects.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from validation import _groups

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / _groups.WHEEL_BUILD / "sq_groups.json"


def _manifest() -> dict[str, Any]:
    """Return the manifest the wheel's build wrote."""
    return json.loads(MANIFEST.read_text())  # type: ignore[no-any-return]


def test_the_manifest_names_every_group() -> None:
    """Each group is listed in definition order, with its dependencies and claims."""
    groups = _manifest()["groups"]
    assert [g["name"] for g in groups] == ["core", "raw", "crash"]
    by_name = {g["name"]: g for g in groups}
    assert by_name["core"]["depends"] == []
    assert by_name["raw"]["depends"] == ["core"]
    assert by_name["crash"]["depends"] == ["core", "raw"]
    for group in groups:
        assert group["dir"] == f"engine/src/{group['name']}"
        for claim in ("python_tests", "validation"):
            assert group[claim] == []
        assert group["bench"] == (["buffer"] if group["name"] == "raw" else [])


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


@pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake is not installed")
def test_a_name_with_a_quote_or_backslash_writes_valid_json(tmp_path: Path) -> None:
    """The manifest's strings are escaped: a quote or a backslash in a name or
    a claimed path leaves it valid JSON, and today's names are unchanged."""
    script = tmp_path / "run.cmake"
    script.write_text(
        f'include("{(REPO / "engine/cmake/groups.cmake").as_posix()}")\n'
        'sq_json_list(plain "tests/src/a" "tests/src/b")\n'
        'sq_json_list(odd [[a\\b]] [[say "hi"]])\n'
        'sq_json_string(name [[x"y\\z]])\n'
        'message(STATUS "plain=${plain}")\n'
        'message(STATUS "odd=${odd}")\n'
        'message(STATUS "name=${name}")\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=True
    )
    found = dict(
        line.removeprefix("-- ").split("=", 1) for line in done.stdout.splitlines()
    )
    assert found["plain"] == '["tests/src/a", "tests/src/b"]'
    assert json.loads(found["odd"]) == ["a\\b", 'say "hi"']
    assert json.loads(found["name"]) == 'x"y\\z'
