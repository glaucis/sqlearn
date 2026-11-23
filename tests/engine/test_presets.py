"""The CMake presets name the builds spec §3.9 lists, and none of them, nor
the flag files they read, turns on fast math."""

import json
import platform
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
PRESETS = ENGINE / "CMakePresets.json"

# Flags that let the compiler change a floating-point result (ADR 0063).
FAST_MATH = re.compile(
    r"-ffast-math|-Ofast|-funsafe-math-optimizations|-fassociative-math"
    r"|-freciprocal-math|-ffinite-math-only|-fno-signed-zeros"
)


def _configure_presets() -> dict[str, dict[str, Any]]:
    """Return the configure presets of CMakePresets.json, by name."""
    data = json.loads(PRESETS.read_text())
    return {p["name"]: p for p in data["configurePresets"]}


def test_every_preset_named_in_the_spec_exists() -> None:
    """Spec §3.9's presets, and llvm-dev, are in CMakePresets.json."""
    assert {"dev", "debug", "release", "profile", "llvm-dev"} <= set(
        _configure_presets()
    )


def test_every_preset_builds_in_its_own_directory() -> None:
    """Each preset builds in engine/build/<preset>."""
    presets = _configure_presets()
    for name, preset in presets.items():
        if preset.get("hidden"):
            continue
        binary_dir = preset.get("binaryDir")
        parent = preset
        while binary_dir is None and "inherits" in parent:
            inherits = parent["inherits"]
            parent = presets[inherits if isinstance(inherits, str) else inherits[0]]
            binary_dir = parent.get("binaryDir")
        assert binary_dir == "${sourceDir}/build/${presetName}", name


def test_no_preset_sets_fast_math() -> None:
    """No preset or flag file has a flag that changes floating-point results."""
    texts = [PRESETS.read_text()]
    texts += [p.read_text() for p in sorted((ENGINE / "cmake").glob("*.cmake"))]
    texts.append((ENGINE / "CMakeLists.txt").read_text())
    for text in texts:
        code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        assert not FAST_MATH.search(code)


def test_our_sources_never_contract_to_fma() -> None:
    """Our sources compile with FMA contraction off (spec §3.9)."""
    assert "-ffp-contract=off" in (ENGINE / "cmake" / "warnings.cmake").read_text()


def test_the_wheel_compiles_our_sources_with_the_strict_flags() -> None:
    """The wheel's build gives the groups, bindings and extension the strict flags,
    with -Wunsafe-buffer-usage off in the raw layer alone (ADR 0065)."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    commands = json.loads(builds[0].read_text())
    ours = [
        c
        for c in commands
        if c["file"].startswith(str(ENGINE / "src"))
        or c["file"].startswith(str(ENGINE / "extension"))
    ]
    files = {Path(c["file"]).name for c in ours}
    assert {
        "error.cpp",
        "parse_version.cpp",
        "version.cpp",
        "buffer.cpp",
        "module.cpp",
        "connection.cpp",
        "sqlearn_extension.cpp",
    } <= files
    raw = str(ENGINE / "src" / "raw")
    for command in ours:
        flags = command["command"].split()
        for flag in ("-Wconversion", "-Werror", "-ffp-contract=off"):
            assert flag in flags, (command["file"], flag)
        in_raw = command["file"].startswith(raw)
        assert ("-Wunsafe-buffer-usage" in flags) != in_raw, command["file"]
        assert "-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST" in flags, command[
            "file"
        ]


def test_the_wheel_compiles_our_sources_with_the_release_hardening() -> None:
    """The wheel's build gives our sources OpenSSF's release hardening: fortified
    libc calls, the stack protector, and on arm64 branch protection."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    commands = json.loads(builds[0].read_text())
    ours = [c for c in commands if c["file"].startswith(str(ENGINE / "src"))]
    assert ours
    wanted = ["-U_FORTIFY_SOURCE", "-D_FORTIFY_SOURCE=3", "-fstack-protector-strong"]
    if platform.machine() in {"arm64", "aarch64"}:
        wanted.append("-mbranch-protection=standard")
    for command in ours:
        flags = command["command"].split()
        for flag in wanted:
            assert flag in flags, (command["file"], flag)
        assert flags.index("-U_FORTIFY_SOURCE") < flags.index("-D_FORTIFY_SOURCE=3")


def test_the_optimised_flavours_alone_carry_the_release_hardening() -> None:
    """release and profile take the hardening; _FORTIFY_SOURCE needs optimisation,
    so the dev, debug and sanitizer flavours go without it."""
    text = (ENGINE / "cmake" / "hardening.cmake").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    branches = re.split(r'\n(?:else)?if\(SQ_FLAVOR STREQUAL "', code)
    flavours = {b.split('"', 1)[0]: b for b in branches[1:]}
    assert set(flavours) >= {"dev", "debug", "release", "profile", "tsan", "lsan"}
    for name, body in flavours.items():
        assert ("${SQ_RELEASE_HARDENING}" in body) == (name in {"release", "profile"})
