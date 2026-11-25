"""The CMake presets name the builds spec §3.9 lists, and none of them, nor
the flag files they read, turns on fast math."""

import json
import platform
import re
import shutil
import subprocess
import sys
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
    wanted = ["-U_FORTIFY_SOURCE", "-D_FORTIFY_SOURCE=3", "-fstack-protector-strong"]
    if platform.machine() in {"arm64", "aarch64"}:
        wanted.append("-mbranch-protection=standard")
    for build in builds:
        commands = json.loads(build.read_text())
        ours = [c for c in commands if c["file"].startswith(str(ENGINE / "src"))]
        assert ours, build
        for command in ours:
            flags = command["command"].split()
            for flag in wanted:
                assert flag in flags, (build, command["file"], flag)
            fortify = flags.index("-D_FORTIFY_SOURCE=3")
            assert flags.index("-U_FORTIFY_SOURCE") < fortify, (build, command["file"])


TEST_ONLY = re.compile(
    r"-fsanitize\S*|-DSQ_CRASH_TEST_HOOKS\S*"
    r"|\S*third_party/(?:catch2|rapidcheck|nanobench)\S*"
)
"""What only a test build has: a sanitizer, the crash group's test hooks, and
the include paths of the test-only libraries (Catch2, RapidCheck, nanobench)."""


def test_the_wheel_build_has_nothing_of_the_test_builds() -> None:
    """No compile command of the wheel's build sanitizes, turns on the crash
    group's test hooks, or reads a test-only library's headers: those never
    ship."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    for build in builds:
        commands = json.loads(build.read_text())
        assert commands, build
        found = [
            (c["file"], m.group(0))
            for c in commands
            for m in TEST_ONLY.finditer(c["command"])
        ]
        assert found == [], (build, found[:5])


def test_the_optimised_flavours_alone_carry_the_release_hardening() -> None:
    """release and profile take the hardening; _FORTIFY_SOURCE needs optimisation,
    so the dev, debug and sanitizer flavours go without it."""
    text = (ENGINE / "cmake" / "hardening.cmake").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    branches = re.split(r'\n(?:else)?if\(SQ_FLAVOR STREQUAL "', code)
    flavours = {b.split('"', 1)[0]: b for b in branches[1:]}
    assert set(flavours) >= {
        "dev",
        "debug",
        "release",
        "profile",
        "tsan",
        "lsan",
        "tysan",
    }
    for name, body in flavours.items():
        assert ("${SQ_RELEASE_HARDENING}" in body) == (name in {"release", "profile"})


def _stack_clash_probe(tmp_path: Path, compiler: str) -> tuple[bool, str]:
    """Configure a scratch project reading hardening.cmake with `compiler`;
    return the stack clash probe's result and the release hardening."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.29)\n"
        "project(probe LANGUAGES CXX)\n"
        f'include("{(ENGINE / "cmake" / "hardening.cmake").as_posix()}")\n'
        'message(STATUS "PROBE=${SQ_TAKES_STACK_CLASH_PROTECTION}")\n'
        'message(STATUS "HARDENING=${SQ_RELEASE_HARDENING}")\n'
    )
    done = subprocess.run(
        [
            "cmake",
            "-S",
            str(project),
            "-B",
            str(tmp_path / "build"),
            "-G",
            "Ninja",
            f"-DCMAKE_CXX_COMPILER={compiler}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = done.stdout.splitlines()
    probe = next(x for x in lines if "-- PROBE=" in x).split("=", 1)[1]
    hardening = next(x for x in lines if "-- HARDENING=" in x).split("=", 1)[1]
    return probe in {"1", "ON", "TRUE"}, hardening


@pytest.mark.skipif(
    shutil.which("cmake") is None or shutil.which("ninja") is None,
    reason="cmake and ninja: just doctor",
)
@pytest.mark.parametrize(
    ("compiler", "takes"),
    [
        # Apple clang ignores it on arm64 macOS, and says so as a warning.
        ("c++", False),
        # GCC takes it: the probe must not ask GCC for a Clang-only option.
        ("g++-16", True),
    ],
)
def test_the_stack_clash_probe_asks_each_compiler_its_own_way(
    tmp_path: Path, compiler: str, takes: bool
) -> None:
    """The probe passes Clang's -Werror for an unused argument to Clang alone;
    GCC refuses that option, which made the probe false on GCC every time."""
    if shutil.which(compiler) is None:
        pytest.skip(f"no {compiler} here")
    if compiler == "c++" and not (
        sys.platform == "darwin" and platform.machine() == "arm64"
    ):
        pytest.skip("Apple clang on arm64 macOS")
    found, hardening = _stack_clash_probe(tmp_path, shutil.which(compiler) or "")
    assert found == takes
    assert ("-fstack-clash-protection" in hardening) == takes


def test_clangd_reads_the_llvm_dev_compile_database() -> None:
    """The root .clangd points clangd at llvm-dev's compile_commands.json, the
    build of Homebrew LLVM, whose clangd it is (spec §3.8)."""
    assert "llvm-dev" in _configure_presets()
    text = (REPO / ".clangd").read_text()
    found = re.search(r"^\s*CompilationDatabase:\s*(\S+)\s*$", text, re.MULTILINE)
    assert found is not None
    assert found.group(1) == "engine/build/llvm-dev"
