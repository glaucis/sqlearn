"""The coverage and mutation presets: `coverage` measures our C++ with Homebrew
LLVM's source-based coverage (its llvm-profdata and llvm-cov read what its
clang writes), and `mutate` builds the groups with Mull's plugin for LLVM 23."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"


def _presets() -> dict[str, dict[str, Any]]:
    """Return the configure presets, by name."""
    data = json.loads((ENGINE / "CMakePresets.json").read_text())
    return {p["name"]: p for p in data["configurePresets"]}


def _recipe(name: str) -> str:
    """Return the body of the justfile's recipe `name`."""
    justfile = (REPO / "justfile").read_text()
    head = next(line for line in justfile.splitlines() if line.startswith(f"{name}"))
    return justfile.split(f"\n{head}\n", 1)[1].split("\n\n", 1)[0]


def test_coverage_and_mutate_build_our_groups_with_homebrew_llvm() -> None:
    """Each builds our groups alone, in its own flavour, with LLVM's toolchain,
    and has a build and a test preset."""
    presets = _presets()
    for name in ("coverage", "mutate"):
        preset = presets[name]
        assert preset["cacheVariables"]["SQ_FLAVOR"] == name
        assert preset["toolchainFile"].endswith("toolchain-llvm.cmake")
        assert preset["inherits"] == "base"
    data = json.loads((ENGINE / "CMakePresets.json").read_text())
    for kind in ("buildPresets", "testPresets"):
        assert {"coverage", "mutate"} <= {p["name"] for p in data[kind]}, kind


def test_the_coverage_flavour_instruments_with_source_based_coverage() -> None:
    """Clang's instrumentation, which llvm-cov reads, at -O0 and without the
    release hardening or a sanitizer."""
    text = (ENGINE / "cmake" / "hardening.cmake").read_text()
    body = text.split('elseif(SQ_FLAVOR STREQUAL "coverage")', 1)[1].split(
        "elseif(", 1
    )[0]
    assert "-fprofile-instr-generate" in body
    assert "-fcoverage-mapping" in body
    assert "-O0" in body
    assert "SQ_SANITIZERS" not in body


def test_the_mutate_flavour_loads_mulls_plugin() -> None:
    """Mull's frontend as a pass plugin, with the command line in the debug
    information (Mull's junk detection reads it)."""
    text = (ENGINE / "cmake" / "hardening.cmake").read_text()
    body = text.split('elseif(SQ_FLAVOR STREQUAL "mutate")', 1)[1].split("elseif(", 1)[
        0
    ]
    assert "-fpass-plugin=${SQ_MULL_PLUGIN}" in body
    assert "-grecord-command-line" in body


def test_just_coverage_engine_gates_on_the_coverage_preset() -> None:
    """The recipe builds the coverage preset and runs the gate."""
    recipe = _recipe("coverage-engine")
    assert '(build-engine "coverage")' in (REPO / "justfile").read_text()
    assert "validation._coverage" in recipe


def test_just_mutate_engine_runs_mull_on_the_mutate_preset() -> None:
    """The recipe fetches Mull when missing, builds the mutate preset and runs it."""
    justfile = (REPO / "justfile").read_text()
    assert 'mutate-engine: fetch-mull (build-engine "mutate")' in justfile
    assert "validation._mutate" in _recipe("mutate-engine")


def test_mull_yml_mutates_our_groups_alone() -> None:
    """Mull's config takes engine/src/ and leaves the bindings out, and keeps
    the list of survivors validation._mutate reads."""
    text = (ENGINE / "mull.yml").read_text()
    assert ".*/engine/src/.*" in text
    assert ".*/engine/src/bindings/.*" in text
    assert "survivors:" in text


@pytest.mark.skipif(shutil.which("cmake") is None, reason="no cmake")
def test_the_mutate_flavour_builds_without_ccache(tmp_path: Path) -> None:
    """Mull's plugin reads mull.yml while it compiles, which ccache cannot
    see, so the mutate flavour drops a ccache launcher an earlier configure
    of the build set, and sets none."""
    fake = tmp_path / "bin" / "ccache"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    script = tmp_path / "run.cmake"
    script.write_text(
        f'include("{(ENGINE / "cmake" / "ccache.cmake").as_posix()}")\n'
        'set(SQ_FLAVOR "mutate")\n'
        f'set(CMAKE_CXX_COMPILER_LAUNCHER "{fake.as_posix()}")\n'
        f'sq_ccache("{fake.parent.as_posix()}")\n'
        'message(STATUS "CXX=[${CMAKE_CXX_COMPILER_LAUNCHER}]")\n'
        'message(STATUS "C=[${CMAKE_C_COMPILER_LAUNCHER}]")\n'
    )
    out = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=True
    ).stdout
    assert "-- CXX=[]" in out
    assert "-- C=[]" in out
